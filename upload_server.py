import http.server, cgi

files = [
    '/root/restaurant-ops/data/recipes/main_summary.csv',
    '/root/restaurant-ops/data/recipes/hale_summary.csv'
]
received = [0]

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={'REQUEST_METHOD':'POST'})
        file_item = form['file']
        path = files[received[0]]
        with open(path, 'wb') as f:
            f.write(file_item.file.read())
        received[0] += 1
        self.send_response(200)
        self.end_headers()
        self.wfile.write(f'Saved to {path}'.encode())
        print(f'Saved: {path}')

server = http.server.HTTPServer(('0.0.0.0', 8888), Handler)
server.allow_reuse_address = True
print('Ready on port 8888 - waiting for 2 files')
while received[0] < 2:
    server.handle_request()
print('All files received')
