import logging
import http
from http import server

logging.basicConfig( level=logging.DEBUG )

class HTTPRequestHandler( http.server.BaseHTTPRequestHandler ):
    def do_POST( self ):
        try:
            logging.info("Have post!")
            content_len = int(self.headers.get('Content-Length'))
            logging.info( self.rfile.read( content_len ) )
        finally:
            self.send_response( 200 )
            self.end_headers()

def main():
    server = http.server.HTTPServer( ('', 3100), HTTPRequestHandler )
    server.serve_forever()

if __name__ == "__main__":
    main()

