"""A real HTTP server that answers the way SendGrid's v3 API docs describe, from invented data.

Tests start it on a local port. To drive the whole product by hand, run it from a shell and point
MESSAGING_SENDGRID_API_URL and MESSAGING_SENDGRID_EU_API_URL at it:

    python products/messaging/backend/tests/fake_sendgrid.py --port 8791 --eu-port 8792

`POST /__control` sets failures and rate limits, and `GET /__requests` returns what it received.
"""

import re
import json
import time
import argparse
import threading
from collections import defaultdict
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ACCOUNT = json.loads((Path(__file__).parent / "fixtures" / "sendgrid_account.json").read_text())
ALL_READ_SCOPES = [
    "asm.groups.read",
    "suppression.read",
    "design_library.read",
    "suppression.bounces.read",
    "suppression.blocks.read",
    "suppression.invalid_emails.read",
    "suppression.spam_reports.read",
    "suppression.unsubscribes.read",
    "templates.read",
    "templates.versions.read",
    "marketing.read",
    "whitelabel.read",
]
FULL_KEY = "SG.full-read-key"
EU_KEY = "SG.eu-subuser-key"
SECOND_ACCOUNT_KEY = "SG.second-account-key"
NARROW_KEY = "SG.suppressions-only-key"
NO_SCOPE_KEY = "SG.no-scopes-key"
EMPTY_ACCOUNT_KEY = "SG.empty-account-key"
_SCOPES_BY_KEY = {
    FULL_KEY: ALL_READ_SCOPES,
    EU_KEY: ALL_READ_SCOPES,
    SECOND_ACCOUNT_KEY: ALL_READ_SCOPES,
    EMPTY_ACCOUNT_KEY: ALL_READ_SCOPES,
    NARROW_KEY: ["suppression.read"],
    NO_SCOPE_KEY: [],
}

# The scope each path needs, as the real API enforces it. It refuses the suppression lists to the per-list scopes.
_PATH_SCOPES = (
    (r"/v3/asm/groups", "asm.groups.read"),
    (r"/v3/asm/groups/\d+/suppressions", "suppression.read"),
    (r"/v3/suppression/.*", "suppression.read"),
    (r"/v3/designs(/[^/]+)?", "design_library.read"),
    (r"/v3/templates", "templates.read"),
    (r"/v3/templates/[^/]+/versions/[^/]+", "templates.versions.read"),
    (r"/v3/marketing/.*", "marketing.read"),
    (r"/v3/whitelabel/domains", "whitelabel.read"),
)
_SUPPRESSION_LISTS = {
    "/v3/suppression/bounces": "bounces",
    "/v3/suppression/blocks": "blocks",
    "/v3/suppression/invalid_emails": "invalid_emails",
    "/v3/suppression/spam_reports": "spam_reports",
    "/v3/suppression/unsubscribes": "unsubscribes",
}


class FakeSendGridState:
    def __init__(self) -> None:
        self.account: dict[str, Any] = deepcopy(ACCOUNT)
        self.second_account: dict[str, Any] = {
            **{key: [] for key in ("groups", "bounces", "invalid_emails", "spam_reports", "blocks", "unsubscribes")},
            **{key: [] for key in ("templates", "designs", "single_sends", "lists", "verified_senders", "domains")},
            "group_suppressions": {},
            "contact_count": {"contact_count": 0, "billable_count": 0},
        }
        self.empty_account: dict[str, Any] = deepcopy(self.second_account)
        self.requests: list[dict[str, Any]] = []
        # Path -> statuses to answer with before answering normally.
        self.failures: dict[str, list[int]] = defaultdict(list)
        # (path, how many requests to let through, status). Fails every request after those.
        self.fail_after: dict[str, tuple[int, int]] = {}
        # Path -> (requests allowed per window, seconds in a window).
        self.rate_limits: dict[str, tuple[int, int]] = {}
        self._windows: dict[str, tuple[float, int]] = {}
        self.next_url_host = "https://api.sendgrid.com"
        self.lock = threading.Lock()

    def account_for(self, key: str) -> dict[str, Any]:
        if key == SECOND_ACCOUNT_KEY:
            return self.second_account
        if key == EMPTY_ACCOUNT_KEY:
            return self.empty_account
        return self.account

    def take_window(self, path: str) -> tuple[int, int, int]:
        """The limit, what remains and when the window resets, after counting this request."""
        limit, seconds = self.rate_limits.get(path, (500, 60))
        now = time.time()
        started, used = self._windows.get(path, (now, 0))
        if now - started >= seconds:
            started, used = now, 0
        used += 1
        self._windows[path] = (started, used)
        return limit, limit - used, int(started + seconds) + 1


