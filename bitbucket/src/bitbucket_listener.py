import argparse
import datetime
from http.server import SimpleHTTPRequestHandler
import logging
import sys

from typing import Any, List, Type, override
from atlassian.bitbucket import Cloud
from atlassian.bitbucket.cloud.repositories.pipelines import Pipeline
import pymongo
from pymongo import MongoClient
import requests

from myblinkstick.navbar import Navbar
from myblinkstick.workqueue import Workunit
from myblinkstick.application import Sensor

class JsonDataAccess( object ):
    def __init__( self, json ):
        self._json = json

    # dict[str, str | this type | array | none | number]
    def json( self ) -> dict:
        return self._json


class UserDataAccess( JsonDataAccess ):
    def get_uuid( self ) -> str:
        return self._json["uuid"]

    def get_username( self ) -> str:
        return self._json["username"]


# TODO: there's got to be a library for all of this
#           THERE IS!  Use atlassian-python-api
class PipelineDataAccess( JsonDataAccess ):
    def get_uuid( self ) -> str:
        return self._json["uuid"]

    def get_successful( self ) -> bool:
        return self._json["state"]["type"] == "pipeline_state_completed" and \
               self._json["state"]["result"]["name"] == "pipeline_state_completed_successful"

    def get_failure( self ) -> bool:
        return self._json["state"]["type"] == "pipeline_state_completed" and \
               self._json["state"]["result"]["type"] == "pipeline_state_completed_failed"


class BitbucketDataAccess( object ):
    # TODO: create a password object so that in a stack trace or dump, the password isn't written
    # in the clear (or at all)
    def __init__( self, base_url: str, workspace: str, username: str, password: str ):
        self._workspace = workspace
        self._bitbucket = Cloud(base_url, username=username, password=password)

        # TODO: write a requests event listener that sends event messages to a specified logger
        self._logging = logging.getLogger('BITBUCKET_API')

    def get_current_user( self ) -> UserDataAccess:
        # TODO: use url builders
        response = self._bitbucket.get("/user")
        return UserDataAccess( response )

    def get_user( self, identifier: str ) -> UserDataAccess:
        response = self._bitbucket.get("/users/")
        assert isinstance(response, requests.Response)
        return UserDataAccess( response )

    def list_pipelines( self, repository: str ) -> List[PipelineDataAccess]:
        pipelines = self._bitbucket.repositories.get(self._workspace, repository) \
                         .pipelines.each(sort="-created_on")
        return [PipelineDataAccess(pipeline.data) for pipeline in pipelines]


class MongoDataAccess:
    _database = None

    def __init__( self, connection_string: str ):
        self._database = None
        try:
            client = MongoClient( connection_string )
            if client is not None:
                self._database = client["bitbucket"]
                self.server_status()
        except Exception as e:
            # TODO: does the database need to be explicitly closed?
            self._database = None

            # For testing: if a mongo instance isn't setup, at least press on
            logging.exception( e )

    def has_database(self) -> bool:
        return self._database is not None

    def server_status( self ) -> dict[str, Any]:
        assert self._database is not None
        with pymongo.timeout(10):
            return self._database.command("serverStatus")

    def set_key_value( self, key: str, value: str ) -> None:
        if self._database is not None:
            self._database["properties"].update_one( { "_id": key }, { "$set": { key: value } }, upsert=True )

    # TODO: this isn't rendering in mongo-express as key-value. It's being rendered as _id/currentUesr
    def set_current_user( self, user_data_access: UserDataAccess ) -> None:
        self.set_key_value( "currentUser", user_data_access.get_uuid() )
        self.set_user( user_data_access )

    def set_user( self, user_data_access: UserDataAccess ) -> None:
        if self._database is not None:
            self._database["users"].update_one( { "_id": user_data_access.get_uuid() },
                                                { "$set": user_data_access.json() }, upsert=True )

    def get_user( self, uuid: str ) -> UserDataAccess | None:
        if self._database is not None:
            user = self._database["users"].find( { "_id": uuid } )
            if user is None:
                return None
            return UserDataAccess( user[0] )

        else:
            return None

    def get_current_user( self ) -> UserDataAccess | None:
        if self._database is not None:
            current_user_uuid = self._database["properties"].find({"_id": "currentUser"})
            # TODO: current_user_id is None
            uuid = current_user_uuid[0]["currentUser"] # pylint: disable=unsubscriptable-object
            if uuid is None:
                return None
            return self.get_user( uuid )

        else:
            return None


# TODO: this is easy to unit test
class BuildFailureManager( object ):
    def __init__( self, ws, config ):
        self._ws = ws
        self._config = config
        self._failures = {}

    def get_failures( self ) -> dict[str, str]:
        return self._failures

    def set_failed_build( self, repository: str, pipeline_uuid: str ) -> None:
        had_failure = len( self._failures )

        self._failures[repository] = pipeline_uuid
        if not had_failure and "notification" in self._config:
            self._ws.enable( self._config["notification"] )
        logging.info( str( self._failures ) )

    def clear_failed_build( self, repository: str, pipeline_uuid: str ) -> None:
        # TODO: There's a readers/writers race condition here
        if repository in self._failures:
            del self._failures[repository]

        logging.info( str( self._config ) )
        if len( self._failures ) == 0 and "notification" in self._config:
            self._ws.disable( self._config["notification"] )

        logging.info( str( self._failures ) )


