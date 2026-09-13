from __future__ import annotations

import select
import socket
import threading
from collections.abc import Callable
from socketserver import BaseRequestHandler, ThreadingTCPServer


def forward_local_port(port: int, target: tuple[str, int]) -> Callable[[], None]:
    stopped = threading.Event()

    class Forwarder(BaseRequestHandler):
        def handle(self) -> None:
            try:
                with socket.create_connection(target, timeout=5) as upstream:
                    upstream.settimeout(None)
                    peers = {self.request: upstream, upstream: self.request}
                    while not stopped.is_set():
                        ready, _, _ = select.select(list(peers), [], [], 1)
                        for source in ready:
                            data = source.recv(65536)
                            if not data:
                                return
                            peers[source].sendall(data)
            except OSError:
                return

    server = ThreadingTCPServer(("127.0.0.1", port), Forwarder, bind_and_activate=False)
    server.allow_reuse_address = True
    server.daemon_threads = True
    server.server_bind()
    server.server_activate()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def stop() -> None:
        stopped.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    return stop
