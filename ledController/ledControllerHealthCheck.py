import json
import logging
import os
import rel
import sys
import threading
import websocket

logging.basicConfig( level=logging.DEBUG )

# TODO: we can probably replace this with
#   $ echo -n "{\"ping\":true}" | nc -w 1 127.0.0.1 9099
#
# Though the timeout is annoying

openSem = threading.Semaphore( 0 )
def on_open( ws ):
    logging.info( "on_open" )
    openSem.release( 1 )

pongSem = threading.Semaphore( 0 )
resultValue = 1
def on_message( ws, data ):
    global resultValue
    logging.info( "exiting resultvalue: " + str( resultValue ) )
    try:
        if data is None:
            logging.error("no data")
            return 1

        data = data.decode( "ascii" )
        data = json.loads( data )
        if "pong" not in data or data["pong"] != True:
            logging.error( "no pong" )
            return 1
        
        else:
            resultValue = 0
            logging.info( "have pong!" )

    finally:
        pongSem.release( 1 )

def on_close( ws, close_status_code, close_message ):
    logging.info("on_close: " + str( close_status_code ) + " " + str( close_message ) )

have_error = False
def on_error( ws, error ):
    global have_error
    have_error = True
    logging.error( error )
    openSem.release()
    pongSem.release()

host =      os.environ["WS_HOST"]      if "WS_HOST"      in os.environ else "ledController"

def main( argv ):
    if len( argv ) != 1:
        sys.stderr.write( "invalid use\n" )
        return 1

    port = 9099

    ws = websocket.WebSocketApp( "ws://" + host + ":9099",
                                 on_open=on_open,
                                 on_message=on_message,
                                 on_error=on_error,
                                 on_close=on_close )
    s = threading.Thread( target=ws.run_forever )
    s.start()

    openSem.acquire()

    # Sending the client name is probably enough to test the health, but sending a ping is
    # probably worth while since it exercises more code on ledController
    if not have_error:
        ws.send( json.dumps( { "name": "HealthCheckPing" } ).encode( "ascii" ) )
    if not have_error:
        ws.send( json.dumps( {"ping": True} ).encode( "ascii" ) )

    logging.info( "waiting for pong..." )
    pongSem.acquire()
    logging.info( "have pong sem" )

    # s.join() doens't always terminate in a timely manner
    logging.info( "exiting with " + str( resultValue ) )
    try:
        sys.exit( resultValue )

    finally:
        logging.info( "closing..." )
        if ws.sock is not None:
            ws.close()

        logging.info( "joining..." )
        s.join()

        logging.info( "done" )
        
    return 0

if __name__ == "__main__":
    sys.exit( main( sys.argv ) )

