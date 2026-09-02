"""Serves a static OpenMetrics payload with exemplars, mimicking an app's
/metrics endpoint. The OpenMetrics content type is what makes the collector's
prometheus receiver parse exemplars; plain Prometheus text has no exemplar
syntax."""

import pathlib
import http.server

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "metrics.openmetrics.txt"
CONTENT_TYPE = "application/openmetrics-text; version=1.0.0; charset=utf-8"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = FIXTURE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    http.server.HTTPServer(("0.0.0.0", 9464), Handler).serve_forever()
