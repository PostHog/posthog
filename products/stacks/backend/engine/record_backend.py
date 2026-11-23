from __future__ import annotations

import hmac
import base64
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, Thread

from .types import EngineError


class AbortRun(Exception):
    """The caller no longer owns the push."""


class RecordDelivery:
    def __init__(self, callback: Callable[[bytes], None] | None) -> None:
        self.callback = callback
        self.last_record: bytes | None = None
        self._error: BaseException | None = None
        self._abort: AbortRun | None = None
        self._stop: Callable[[], None] | None = None
        self._lock = Lock()

    @contextmanager
    def stop_on_abort(self, stop: Callable[[], None]) -> Iterator[None]:
        with self._lock:
            self._stop = stop
            if self._abort is not None:
                stop()
        try:
            yield
        finally:
            with self._lock:
                self._stop = None

    def publish(self, record: bytes) -> None:
        self.last_record = record
        if self.callback is None:
            return
        try:
            self.callback(record)
        except AbortRun as exc:
            # The backend thread must stop the process before acknowledging this write. Acknowledging first lets a dependent write start.
            with self._lock:
                if self._abort is None:
                    self._abort = exc
                if self._stop is not None:
                    self._stop()
        except BaseException as exc:
            if self._error is None:
                self._error = exc

    def raise_if_failed(self) -> None:
        if self._abort is not None:
            raise self._abort
        if self._error is not None:
            raise self._error


@contextmanager
def record_backend(
    path: Path, validate: Callable[[bytes], object], on_write: Callable[[bytes], None] | None
) -> Iterator[dict[str, str]]:
    """Acknowledge each complete backend write after the caller has received its bytes."""
    password = secrets.token_urlsafe(32)
    authorization = b"Basic " + base64.b64encode(f"stack:{password}".encode())

    class Handler(BaseHTTPRequestHandler):
        timeout = 5

        def log_message(self, format: str, *args: object) -> None:
            pass

        def reply(self, status: int, data: bytes = b"") -> None:
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)

        def authorized(self) -> bool:
            if self.path == "/record" and hmac.compare_digest(
                self.headers.get("Authorization", "").encode(), authorization
            ):
                return True
            self.reply(403)
            return False

        def do_GET(self) -> None:
            if self.authorized():
                try:
                    data = path.read_bytes()
                except FileNotFoundError:
                    data = b""
                except OSError:
                    self.reply(500)
                    return
                self.reply(200 if data else 404, data)

        def do_POST(self) -> None:
            if not self.authorized():
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0:
                    raise ValueError
                data = self.rfile.read(size)
                if len(data) != size:
                    raise ValueError
                validate(data)
            except (OSError, ValueError, RecursionError):
                self.reply(400)
                return
            try:
                with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                    stream.write(data)
                Path(stream.name).replace(path)
            except OSError:
                self.reply(500)
                return
            if on_write is not None:
                on_write(data)
            with suppress(BrokenPipeError, ConnectionResetError):
                self.reply(200)

    try:
        listener = HTTPServer(("127.0.0.1", 0), Handler)
    except OSError:
        raise EngineError(
            [{"code": "runner_unavailable", "message": "Check the stack worker installation and try again."}]
        ) from None
    with listener as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield {
                "TF_HTTP_ADDRESS": f"http://127.0.0.1:{server.server_port}/record",
                "TF_HTTP_USERNAME": "stack",
                "TF_HTTP_PASSWORD": password,
            }
        finally:
            server.shutdown()
            thread.join()