class PipelineWorkunit( Workunit ):
    # TODO: rename pipeline to repository!
    def __init__( self,
                  build_failure_manager: BuildFailureManager,
                  df,
                  period_seconds: int,
                  bitbucket,
                  workqueue,
                  mongo_data_access: MongoDataAccess,
                  repository: str ):
        super().__init__( df )

        self._build_failure_manager = build_failure_manager
        self._period_seconds = period_seconds
        self._bitbucket = bitbucket
        self._workqueue = workqueue
        self._mongo_data_access = mongo_data_access
        self._repository = repository


    @override
    def work( self ) -> None:
        try:
            pipelines = self._bitbucket.list_pipelines( self._repository )
            # TODO: Don't report any failed pipelines that occurred before the
            # system started (not necessarily just this container!)
            # TODO: more fine grained logging channels
            logging.info( "found %s %s pipeline(s)", str( len( pipelines ) ), self._repository )

            if len( pipelines ) > 0:
                # At present, we're only tracking the most recent pipeline
                if pipelines[0].get_failure():
                    self._build_failure_manager.set_failed_build( self._repository, pipelines[0].get_uuid() )
                else:
                    self._build_failure_manager.clear_failed_build( self._repository, pipelines[0].get_uuid() )

        except Exception as e:
            logging.exception( e )
            # TODO: prometheus workunit exception

        finally:
            try:
                future = datetime.datetime.now() + datetime.timedelta( seconds=self._period_seconds )
                self._workqueue.enqueue(
                    PipelineWorkunit(
                        self._build_failure_manager,
                        future,
                        self._period_seconds,
                        self._bitbucket,
                        self._workqueue,
                        self._mongo_data_access,
                        self._repository ) )
            except Exception as e:
                logging.exception( e )
                # TODO: prometheus workunit exception

class BitbucketSensor( Sensor ):
    def __init__(self, args: List[str]):
        super().__init__(args, "Bitbucket Listener", "/bitbucket")

        self._mongo_data_access = MongoDataAccess( self._parsed_args.mongo_url )
        self._build_failure_manager = None
        self._bitbucket = None


    @override
    def get_arg_parser(self) -> argparse.ArgumentParser:
        parser = super().get_arg_parser()
        parser.add_argument('--bitbucket-url',
                            help='The url of the led-controller',
                            default='https://api.bitbucket.org',
                            dest='bitbucket_url')
        parser.add_argument('--mongo-url',
                            help='the url to the mongo database',
                            default='mongodb://mongo/bitbucket',
                            dest='mongo_url')
        return parser

    @override
    def _get_httpd_handler( self ) -> Type[SimpleHTTPRequestHandler]:
        def get_build_failure_manager():
            return self._build_failure_manager
        http_path_prefix = self._http_path_prefix

        class HTTPRequestHandler( SimpleHTTPRequestHandler ):
            @override
            def do_GET( self ) -> None: # pylint: disable=invalid-name
                response = None
                status = 500
                headers = {}

                try:
                    if self.path.startswith( http_path_prefix ):
                        status = 200
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

                        failures = {}
                        manager = get_build_failure_manager()
                        if manager is not None:
                            failures = manager.get_failures()
                        for key, value in failures.items():
                            response += "<tr><td>" + key + "</td><td>" + value + "</td></tr>"

                        response += """
                                    </table>
                                </body>
                            </html>"""

                except Exception as e:
                    logging.exception( e )

                finally:
                    self.send_response( status )
                    for key, value in headers.items():
                        self.send_header( key, value )
                    self.end_headers()
                    if response is not None:
                        if isinstance( response, str ):
                            response = response.encode( "utf-8" )
                        self.wfile.write( response )
        return HTTPRequestHandler

    @override
    def main(self) -> int:
        result = super().main()
        if result != 0:
            return result

        self._build_failure_manager = BuildFailureManager( self._ws, self._config )
        self._bitbucket = BitbucketDataAccess(
            self._parsed_args.bitbucket_url,
            self._config["workspace"],
            self._config["user"],
            self._config["token"] )
        current_user = self._bitbucket.get_current_user()
        if current_user is None:
            logging.error( "Couldn't get the current user!" )
            return 1
        self._mongo_data_access.set_current_user( current_user )

        assert self._workqueue is not None
        for pipeline in self._config["pipelines"]:
            # TODO: make period configurable
            self._workqueue.enqueue(
                PipelineWorkunit(
                    self._build_failure_manager,
                    datetime.datetime.now(),
                    60,
                    self._bitbucket,
                    self._workqueue,
                    self._mongo_data_access,
                    pipeline ) )

        self._up.set(1)
        assert self._terminate_semaphore is not None
        self._terminate_semaphore.acquire()

        self._workqueue.stop()

        return 0


if __name__ == "__main__":
    sys.exit(BitbucketSensor( sys.argv ).main())
