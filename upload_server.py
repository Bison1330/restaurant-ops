import http.server, cgi, os

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={'REQUEST_METHOD':'POST'})
        file_item = form['file']
        with open('/root/restaurant-ops/data/recipes/hale_street_cantina_recipes.json', 'wb') as f:
            f.write(file_item.file.read())
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Upload complete')
        print('File saved!')

server = http.server.HTTPServer(('0.0.0.0', 8888), Handler)
print('Upload server running on port 8888...')
server.handle_request()
