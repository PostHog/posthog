"""Answers Mailchimp's documented Marketing API reads from invented data, as a real server or as a `requests.get`
stand-in.

Shapes come from Mailchimp's OpenAPI spec:
https://github.com/mailchimp/mailchimp-client-lib-codegen/blob/main/spec/marketing.json

Run it as a server for a local import: `python -m products.messaging.backend.tests.fake_mailchimp --port 8790`, then
set MESSAGING_MAILCHIMP_API_URL=http://127.0.0.1:8790.
"""

import re
import json
import argparse
import threading
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "mailchimp_account.json").read_text())

# Shaped unlike a real key, so secret scanners leave them alone, but still ending in a data center.
FULL_KEY = "fake-full-access-key-us21"
EMPTY_KEY = "fake-empty-account-key-us21"

_ROUTES = (
    ("root", r"/3\.0/"),
    ("ping", r"/3\.0/ping"),
    ("lists", r"/3\.0/lists"),
    ("list", r"/3\.0/lists/(?P<list>[^/]+)"),
    ("members", r"/3\.0/lists/(?P<list>[^/]+)/members"),
    ("segments", r"/3\.0/lists/(?P<list>[^/]+)/segments"),
    ("segment_members", r"/3\.0/lists/(?P<list>[^/]+)/segments/(?P<segment>[^/]+)/members"),
    ("abuse", r"/3\.0/lists/(?P<list>[^/]+)/abuse-reports"),
    ("categories", r"/3\.0/lists/(?P<list>[^/]+)/interest-categories"),
    ("interests", r"/3\.0/lists/(?P<list>[^/]+)/interest-categories/(?P<category>[^/]+)/interests"),
    ("templates", r"/3\.0/templates"),
    ("default_content", r"/3\.0/templates/(?P<template>[^/]+)/default-content"),
    ("campaigns", r"/3\.0/campaigns"),
    ("campaign_content", r"/3\.0/campaigns/(?P<campaign>[^/]+)/content"),
)


@dataclass(frozen=False)
class Failure:
    route: str
    status: int
    times: int = 1
    headers: dict[str, str] = field(default_factory=dict)
    # Fail only from this offset on, so earlier pages of the same list still answer.
    from_offset: int = 0
    # Fail only reads of contacts with this status.
    status_filter: str | None = None


