"""Synthetic Prometheus target farm for the sharding scale test.

Serves FARM_PORTS consecutive ports starting at FARM_BASE_PORT. Every port
answers /metrics with FARM_SERIES_PER_TARGET unique series, each labeled with
its target port so assertions can attribute every sample to a target.
"""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_PORT = int(os.environ.get("FARM_BASE_PORT", "9500"))
PORTS = int(os.environ.get("FARM_PORTS", "40"))
SERIES_PER_TARGET = int(os.environ.get("FARM_SERIES_PER_TARGET", "200"))


def render_metrics(port: int) -> bytes:
    lines = [
        "# HELP farm_series synthetic scale-test series",
        "# TYPE farm_series gauge",
    ]
    for i in range(SERIES_PER_TARGET):
        lines.append(f'farm_series{{target="{port}",series="{i}"}} {port}.{i}')
    lines.append("")
    return "\n".join(lines).encode()


class FarmServer(ThreadingHTTPServer):
    def __init__(self, port: int) -> None:
        super().__init__(("0.0.0.0", port), Handler)
        self.port = port


class Handler(BaseHTTPRequestHandler):
    server: FarmServer

    def do_GET(self) -> None:
        body = render_metrics(self.server.port)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def main() -> None:
    servers = []
    for port in range(BASE_PORT, BASE_PORT + PORTS):
        server = FarmServer(port)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
    print(  # noqa: T201 — container log line, the harness's readiness signal
        f"farm ready: {PORTS} targets on {BASE_PORT}-{BASE_PORT + PORTS - 1}, {SERIES_PER_TARGET} series each",
        flush=True,
    )
    threading.Event().wait()


if __name__ == "__main__":
    main()
