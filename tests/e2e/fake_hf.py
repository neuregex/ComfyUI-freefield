"""A stand-in for huggingface.co/<repo>/resolve/main/<file>: every file is 3 MB of zeros; Range supported; /gated/ answers 401."""
import http.server
import sys

SIZE = 3 * 1024 * 1024


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if "/gated/" in self.path:
            self.send_response(401)
            self.end_headers()
            return
        start = 0
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0])
            if start >= SIZE:
                self.send_response(416)
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{SIZE - 1}/{SIZE}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(SIZE - start))
        self.end_headers()
        sent = start
        while sent < SIZE:
            n = min(1 << 16, SIZE - sent)
            self.wfile.write(b"\0" * n)
            sent += n

    def log_message(self, *a):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
