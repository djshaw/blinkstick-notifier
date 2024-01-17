from functools import partial
import datetime
import http
from http.server import BaseHTTPRequestHandler
import logging
import os
import requests
import sqlite3
import sys
import threading
import yaml

from prometheus_client import start_http_server, Gauge
from prometheus_client.core import REGISTRY

from pymongo import MongoClient

from navbar import Navbar
from websocketClient import WebsocketClient
from workunit import WorkQueue, Workunit, installWorkunitsCollector

logging.basicConfig( level=logging.DEBUG )

up =    Gauge(
        'up',
        'Whether or not the bitbucket client is running' )
up.set( 0 )

httpPathPrefix  = os.environ["HTTP_PATH_PREFIX"] if "HTTP_PATH_PREFIX" in os.environ else "/bitbucket"
configFile      = os.environ["CONFIG_FILE"]      if "CONFIG_FILE"      in os.environ else "/app/config.yml"

class JsonDataAccess( object ):
    def __init__( self, json ):
        self._json = json

    def json( self ):
        return self._json


class UserDataAccess( JsonDataAccess ):
    def __init__( self, json ):
        super().__init__( json )

    def getUuid( self ):
        return self._json["uuid"]

    def getUsername( self ):
        return self._json["username"]


# TODO: there's got to be a library for all of this
class PipelineDataAccess( JsonDataAccess ):
    def __init__( self, json ):
        super().__init__( json )

    def getUuid( self ):
        return self._json["uuid"]

    def getSuccessful( self ):
        return self._json["state"]["type"] == "pipeline_state_completed" and \
               self._json["state"]["result"]["name"] == "pipeline_state_completed_successful"

    def getFailure( self ):
        return self._json["state"]["type"] == "pipeline_state_completed" and \
               self._json["state"]["result"]["type"] == "pipeline_state_completed_failed"

    def getCreator( self ):
        # TODO: can I return a UserDataAccess?
        return self._json["creator"]["uuid"]

    def getRepository( self ):
        # TODO: can I return a RepositoryDataAccess?
        return self._json["repository"]["full_name"]


class PipelineStepDataAccess( JsonDataAccess ):
    def __init__( self, json ):
        super().__init__( json )

    def getSuccessful( self ):
        # TODO: verify the string
        # TODO: presumably, if a step was restarted, we'd see it in self._json["state"][...]
        return self._json["state"]["type"] == "pipeline_state_completed_successful"

    def getFailure( self ):
        # TODO: verify the string
        return self._json["state"]["type"] == "pipeline_state_completed_failure"


class BitbucketDataAccess( object ):
    def __init__( self, workspace, username, password ):
        self._workspace = workspace
        self._session = requests.Session()
        self._session.auth = (username, password)

    def getCurrentUser( self ) -> UserDataAccess:
        result = self._session.get( "https://api.bitbucket.org/2.0/user" )
        return UserDataAccess( result.json() )

    def getUser( self, identifier: str ) -> UserDataAccess:
        result = self._session.get( "https://api.bitbucket.org/2.0/users/" + str( identifier ) )
        return UserDataAccess( result.json() )

    def listPipelines( self, repository: str ):
        result = []
        # TODO: query for more pages of pipelines
        # sort=-created_on :                               order by created, descending
        # fields%3D%2Bvalues.creator%2C%2Bvalues.trigger : fields=+values.creator,+values.trigger
        url = "https://api.bitbucket.org/2.0/repositories/" + self._workspace + "/" \
                + str( repository ) + "/pipelines?" \
                + "pagelen=200&fields%3D%2Bvalues.creator%2C%2Bvalues.trigger" \
                + "&sort=-created_on"
        while True:
            pipelines = self._session.get( url ).json()
            for pipeline in pipelines["values"]:
                result.append( PipelineDataAccess( pipeline ) )

            if "next" in pipelines and pipelines["next"] != None:
                url = pipelines["next"]
            else:
                break

            if len( result ) > 100:
                break

            # TODO: also check to see if the age is >= C
        # TODO: return a list of pipeline steps
        return result

    def listPipelineSteps( self, pipelineDataAccess: PipelineDataAccess ) -> PipelineStepDataAccess:
        pipelineSteps = self._session.get(
              "https://api.bitbucket.org/2.0" \
            + "/repositories/" + pipelineDataAccess.getRepository() \
            + "/pipelines/" + pipelineDataAccess.getUuid() \
            + "/steps" )
        # TODO: must check for a pipelineSteps["next"] value!
        result = []
        for value in pipelineSteps.json()["values"]:
            result.append( PipelineStepDataAccess( value ) )
        return result


