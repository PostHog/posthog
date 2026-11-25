"""A local HTTP server that answers the way a real Customer.io workspace did on 2026-11-25, from invented people.

Tests start it in a thread. To drive the import by hand, run it on its own:

    python products/messaging/backend/tests/customerio_fake_server.py --port 18960 --people 60000
"""

import io
import re
import csv
import json
import base64
import hashlib
import argparse
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

KEY = "fake-customerio-key"
NO_EXPORT_KEY = "fake-customerio-key-without-exports"
SEGMENT_TIME = "1795627826"


@dataclass(frozen=False)
class Workspace:
    id: int = 1001
    people: list[dict[str, Any]] = field(default_factory=list)
    topics: list[dict[str, Any]] = field(default_factory=list)
    segments: list[dict[str, Any]] = field(default_factory=list)
    # The cio_ids in each segment, by segment ID.
    members: dict[str, set[str]] = field(default_factory=dict)
    suppressions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


class FakeCustomerIO:
    def __init__(self) -> None:
        self.workspace = Workspace()
        self.exports: list[dict[str, Any]] = []
        self.requests: list[tuple[str, str, str]] = []
        # Responses to send instead, by a pattern of the path. Each is used once.
        self.failures: list[tuple[str, int, dict[str, str]]] = []
        # How many status checks an export stays pending for.
        self.pending_checks = 0
        # Changes a file's bytes, or the headers that describe it, on its way out.
        self.cut_file_to: int | None = None
        self.stated_total: int | None = None
        self.state_length = True
        self.download_url: str | None = None
        self._server: ThreadingHTTPServer | None = None

    def __enter__(self) -> "FakeCustomerIO":
        self.serve(0)
        return self

    def __exit__(self, *_: object) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()

    def serve(self, port: int) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", port), _handler(self))
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def answer(self, method: str, target: str, key: str, body: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
        parts = urlsplit(target)
        path = parts.path.removeprefix("/v1")
        for index, (pattern, status, headers) in enumerate(self.failures):
            if re.fullmatch(pattern, f"{method} {path}"):
                del self.failures[index]
                return status, headers, b"{}"
        if path.startswith("/us/"):
            # Customer.io sends a key to its own region.
            return 301, {"Location": f"{self.url}{path.removeprefix('/us')}"}, b"{}"
        if match := re.fullmatch(r"/files/(\d+)/(\d+)\.csv", path):
            return self._file(int(match[2]))
        if key not in (KEY, NO_EXPORT_KEY):
            return _json({"meta": {"error": "unauthorized"}}, 401)
        if key == NO_EXPORT_KEY and path.startswith("/exports"):
            return _json({"errors": [{"detail": "forbidden", "status": "403"}]}, 403)
        query = {name: values[0] for name, values in parse_qs(parts.query).items()}
        match method, path.split("/")[1:]:
            case "GET", ["subscription_topics"]:
                return _json({"topics": self.workspace.topics})
            case "GET", ["workspaces"]:
                return _json({"workspaces": [{"id": self.workspace.id, "name": "Example"}, {"id": 1, "name": "Other"}]})
            case "GET", ["segments"]:
                return _json({"segments": self.workspace.segments})
            case "GET", ["esp", "suppression", kind]:
                entries = self.workspace.suppressions.get(kind, [])[int(query.get("offset", 0)) :]
                return _json({"suppressions": entries[: int(query["limit"])] or None})
            case "POST", ["customers"]:
                return self._search(body["filter"], int(query["limit"]), int(query.get("start") or 0))
            case "GET", ["exports"]:
                return _json({"exports": [_public(export) for export in self.exports] or None})
            case "POST", ["exports", "customers"]:
                return self._start_export(body["filters"])
            case "GET", ["exports", export_id, *rest] if int(export_id) <= len(self.exports):
                export = self.exports[int(export_id) - 1]
                if rest == ["download"]:
                    path = f"/files/{self.workspace.id}/{export_id}.csv"
                    return _json({"url": self.download_url or f"{self.url}{path}"})
                if export["checks_left"] > 0:
                    export["checks_left"] -= 1
                elif export["status"] == "pending":
                    export["status"] = "done"
                    export["total"] = len(export["rows"]) if self.stated_total is None else self.stated_total
                return _json({"export": _public(export)})
        return _json({"errors": [{"detail": "not found", "status": "404"}]}, 404)

    def _search(self, condition: dict[str, Any], limit: int, start: int) -> tuple[int, dict[str, str], bytes]:
        found = [person for person in self.workspace.people if self._matches(person, condition)]
        page = found[start : start + limit]
        return _json(
            {
                "identifiers": [
                    {
                        "cio_id": person["cio_id"],
                        "id": person.get("id"),
                        "email": person["email"].lower() if person.get("email") else None,
                    }
                    for person in page
                ],
                "next": str(start + limit) if start + limit < len(found) else "",
            }
        )

    def _matches(self, person: dict[str, Any], condition: dict[str, Any]) -> bool:
        if "or" in condition:
            return any(self._matches(person, part) for part in condition["or"])
        if "and" in condition:
            return all(self._matches(person, part) for part in condition["and"])
        if "segment" in condition:
            return person["cio_id"] in self.workspace.members.get(str(condition["segment"]["id"]), set())
        attribute = condition["attribute"]
        value = person.get(attribute["field"])
        if attribute["operator"] == "exists":
            return value is not None
        # Customer.io compares values as text, without case, and true doesn't equal 1.
        return value is not None and _text(value).lower() == _text(attribute["value"]).lower()

    def _start_export(self, filters: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
        segment_ids = [str(part["segment"]["id"]) for part in filters.get("or", []) if "segment" in part]
        if unknown := set(segment_ids) - {str(segment["id"]) for segment in self.workspace.segments}:
            return _json({"errors": [{"detail": f"not found {unknown}", "status": "404"}]}, 404)
        rows = []
        for person in self.workspace.people:
            if not self._matches(person, filters):
                continue
            row = {name: _text(value) for name, value in person.items() if value is not None}
            row |= {"_created_in_customerio_at": SEGMENT_TIME, "_cio_example": "x"}
            for segment_id in segment_ids:
                if person["cio_id"] in self.workspace.members.get(segment_id, set()):
                    row |= {f"_segment:{segment_id}": SEGMENT_TIME, f"_segment:{segment_id}_RFC3339": "2026-11-25"}
            rows.append(row)
        columns = {"id", "cio_id", *(f"_segment:{segment_id}" for segment_id in segment_ids)}
        export = {
            "id": len(self.exports) + 1,
            "status": "pending",
            "failed": False,
            "total": 0,
            "type": "customers",
            "rows": rows,
            "columns": ["id", *sorted(columns.union(*rows) - {"id"})],
            "checks_left": self.pending_checks,
        }
        self.exports.append(export)
        return _json({"export": _public(export)})

    def _file(self, export_id: int) -> tuple[int, dict[str, str], bytes]:
        export = self.exports[export_id - 1]
        text = io.StringIO()
        writer = csv.DictWriter(text, export["columns"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(export["rows"])
        content = text.getvalue().encode()
        digest = base64.b64encode(hashlib.md5(content, usedforsecurity=False).digest()).decode()
        headers = {"Content-Type": "text/csv"}
        if self.state_length:
            headers |= {"Content-Length": str(len(content)), "x-goog-hash": f"md5={digest}"}
        return 200, headers, content[: self.cut_file_to]


def person(number: int, email: str | None = "", **attributes: Any) -> dict[str, Any]:
    if email == "":
        email = f"person-{number}@example.com"
    return {"cio_id": f"c{number:07}", "id": f"user-{number}", "email": email, **attributes}


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))


def _public(export: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in export.items() if name not in ("rows", "columns", "checks_left")}


def _json(body: Any, status: int = 200) -> tuple[int, dict[str, str], bytes]:
    return status, {"Content-Type": "application/json"}, json.dumps(body).encode()


def _handler(fake: FakeCustomerIO) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            authorization = self.headers.get("Authorization", "")
            fake.requests.append((self.command, self.path, authorization))
            status, headers, content = fake.answer(self.command, self.path, authorization.removeprefix("Bearer "), body)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            if "Content-Length" not in headers and "text/csv" not in headers.values():
                self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        do_GET = do_POST = _answer

        def log_message(self, *_: Any) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18960)
    parser.add_argument("--people", type=int, default=100)
    options = parser.parse_args()
    fake = FakeCustomerIO()
    fake.workspace.people = [
        person(number, plan="pro", unsubscribed=number % 10 == 0) for number in range(options.people)
    ]
    fake.serve(options.port)
    threading.Event().wait()


if __name__ == "__main__":
    main()