class _Handler(BaseHTTPRequestHandler):
    server: "FakeSendGridServer"

    def log_message(self, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        if self.path != "/__control":
            return self._send(404, {"errors": [{"message": "not found"}]})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        state = self.server.state
        with state.lock:
            for path, statuses in body.get("failures", {}).items():
                state.failures[path] = list(statuses)
            for path, spec in body.get("fail_after", {}).items():
                state.fail_after[path] = tuple(spec)
            for path, spec in body.get("rate_limits", {}).items():
                state.rate_limits[path] = tuple(spec)
            if body.get("clear"):
                state.failures.clear()
                state.fail_after.clear()
                state.rate_limits.clear()
                state.requests.clear()
            for name in body.get("grow", []):
                state.account[name["list"]].extend(
                    {"created": 1700000000 + i, "email": f"grown{i}@example.com"} for i in range(name["count"])
                )
        self._send(200, {"ok": True})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        state = self.server.state
        if parsed.path == "/__requests":
            with state.lock:
                return self._send(200, state.requests)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        authorization = self.headers.get("Authorization", "")
        with state.lock:
            state.requests.append(
                {
                    "region": self.server.region,
                    "path": parsed.path,
                    "query": query,
                    "accept": self.headers.get("Accept"),
                    "authorization": authorization,
                }
            )
            status = self._forced_status(parsed.path)
            limit, remaining, reset = state.take_window(parsed.path)
        headers = {"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": str(max(remaining, 0))}
        headers["X-RateLimit-Reset"] = str(reset)
        if remaining < 0:
            return self._send(429, {"errors": [{"field": None, "message": "too many requests"}]}, headers)
        if status:
            return self._send(status, {"errors": [{"field": None, "message": "injected"}]}, headers)
        if "application/json" not in (self.headers.get("Accept") or ""):
            return self._send(406, {"errors": [{"message": "Accept header required"}]}, headers)
        key = authorization.removeprefix("Bearer ")
        if key not in _SCOPES_BY_KEY or (self.server.region == "eu") != (key == EU_KEY):
            return self._send(401, {"errors": [{"field": None, "message": "authorization required"}]}, headers)
        scope = next((scope for pattern, scope in _PATH_SCOPES if re.fullmatch(pattern, parsed.path)), None)
        if scope and scope not in _SCOPES_BY_KEY[key]:
            return self._send(403, {"errors": [{"field": None, "message": "access forbidden"}]}, headers)
        status, body, extra = self._route(parsed.path, query, state.account_for(key), key)
        self._send(status, body, {**headers, **extra})

    def _forced_status(self, path: str) -> int | None:
        state = self.server.state
        if state.failures.get(path):
            return state.failures[path].pop(0)
        if path in state.fail_after:
            allowed, status = state.fail_after[path]
            if allowed <= 0:
                return status
            state.fail_after[path] = (allowed - 1, status)
        return None

    def _route(
        self, path: str, query: dict[str, str], account: dict[str, Any], key: str
    ) -> tuple[int, Any, dict[str, str]]:
        if path == "/v3/scopes":
            return 200, {"scopes": _SCOPES_BY_KEY[key]}, {}
        if path in _SUPPRESSION_LISTS:
            return self._offset_list(account[_SUPPRESSION_LISTS[path]], query, path, 500)
        if path == "/v3/asm/groups":
            return 200, account["groups"], {}
        if match := re.fullmatch(r"/v3/asm/groups/(\d+)/suppressions", path):
            return 200, account["group_suppressions"].get(match.group(1), []), {}
        if path == "/v3/templates":
            return self._templates(account, query)
        if match := re.fullmatch(r"/v3/templates/([^/]+)/versions/([^/]+)", path):
            return self._version(account, match.group(1), match.group(2))
        if path == "/v3/designs":
            return self._token_list(account["designs"], query, path, 100)
        if match := re.fullmatch(r"/v3/designs/([^/]+)", path):
            return self._one(account["designs"], match.group(1))
        if path == "/v3/marketing/singlesends":
            return self._token_list(account["single_sends"], query, path, 100)
        if match := re.fullmatch(r"/v3/marketing/singlesends/([^/]+)", path):
            return self._one(account["single_sends"], match.group(1))
        if path == "/v3/marketing/lists":
            return self._token_list(account["lists"], query, path, 1000)
        if path == "/v3/marketing/contacts/count":
            return 200, account["contact_count"], {}
        if path == "/v3/verified_senders":
            return self._senders(account, query)
        if path == "/v3/whitelabel/domains":
            return self._offset_list(account["domains"], query, path, 500)
        return 404, {"errors": [{"message": "not found"}]}, {}

    def _offset_list(
        self, rows: list[Any], query: dict[str, str], path: str, maximum: int
    ) -> tuple[int, Any, dict[str, str]]:
        limit = int(query.get("limit", 50))
        offset = int(query.get("offset", 0))
        if not 1 <= limit <= maximum or offset < 0:
            return 400, {"errors": [{"field": "limit", "message": f"limit must be between 1 and {maximum}"}]}, {}
        if "end_time" in query:
            rows = [row for row in rows if not isinstance(row, dict) or row.get("created", 0) <= int(query["end_time"])]
        page = rows[offset : offset + limit]
        links = []
        if offset + limit < len(rows):
            links.append(f'<https://api.sendgrid.com{path}?limit={limit}&offset={offset + limit}>; rel="next"')
        return 200, page, {"Link": ", ".join(links)} if links else {}

    def _token_list(
        self, rows: list[Any], query: dict[str, str], path: str, maximum: int
    ) -> tuple[int, Any, dict[str, str]]:
        size = int(query.get("page_size", 100))
        if not 1 <= size <= maximum:
            return 400, {"errors": [{"message": f"page_size must be between 1 and {maximum}", "error_id": "x"}]}, {}
        start = int(query.get("page_token", 0))
        page = rows[start : start + size]
        metadata: dict[str, Any] = {"self": f"https://api.sendgrid.com{path}", "count": len(rows)}
        if start + size < len(rows):
            host = self.server.state.next_url_host
            metadata["next"] = f"{host}{path}?page_size={size}&page_token={start + size}"
        return 200, {"result": page, "_metadata": metadata}, {}

    def _templates(self, account: dict[str, Any], query: dict[str, str]) -> tuple[int, Any, dict[str, str]]:
        if "page_size" not in query:
            return 400, {"errors": [{"message": "page_size is required", "error_id": "x"}]}, {}
        generations = query.get("generations", "legacy").split(",")
        rows = [
            {**row, "versions": [_without_content(version) for version in row["versions"]]}
            for row in account["templates"]
            if row["generation"] in generations
        ]
        return self._token_list(rows, query, "/v3/templates", 200)

    def _version(self, account: dict[str, Any], template_id: str, version_id: str) -> tuple[int, Any, dict[str, str]]:
        for template in account["templates"]:
            if template["id"] == template_id:
                for version in template["versions"]:
                    if version["id"] == version_id:
                        return 200, version, {}
        return 404, {"errors": [{"message": "not found"}]}, {}

    def _one(self, rows: list[dict[str, Any]], row_id: str) -> tuple[int, Any, dict[str, str]]:
        row = next((row for row in rows if row["id"] == row_id), None)
        return (200, row, {}) if row else (404, {"errors": [{"message": "not found"}]}, {})

    def _senders(self, account: dict[str, Any], query: dict[str, str]) -> tuple[int, Any, dict[str, str]]:
        rows = account["verified_senders"]
        if "id" in query:
            rows = [row for row in rows if row["id"] == int(query["id"])]
        if "lastSeenID" in query:
            rows = [row for row in rows if row["id"] > int(query["lastSeenID"])]
        return 200, {"results": rows[: int(query.get("limit", 100))]}, {}

    def _send(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)


def _without_content(version: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in version.items() if key not in ("html_content", "plain_content", "test_data")}


class FakeSendGridServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, state: FakeSendGridState, region: str, port: int = 0) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.state = state
        self.region = region

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def start(self) -> None:
        threading.Thread(target=self.serve_forever, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--eu-port", type=int, default=8792)
    args = parser.parse_args()
    state = FakeSendGridState()
    FakeSendGridServer(state, "eu", args.eu_port).start()
    FakeSendGridServer(state, "global", args.port).serve_forever()


if __name__ == "__main__":
    main()