class MongoDataAccess( object ):
    def __init__( self, connectionString ):
        self._database = MongoClient( connectionString )["bitbucket"]

    def setKeyValue( self, key, value ):
        self._database["properties"].update_one( { "_id": key }, { "$set": { key: value } }, upsert=True )

    # TODO: this isn't rendering in mongo-express as key-value. It's being rendered as _id/currentUesr
    def setCurrentUser( self, userDataAccess ):
        self.setKeyValue( "currentUser", userDataAccess.getUuid() )
        self.setUser( userDataAccess )

    def setUser( self, userDataAccess ):
        self._database["users"].update_one( { "_id": userDataAccess.getUuid() }, { "$set": userDataAccess.json() }, upsert=True )

    def getUser( self, uuid ) -> UserDataAccess:
        user = self._database["users"].find( { "_id": uuid } )
        if user is None:
            return None
        return UserDataAccess( user[0] )

    def getCurrentUser( self ) -> UserDataAccess:
        currentUserUuid = self._database["properties"].find({"_id": "currentUser"})
        uuid = currentUserUuid[0]["currentUser"]
        if uuid is None:
            return None
        return self.getUser( uuid )

    def savePipeline( self, pipelineDataAccess ):
        pass


class BuildFailureManager( object ):
    def __init__( self, ws, config ):
        self._ws = ws
        self._config = config
        self._failures = {}

    def getFailures( self ):
        return self._failures

    def setFailedBuild( self, repository, pipelineUuid ):
        hadFailure = len( self._failures )

        self._failures[repository] = pipelineUuid
        if not hadFailure and "notification" in self._config:
            self._ws.enable( self._config["notification"] )
        logging.info( str( self._failures ) )

    def clearFailedBuild( self, repository, pipelineUuid ):
        # TODO: There's a readers/writers race condition here
        if repository in self._failures:
            del self._failures[repository]

        logging.info( str( self._config ) )
        if len( self._failures ) == 0 and "notification" in self._config:
            self._ws.disable( self._config["notification"] )

        logging.info( str( self._failures ) )


class PipelineWorkunit( Workunit ):
    # TODO: rename pipeline to repository!
    def __init__( self, buildFailureManager: BuildFailureManager, df, periodSeconds, bitbucket, workqueue, mongoDataAccess, repository ):
        super().__init__( df )

        self._buildFailureManager = buildFailureManager
        self._periodSeconds = periodSeconds
        self._bitbucket = bitbucket
        self._workqueue = workqueue
        self._mongoDataAccess = mongoDataAccess
        self._repository = repository


    def work( self ):
        try:
            currentUser = self._mongoDataAccess.getCurrentUser()

            # TODO: return a list of PipelineDataAccess objects
            pipelines = self._bitbucket.listPipelines( self._repository )
            # TODO: Don't report any failed pipelines that occurred before the
            # system started (not necessarily just this container!)
            logging.info( "found " + str( len( pipelines ) ) + " " + self._repository + " pipeline(s)" )

            if pipelines[0].getFailure():
                self._buildFailureManager.setFailedBuild( self._repository, pipelines[0].getUuid() )
            else:
                self._buildFailureManager.clearFailedBuild( self._repository, pipelines[0].getUuid() )

            for pipeline in pipelines:
                # TODO: don't skip checking the main branch?
                if pipeline.getCreator() != currentUser.getUuid():
                    continue

                if not pipeline.getFailure():
                    continue

                logging.info( "found failed pipeline" )

                # TODO: the intent was to save the pipeline to mongo so it doesn't need to be
                # queried again, and instead we can skip straight to querying the pipeline steps
                # TODO: do not query pipelines were we already kicked a restart
                steps = self._bitbucket.listPipelineSteps( pipeline )
                for step in steps:
                    if not step.getFailure():
                        continue

                    if not step.alreadyRetried():
                        # TODO: rerun failed steps blocked by https://jira.atlassian.com/browse/BCLOUD-21591,
                        # https://jira.atlassian.com/browse/BCLOUD-21608
                        break


        except Exception as e:
            logging.exception( e )
            # TODO: prometheus workunit exception

        finally:
            try:
                future = datetime.datetime.now() + datetime.timedelta( seconds=self._periodSeconds )
                self._workqueue.enqueue(
                    PipelineWorkunit(
                        self._buildFailureManager,
                        future,
                        self._periodSeconds,
                        self._bitbucket,
                        self._workqueue,
                        self._mongoDataAccess,
                        self._repository ) )
            except Exception as e:
                logging.exception( e )
                # TODO: prometheus workunit exception

