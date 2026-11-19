"""A local HTTP server that answers the way Postmark's API docs describe, from invented data.

Written from https://postmarkapp.com/developer/api/overview and the reference pages for servers, message streams,
suppressions, templates, domains, sender signatures and webhooks. Nothing here has been compared with a real account.

Tests start it in a thread. To drive the import by hand, run it on its own and point `MESSAGING_POSTMARK_API_URL` at it:

    python products/messaging/backend/tests/postmark_fake_server.py --port 18950 --suppressions 5000 --templates 90

`POST /__control/fail` queues failures, `GET /__control/requests` lists what arrived, and `POST /__control/reset` clears
both. They exist only here.
"""

import re
import copy
import json
import time
import argparse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

FIXTURE = Path(__file__).parent / "fixtures" / "postmark_account.json"
MAX_COUNT = 500
SERVER_HEADER = "X-Postmark-Server-Token"
ACCOUNT_HEADER = "X-Postmark-Account-Token"
_ERROR_NOT_AUTHORIZED = 10
_ERROR_BAD_PAGING = 1100
_ERROR_TEMPLATE_NOT_FOUND = 1101
_ERROR_STREAM_NOT_FOUND = 1226


class FakePostmark:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data if data is not None else json.loads(FIXTURE.read_text())
        self.requests: list[dict[str, Any]] = []
        # Each entry answers matching requests, for `times` requests, before the normal response.
        self.failures: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def fail(
        self,
        path_pattern: str,
        status: int,
        times: int = 1,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        skip: int = 0,
    ) -> None:
        with self._lock:
            self.failures.append(
                {
                    "pattern": path_pattern,
                    "status": status,
                    "times": times,
                    "skip": skip,
                    "body": body if body is not None else {"ErrorCode": 0, "Message": f"Invented failure {status}"},
                    "headers": headers or {},
                }
            )

    def reset(self) -> None:
        with self._lock:
            self.failures = []
            self.requests = []

    def _take_failure(self, path: str) -> dict[str, Any] | None:
        with self._lock:
            for failure in self.failures:
                if failure["times"] > 0 and re.fullmatch(failure["pattern"], path):
                    if failure["skip"] > 0:
                        failure["skip"] -= 1
                        return None
                    failure["times"] -= 1
                    return failure
        return None

    def answer(self, method: str, target: str, headers: Any) -> tuple[int, dict[str, Any], dict[str, str]]:
        parsed = urlparse(target)
        path = parsed.path
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        with self._lock:
            self.requests.append(
                {
                    "at": time.monotonic(),
                    "method": method,
                    "path": path,
                    "query": query,
                    "accept": headers.get("Accept"),
                    "server_token": headers.get(SERVER_HEADER),
                    "account_token": headers.get(ACCOUNT_HEADER),
                }
            )
        if method != "GET":
            return 405, {"ErrorCode": 0, "Message": "The import must only read."}, {}
        if headers.get("Accept") != "application/json":
            return 415, {"ErrorCode": 0, "Message": "The Accept header is required."}, {}
        if failure := self._take_failure(path):
            return failure["status"], failure["body"], failure["headers"]
        if path in ("/servers", "/domains", "/senders") or re.fullmatch(r"/domains/\d+", path):
            return self._account_route(path, query, headers.get(ACCOUNT_HEADER))
        return self._server_route(path, query, headers.get(SERVER_HEADER))

    def _account_route(
        self, path: str, query: dict[str, str], token: str | None
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        if token != self.data["account_token"]:
            return _unauthorized()
        if match := re.fullmatch(r"/domains/(\d+)", path):
            for domain in self.data["domains"]:
                if domain["ID"] == int(match.group(1)):
                    return 200, domain, {}
            return 404, {"ErrorCode": 0, "Message": "Domain not found"}, {}
        if path == "/servers":
            rows = [_public_server(server) for server in self.data["servers"]]
            return _paged(rows, "Servers", query, "count", "offset")
        if path == "/domains":
            rows = [_domain_summary(domain) for domain in self.data["domains"]]
            return _paged(rows, "Domains", query, "count", "offset")
        return _paged(self.data["senders"], "SenderSignatures", query, "count", "offset")

    def _server_route(
        self, path: str, query: dict[str, str], token: str | None
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        server = next((row for row in self.data["servers"] if token in row["ApiTokens"]), None)
        if server is None:
            return _unauthorized()
        if path == "/server":
            return 200, _public_server(server), {}
        if path == "/message-streams":
            return 200, _streams_response(server, query), {}
        if match := re.fullmatch(r"/message-streams/([^/]+)/suppressions/dump", path):
            if not any(stream["ID"] == match.group(1) for stream in server["streams"]):
                return 422, {"ErrorCode": _ERROR_STREAM_NOT_FOUND, "Message": "Stream not found"}, {}
            return 200, {"Suppressions": server["suppressions"].get(match.group(1), [])}, {}
        if path == "/webhooks":
            return 200, {"Webhooks": server["webhooks"]}, {}
        if path == "/templates":
            rows = [_template_summary(row) for row in server["templates"]]
            return _paged(rows, "Templates", query, "Count", "Offset")
        if match := re.fullmatch(r"/templates/([^/]+)", path):
            for template in server["templates"]:
                if match.group(1) in (str(template["TemplateId"]), template["Alias"]):
                    return 200, template, {}
            return 422, {"ErrorCode": _ERROR_TEMPLATE_NOT_FOUND, "Message": "Template not found"}, {}
        return 404, {"ErrorCode": 0, "Message": "Not found"}, {}


def _unauthorized() -> tuple[int, dict[str, Any], dict[str, str]]:
    return 401, {"ErrorCode": _ERROR_NOT_AUTHORIZED, "Message": "Bad or missing API token"}, {}


def _paged(
    rows: list[dict[str, Any]], key: str, query: dict[str, str], count_param: str, offset_param: str
) -> tuple[int, dict[str, Any], dict[str, str]]:
    try:
        count, offset = int(query[count_param]), int(query[offset_param])
    except (KeyError, ValueError):
        return 422, {"ErrorCode": _ERROR_BAD_PAGING, "Message": f"{count_param} and {offset_param} are required"}, {}
    if count > MAX_COUNT or count < 1 or offset < 0:
        return 422, {"ErrorCode": _ERROR_BAD_PAGING, "Message": f"{count_param} must be 1 to {MAX_COUNT}"}, {}
    return 200, {"TotalCount": len(rows), key: rows[offset : offset + count]}, {}


def _public_server(server: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in server.items() if key not in ("streams", "suppressions", "templates", "webhooks")
    }


def _domain_summary(domain: dict[str, Any]) -> dict[str, Any]:
    fields = ("Name", "ID", "SPFVerified", "DKIMVerified", "WeakDKIM", "ReturnPathDomainVerified")
    return {key: domain[key] for key in fields}


def _template_summary(template: dict[str, Any]) -> dict[str, Any]:
    fields = ("Active", "TemplateId", "Name", "Alias", "TemplateType", "LayoutTemplate")
    return {key: template[key] for key in fields}


def _streams_response(server: dict[str, Any], query: dict[str, str]) -> dict[str, Any]:
    include_archived = query.get("IncludeArchivedStreams", "false").lower() == "true"
    stream_type = query.get("MessageStreamType", "All")
    rows = [
        {
            **stream,
            "ServerID": server["ID"],
            "CreatedAt": "2026-01-01T00:00:00-05:00",
            "UpdatedAt": None,
            "ExpectedPurgeDate": None,
            "SubscriptionManagementConfiguration": {
                "UnsubscribeHandlingType": "Postmark" if stream["MessageStreamType"] == "Broadcasts" else "None"
            },
        }
        for stream in server["streams"]
        if (include_archived or not stream["ArchivedAt"]) and stream_type in ("All", stream["MessageStreamType"])
    ]
    return {"MessageStreams": rows, "TotalCount": len(rows)}


def with_scale(data: dict[str, Any], suppressions: int, templates: int) -> dict[str, Any]:
    scaled = copy.deepcopy(data)
    server = scaled["servers"][0]
    server["suppressions"]["broadcast"] += [
        {
            "EmailAddress": f"bulk-{index:07d}@example.com",
            "SuppressionReason": ("HardBounce", "SpamComplaint", "ManualSuppression")[index % 3],
            "Origin": "Customer",
            "CreatedAt": "2026-06-01T08:58:33-05:00",
        }
        for index in range(suppressions)
    ]
    server["templates"] += [
        {
            "TemplateId": 10000 + index,
            "Name": f"Bulk template {index}",
            "Alias": f"bulk-{index}",
            "TemplateType": "Standard",
            "LayoutTemplate": "base-layout",
            "Active": True,
            "AssociatedServerId": server["ID"],
            "Subject": "Bulk {{ name }}",
            "HtmlBody": "<p>{{ name }}</p>",
            "TextBody": None,
        }
        for index in range(templates)
    ]
    return scaled


def start_server(fake: FakePostmark, port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            if status >= 400 and isinstance(body, dict) and "ErrorCode" in body:
                self.send_header("X-PM-ApiErrorCode", str(body["ErrorCode"]))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(encoded)

        def _control(self) -> bool:
            path = urlparse(self.path).path
            if not path.startswith("/__control/"):
                return False
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length)) if length else {}
            if path == "/__control/fail":
                fake.fail(**payload)
            elif path == "/__control/reset":
                fake.reset()
            elif path == "/__control/data":
                fake.data = payload
            self._send(200, fake.requests if path == "/__control/requests" else {"ok": True})
            return True

        def _handle(self, method: str) -> None:
            if not self._control():
                self._send(*fake.answer(method, self.path, self.headers))

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def do_PUT(self) -> None:
            self._handle("PUT")

        def do_DELETE(self) -> None:
            self._handle("DELETE")

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18950)
    parser.add_argument("--suppressions", type=int, default=0)
    parser.add_argument("--templates", type=int, default=0)
    args = parser.parse_args()
    fake_postmark = FakePostmark(with_scale(json.loads(FIXTURE.read_text()), args.suppressions, args.templates))
    start_server(fake_postmark, args.port)
    threading.Event().wait()
