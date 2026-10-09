import json
import contextlib
import dataclasses
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.fake_network import (
    FakeNetwork,
    RecordedRequest,
    fake_environment,
    http_response,
)

_REASONS = {
    200: "OK",
    201: "Created",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


@frozen
class ScriptedResponse:
    """One answer a scripted vendor gives.

    `json` is the body for the common case. `body` sends raw bytes instead, for a payload that is not
    JSON or is deliberately malformed.
    """

    status: int = 200
    json: Any = None
    headers: Mapping[str, str] = dataclasses.field(default_factory=dict)
    body: bytes | None = None

    def to_bytes(self) -> bytes:
        if self.body is not None:
            payload = self.body
        elif self.json is None:
            payload = b""
        else:
            payload = json.dumps(self.json).encode()
        reason = _REASONS.get(self.status, "Unknown")
        status_line = f"{self.status} {reason}".encode()
        headers = [f"{name}: {value}".encode() for name, value in self.headers.items()]
        return http_response(status_line, payload, headers)


# A script answers each request in turn, or decides from the request itself.
Script = Sequence[ScriptedResponse] | Callable[[RecordedRequest], ScriptedResponse]


class UnexpectedRequest(AssertionError):
    """The source made a request the script does not answer.

    Raised rather than answered, because a source that keeps asking is the failure a pagination test
    looks for. An empty answer would hide it.
    """


class ScriptedResponder:
    """Answers each request from a script, and fails on a request the script does not cover."""

    def __init__(self, script: Script) -> None:
        self._script = script
        self._queue = None if callable(script) else list(script)

    def respond(self, request: RecordedRequest, network: FakeNetwork) -> bytes:
        if self._queue is None:
            assert callable(self._script)
            return self._script(request).to_bytes()
        if not self._queue:
            raise UnexpectedRequest(
                f"the script has no answer left for {request.method} {request.url}"
                f" (request {network.requests} of this run)"
            )
        return self._queue.pop(0).to_bytes()


def route(table: Mapping[str, Sequence[ScriptedResponse]]) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer each path from its own queue, for a source that interleaves endpoints or a token exchange.

    A key matches a request whose path equals it, or ends with it, so a caller can name `/surveys`
    without the API's version prefix.
    """
    queues = {path: list(responses) for path, responses in table.items()}

    def respond(request: RecordedRequest) -> ScriptedResponse:
        for path, queue in queues.items():
            if request.path == path or request.path.endswith(path):
                if not queue:
                    raise UnexpectedRequest(f"the script has no answer left for {request.method} {request.url}")
                return queue.pop(0)
        raise UnexpectedRequest(f"the script covers no path matching {request.method} {request.url}")

    return respond


@contextlib.contextmanager
def scripted_network(script: Script) -> Iterator[FakeNetwork]:
    """Answer every request in the block from `script`, and yield the network that records them.

    For code a source runs outside an extraction, such as a credential probe or a webhook call. An
    extraction goes through `SourceDriver`, which also stands in for the pipeline.
    """
    with fake_environment(ScriptedResponder(script)) as network:
        yield network