def getHandler( buildFailureManager ):
    class HTTPRequestHandler( BaseHTTPRequestHandler ):
        def do_GET( self ):
            response = None
            status = 500
            headers = {}

            try:
                if self.path.startswith( httpPathPrefix ):
                    response = """
                        <html>
                            <head>
                                <link rel="stylesheet"
                                      href="https://cdn.jsdelivr.net/npm/bootstrap@4.0.0/dist/css/bootstrap.min.css"
                                      integrity="sha384-Gn5384xqQ1aoWXA+058RXPxPg6fy4IWvTNh0E263XmFcJlSAwiGgFAW/dAiS6JXm"
                                      crossorigin="anonymous">
                                <script src="https://code.jquery.com/jquery-3.2.1.slim.min.js" integrity="sha384-KJ3o2DKtIkvYIK3UENzmM7KCkRr/rE9/Qpg6aAZGJwFDMVNA/GpGFF93hXpG5KkN" crossorigin="anonymous"></script>
                                <script src="https://cdn.jsdelivr.net/npm/popper.js@1.12.9/dist/umd/popper.min.js" integrity="sha384-ApNbgh9B+Y1QKtv3Rn7W3mgPxhU9K/ScQsAP7hUibX39j7fakFPskvXusvfa0b4Q" crossorigin="anonymous"></script>
                                <script src="https://cdn.jsdelivr.net/npm/bootstrap@4.0.0/dist/js/bootstrap.min.js" integrity="sha384-JZR6Spejh4U02d8jOt6vLEHfe/JQGiRRSQQxSfFWpi1MquVdAyjUar5+76PVCmYl" crossorigin="anonymous"></script>
                                <style>
                                    pre {
                                      border-radius: 10px;
                                      font-family: Consolas,monospace;
                                      margin-bottom: 10px;
                                      overflow: auto;
                                      padding: 10px;
                                    }
                                </style>
                            </head>
                            <body>
                            """ \
                        + Navbar().render() \
                        + """
                                <table>
                                    <tr>
                                        <td>Failing Build</td>
                                        <td>id</td>
                                    </tr>"""

                    failures = buildFailureManager.getFailures()
                    for repository in failures:
                        response += "<tr><td>" + repository + "</td><td>" + failures[repository] + "</td></tr>"

                    response += """
                                </table>
                            </body>
                        </html>"""

            except Exception as e:
                logging.exception( e )

            finally:
                self.send_response( status )
                for key in headers:
                    self.send_header( key, headers[key] )
                self.end_headers()
                if response != None:
                    if type( response ) is str:
                        response = response.encode( "utf-8" )
                    self.wfile.write( response )
    return HTTPRequestHandler


def main( args ):
    if os.path.exists( configFile ):
        with open( configFile, 'r' ) as f:
            config = yaml.safe_load( f )
    else:
        logging.warning( "Warning: using an empty config file" )
        config = []


    # start prometheus
    start_http_server( 9000 )

    ws = WebsocketClient( "ws://led-controller:9099",
                          name="Bitbucket",
                          httpPathPrefix=httpPathPrefix )
    ws.start()


    buildFailureManager = BuildFailureManager( ws, config )
    def httpdService():
        # TODO: make port configurable
        httpd = http.server.HTTPServer( ('', 8080), getHandler( buildFailureManager) )
        httpd.serve_forever()
    httpd = threading.Thread( target=httpdService )
    httpd.start()

    bitbucket = BitbucketDataAccess( config["workspace"], config["user"], config["token"] )


    mongoDataAccess = MongoDataAccess( "mongodb://mongo/bitbucket" )
    currentUser = bitbucket.getCurrentUser()
    if currentUser == None:
        logging.error( "Couldn't get the current user!" )
        return 1
    mongoDataAccess.setCurrentUser( currentUser )

    workqueue = WorkQueue()
    installWorkunitsCollector( workqueue )

    for pipeline in config["pipelines"]:
        # TODO: make period configurable
        # TODO: the first workunit should be scheduled immediately
        workqueue.enqueue(
            PipelineWorkunit(
                buildFailureManager,
                datetime.datetime.now(),
                60,
                bitbucket,
                workqueue,
                mongoDataAccess,
                pipeline ) )

    workqueue.start()
    up.set( 1 )

    while True:
        import time
        time.sleep( 10 )


if __name__ == "__main__":
    sys.exit( main( sys.argv ) )