class FakeMailchimp:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data if data is not None else json.loads(json.dumps(FIXTURES))
        self.keys = {FULL_KEY, EMPTY_KEY}
        self.calls: list[dict[str, Any]] = []
        self.failures: list[Failure] = []
        self._in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def handle(
        self, path: str, query: dict[str, str], authorization: str
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            return self._handle(path, query, authorization)
        finally:
            with self._lock:
                self._in_flight -= 1

    def _handle(
        self, path: str, query: dict[str, str], authorization: str
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        route, params = _match(path)
        self.calls.append({"route": route, "path": path, "query": query})
        key = authorization.removeprefix("Bearer ")
        if key not in self.keys:
            return 401, {"title": "API Key Invalid", "status": 401, "detail": "Your API key may be invalid."}, {}
        for failure in self.failures:
            if (
                failure.route == route
                and failure.times > 0
                and int(query.get("offset", 0)) >= failure.from_offset
                and failure.status_filter in (None, query.get("status"))
            ):
                failure.times -= 1
                return failure.status, {"title": "Fake failure", "status": failure.status}, failure.headers
        if route is None:
            return 404, {"title": "Resource Not Found", "status": 404}, {}
        lists = [] if key == EMPTY_KEY else self.data["lists"]
        by_id = {row["id"]: row for row in lists}
        if route == "root":
            return (
                200,
                dict(self.data.get("account", {"account_id": "acct1", "account_name": "Example Co", "role": "owner"})),
                {},
            )
        if route == "ping":
            return 200, {"health_status": "Everything's Chimpy!"}, {}
        if route == "lists":
            # A key of a user without access to an audience doesn't list it.
            rows = [{k: v for k, v in row.items() if k not in _NESTED} for row in lists if not row.get("hidden")]
            return 200, self._page("lists", rows, query), {}
        if route == "list":
            audience = by_id.get(params["list"])
            return (
                (200, {"id": audience["id"]}, {})
                if audience
                else (404, {"title": "Resource Not Found", "status": 404}, {})
            )
        if route in ("members", "abuse", "categories", "interests", "segments", "segment_members"):
            audience = by_id.get(params.get("list", ""))
            if audience is None:
                return 404, {"title": "Resource Not Found", "status": 404}, {}
            return self._audience_route(route, audience, params, query)
        templates = [] if key == EMPTY_KEY else self.data["templates"]
        if route == "templates":
            kind = query.get("type")
            rows = [
                {k: v for k, v in row.items() if k != "html"} for row in templates if not kind or row["type"] == kind
            ]
            return 200, self._page("templates", rows, query), {}
        if route == "default_content":
            template = next((row for row in templates if str(row["id"]) == params["template"]), None)
            if template is None:
                return 404, {"title": "Resource Not Found", "status": 404}, {}
            body: dict[str, Any] = {"sections": {"body": "Default content"}}
            if template.get("html"):
                body["html"] = template["html"]
            return 200, body, {}
        campaigns = [] if key == EMPTY_KEY else self.data["campaigns"]
        if route == "campaigns":
            rows = sorted(
                ({k: v for k, v in row.items() if k != "content"} for row in campaigns),
                key=lambda row: row["create_time"],
            )
            if status := query.get("status"):
                rows = [row for row in rows if row["status"] == status]
            if since := query.get("since_send_time"):
                rows = [
                    row
                    for row in rows
                    if row.get("send_time")
                    and datetime.fromisoformat(row["send_time"]) >= datetime.fromisoformat(since)
                ]
            return 200, self._page("campaigns", rows, query), {}
        campaign = next((row for row in campaigns if row["id"] == params["campaign"]), None)
        if campaign is None:
            return 404, {"title": "Resource Not Found", "status": 404}, {}
        return 200, dict(campaign["content"]), {}

    def _audience_route(
        self, route: str, audience: dict[str, Any], params: dict[str, str], query: dict[str, str]
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        if route == "members":
            status = query.get("status")
            rows = [row for row in audience["members"] if not status or row["status"] == status]
            page = self._page("members", rows, query)
            if fields := query.get("fields"):
                wanted = {name.removeprefix("members.") for name in fields.split(",")}
                page["members"] = [{k: v for k, v in row.items() if k in wanted} for row in page["members"]]
            return 200, page, {}
        if route == "segments":
            rows = [{k: v for k, v in row.items() if k != "emails"} for row in audience.get("segments", [])]
            return 200, self._page("segments", rows, query), {}
        if route == "segment_members":
            segment = next((row for row in audience.get("segments", []) if str(row["id"]) == params["segment"]), None)
            if segment is None:
                return 404, {"title": "Resource Not Found", "status": 404}, {}
            # Mailchimp leaves out everyone but subscribed members unless the request asks for them.
            rows = [
                row
                for row in audience["members"]
                if row["email_address"] in segment["emails"] and row["status"] == "subscribed"
            ]
            return 200, self._page("members", rows, query), {}
        if route == "abuse":
            return 200, self._page("abuse_reports", audience["abuse_reports"], query), {}
        if route == "categories":
            rows = [{k: v for k, v in row.items() if k != "interests"} for row in audience["interest_categories"]]
            return 200, self._page("categories", rows, query), {}
        if route == "interests":
            category = next((row for row in audience["interest_categories"] if row["id"] == params["category"]), None)
            if category is None:
                return 404, {"title": "Resource Not Found", "status": 404}, {}
            return 200, self._page("interests", category["interests"], query), {}
        return 404, {"title": "Resource Not Found", "status": 404}, {}

    @staticmethod
    def _page(items_key: str, rows: list[dict[str, Any]], query: dict[str, str]) -> dict[str, Any]:
        count = min(int(query.get("count", 10)), 1000)
        offset = int(query.get("offset", 0))
        return {items_key: rows[offset : offset + count], "total_items": len(rows)}


_NESTED = ("members", "interest_categories", "abuse_reports", "segments")


def _match(path: str) -> tuple[str | None, dict[str, str]]:
    for name, pattern in _ROUTES:
        match = re.fullmatch(pattern, path)
        if match:
            return name, {key: unquote(value) for key, value in match.groupdict().items()}
    return None, {}


def split_url(url: str) -> tuple[str, str, dict[str, str]]:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}", parts.path, dict(parse_qsl(parts.query))


class FakeMailchimpServer(ThreadingHTTPServer):
    def __init__(self, fake: FakeMailchimp, port: int) -> None:
        self.fake = fake
        super().__init__(("127.0.0.1", port), _Handler)


class _Handler(BaseHTTPRequestHandler):
    server: FakeMailchimpServer

    def do_GET(self) -> None:
        _, path, query = split_url(f"http://fake{self.path}")
        status, body, headers = self.server.fake.handle(path, query, self.headers.get("Authorization", ""))
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--fixture", type=Path, default=None)
    args = parser.parse_args()
    data = json.loads(args.fixture.read_text()) if args.fixture else None
    server = FakeMailchimpServer(FakeMailchimp(data), args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
