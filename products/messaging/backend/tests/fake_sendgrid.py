"""A real HTTP server that answers the way SendGrid's v3 API docs describe, from invented data.

Tests start it on a local port. To drive the whole product by hand, run it from a shell and point
MESSAGING_SENDGRID_API_URL and MESSAGING_SENDGRID_EU_API_URL at it:

    python products/messaging/backend/tests/fake_sendgrid.py --port 8791 --eu-port 8792

`POST /__control` sets failures and rate limits, or replaces parts of the account, and `GET /__requests` returns what
it received. A contact export is pending the first time it's checked and ready after that, unless the control says so.

Contact exports, lists and field definitions answer as SendGrid's OpenAPI spec says
(https://github.com/twilio/sendgrid-oai/tree/main/spec/json). It doesn't say what an export's files look like, so
`export_shape` covers each way they could.
"""

import io
import re
import csv
import gzip
import json
import time
import argparse
import threading
from collections import defaultdict
from collections.abc import Callable
from copy import deepcopy
from functools import partial
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
    "user.username.read",
]
FULL_KEY = "SG.full-read-key"
EU_KEY = "SG.eu-subuser-key"
SECOND_ACCOUNT_KEY = "SG.second-account-key"
NARROW_KEY = "SG.suppressions-only-key"
NO_SCOPE_KEY = "SG.no-scopes-key"
EMPTY_ACCOUNT_KEY = "SG.empty-account-key"
# A full-access key on an account without Marketing Campaigns, where SendGrid grants no marketing scope.
EMAIL_API_ONLY_KEY = "SG.email-api-only-key"
_SCOPES_BY_KEY = {
    FULL_KEY: ALL_READ_SCOPES,
    EU_KEY: ALL_READ_SCOPES,
    SECOND_ACCOUNT_KEY: ALL_READ_SCOPES,
    EMPTY_ACCOUNT_KEY: ALL_READ_SCOPES,
    EMAIL_API_ONLY_KEY: [scope for scope in ALL_READ_SCOPES if not scope.startswith("marketing.")],
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
    (r"/v3/user/username", "user.username.read"),
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
            "contacts": [],
            "segments": [],
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
        # How "ready" exports fall short: "bytes" cuts the packed file off, "connection" ends an unpacked one early,
        # "rows" leaves out the last contact, "extra" adds one, and "empty" holds no contacts and counts none.
        self.export_damage: str | None = None
        # How "ready" exports look where SendGrid's docs don't say: "packed", "files", "header_in_each_file", "bom",
        # "header" ("upper", "lower", "spaced" or "field_ids"), "reversed", "all_columns", "count" ("stated", "null" or
        # "missing"), "ignores_filter", "ignores_segments", "short_segments" (how many contacts each leaves out) and
        # "damaged_segment" (an address each segment holds uncounted). "empty_list" ("unreadable") and "empty_segment"
        # are the answers for one without contacts. The latter is "no_files", "counted", "failure", "pending",
        # "refused", "empty_file", "unreadable", or else a file with a header.
        self.export_shape: dict[str, Any] = {}
        # How long `/__trickle` waits between bytes.
        self.trickle_seconds = 0.0
        # How many checks an export stays pending for, and the status that follows.
        self.export_pending_checks = 1
        self.export_status = "ready"
        self.exports: dict[str, dict[str, Any]] = {}
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
        if self.path == "/v3/marketing/contacts/exports":
            return self._start_export()
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
                state.export_damage, state.export_pending_checks, state.export_status = None, 1, "ready"
                state.export_shape = {}
            state.account.update(body.get("account", {}))
            state.second_account.update(body.get("second_account", {}))
            for name in ("export_damage", "export_pending_checks", "export_status", "export_shape"):
                if name in body:
                    setattr(state, name, body[name])
            for name in body.get("grow", []):
                state.account[name["list"]].extend(
                    {"created": 1700000000 + i, "email": f"grown{i}@example.com"} for i in range(name["count"])
                )
        self._send(200, {"ok": True})

    def _start_export(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        state = self.server.state
        authorization = self.headers.get("Authorization", "")
        with state.lock:
            state.requests.append(
                {
                    "region": self.server.region,
                    "path": self.path,
                    "query": {},
                    "body": body,
                    "accept": self.headers.get("Accept"),
                    "authorization": authorization,
                }
            )
            status = self._forced_status(self.path)
        key = authorization.removeprefix("Bearer ")
        if not status and (key not in _SCOPES_BY_KEY or (self.server.region == "eu") != (key == EU_KEY)):
            status = 401
        if not status and "marketing.read" not in _SCOPES_BY_KEY[key]:
            status = 403
        if status:
            return self._send(status, {"errors": [{"field": None, "message": "refused"}]})
        list_ids, segment_ids = set(body.get("list_ids") or []), set(body.get("segment_ids") or [])
        contacts = [
            contact
            for contact in state.account_for(key)["contacts"]
            if not (list_ids or segment_ids)
            or state.export_shape.get("ignores_filter")
            or list_ids & set(contact["list_ids"])
            or (segment_ids and state.export_shape.get("ignores_segments"))
            or segment_ids & set(contact.get("segment_ids", []))
        ]
        if segment_ids and not contacts and state.export_shape.get("empty_segment") == "refused":
            return self._send(400, {"errors": [{"field": "segment_ids", "message": "refused"}]})
        if segment_ids and (short := state.export_shape.get("short_segments")):
            contacts = contacts[:-short]
        with state.lock:
            export_id = f"export-{len(state.exports) + 1}"
            state.exports[export_id] = {"contacts": contacts, "checks": 0, "segment_ids": segment_ids}
        self._send(202, {"id": export_id, "_metadata": {"self": f"https://api.sendgrid.com{self.path}/{export_id}"}})

    def _export_status(self, export_id: str) -> tuple[int, Any, dict[str, str]]:
        state = self.server.state
        export = state.exports.get(export_id)
        if export is None:
            return 404, {"errors": [{"message": "not found"}]}, {}
        export["checks"] += 1
        status = "pending" if export["checks"] <= state.export_pending_checks else state.export_status
        dates = {"created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}
        body: dict[str, Any] = {"id": export_id, "status": status, "expires_at": "2026-01-04T00:00:00Z", **dates}
        if status == "failure":
            body["message"] = "export failed"
        empty_segment = state.export_shape.get("empty_segment", "no_files")
        is_empty_segment = export["segment_ids"] and not export["contacts"]
        if is_empty_segment and empty_segment == "failure" and status == "ready":
            body |= {"status": "failure", "message": "nothing to export"}
        elif is_empty_segment and empty_segment == "pending":
            body["status"] = "pending"
        elif is_empty_segment and empty_segment == "counted" and status == "ready":
            body |= {"urls": [], "contact_count": 0}
        elif is_empty_segment and empty_segment == "no_files" and status == "ready":
            body["urls"] = []
        elif status == "ready":
            count = 0 if state.export_damage == "empty" else len(export["contacts"])
            # SendGrid documents the count as optional.
            stated = "missing" if state.export_damage == "connection" else state.export_shape.get("count", "stated")
            if stated != "missing":
                body["contact_count"] = None if stated == "null" else count
            files = 0 if state.export_damage == "empty" else state.export_shape.get("files", 1)
            body["urls"] = [
                f"{self.server.url}/__exports/{export_id}.csv.gz?signature=secret&part={part}" for part in range(files)
            ]
        return 200, body, {}

    def _send_trickle(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "40")
        self.end_headers()
        for _ in range(40):
            try:
                self.wfile.write(b"x")
                self.wfile.flush()
            except OSError:
                return
            threading.Event().wait(self.server.state.trickle_seconds)

    def _send_export_file(self, export_id: str, query: dict[str, str]) -> None:
        state = self.server.state
        with state.lock:
            state.requests.append(
                {
                    "region": self.server.region,
                    "path": "/__exports",
                    "query": query,
                    "accept": None,
                    "authorization": self.headers.get("Authorization", ""),
                }
            )
            status = self._forced_status("/__exports")
        if status and status != 200:
            return self._send(status, {}, {"Location": "https://example.com/"} if status == 302 else None)
        shape = state.export_shape
        part, files = int(query.get("part", 0)), shape.get("files", 1)
        contacts = state.exports[export_id]["contacts"][part::files]
        if state.export_damage == "rows":
            contacts = contacts[:-1]
        if state.exports[export_id]["segment_ids"] and (late := shape.get("damaged_segment")):
            contacts = [*contacts, {"id": "late", "email": late, "list_ids": []}]
        if state.export_damage == "extra":
            contacts = [*contacts, {"id": "extra", "email": "extra@example.com", "list_ids": []}]
        columns = _export_columns(state.exports[export_id]["contacts"], shape)
        rows = io.StringIO()
        writer = csv.writer(rows)
        if not part or shape.get("header_in_each_file", True):
            writer.writerow([header for header, _ in columns])
        writer.writerows([[value(contact) for _, value in columns] for contact in contacts])
        text = ("\ufeff" if shape.get("bom") else "") + rows.getvalue()
        if shape.get("empty_list") == "unreadable" and not (
            state.exports[export_id]["contacts"] or state.exports[export_id]["segment_ids"]
        ):
            text = "No contacts\r\n"
        if (
            state.exports[export_id]["segment_ids"]
            and not contacts
            and shape.get("empty_segment")
            in (
                "empty_file",
                "unreadable",
            )
        ):
            text = "" if shape["empty_segment"] == "empty_file" else "No contacts\r\n"
        payload = gzip.compress(text.encode()) if shape.get("packed", True) else text.encode()
        stated_length = len(payload)
        if state.export_damage == "bytes":
            payload = payload[:-12]
            stated_length = len(payload)
        if state.export_damage == "connection":
            stated_length = len(text.encode())
            payload = text[: text.rindex("\r\n", 0, -2) + 2].encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/gzip")
        self.send_header("Content-Length", str(stated_length))
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        state = self.server.state
        if parsed.path == "/__requests":
            with state.lock:
                return self._send(200, state.requests)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        if parsed.path == "/__trickle":
            return self._send_trickle()
        if match := re.fullmatch(r"/__exports/([^/]+)\.csv\.gz", parsed.path):
            return self._send_export_file(match.group(1), query)
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
        if path == "/v3/marketing/field_definitions":
            names = enumerate(_custom_field_names(account["contacts"]), start=1)
            custom = [{"id": f"e{number}_T", "name": name, "field_type": "Text"} for number, name in names]
            return 200, {"custom_fields": custom, "reserved_fields": [], "_metadata": {}}, {}
        if match := re.fullmatch(r"/v3/marketing/contacts/exports/([^/]+)", path):
            return self._export_status(match.group(1))
        if path in ("/v3/marketing/segments", "/v3/marketing/segments/2.0"):
            is_v2 = path.endswith("2.0")
            found = [s for s in account["segments"] if (s.get("query_version") == "2") == is_v2]
            return 200, {"results": found, "_metadata": {}}, {}
        if path == "/v3/user/username":
            return 200, {"username": f"{key[3:]}-user", "user_id": sorted(_SCOPES_BY_KEY).index(key) + 1}, {}
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


def _custom_field_names(contacts: list[dict[str, Any]]) -> list[str]:
    return sorted({name for contact in contacts for name in contact.get("custom_fields", {})})


def _export_columns(
    contacts: list[dict[str, Any]], shape: dict[str, Any]
) -> list[tuple[str, Callable[[dict[str, Any]], str]]]:
    fields = ["email", "first_name", "last_name", "city", "contact_id", "created_at"]
    if shape.get("all_columns"):
        fields += ["alternate_emails", "phone_number", "external_id", "list_ids", "last_emailed", "email_domains"]
    headers = {"lower": str.lower, "spaced": lambda name: name.replace("_", " ").title()}
    in_case = headers.get(shape.get("header", "upper"), str.upper)
    custom = _custom_field_names(contacts)
    columns: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        (in_case(field), partial(_exported_value, field)) for field in fields
    ]
    for number, name in enumerate(custom, start=1):
        header = f"e{number}_T" if shape.get("header") == "field_ids" else name
        columns.append((header, partial(_custom_value, name)))
    return columns[::-1] if shape.get("reversed") else columns


def _custom_value(name: str, contact: dict[str, Any]) -> str:
    return contact.get("custom_fields", {}).get(name, "")


def _exported_value(field: str, contact: dict[str, Any]) -> str:
    own = {**contact, "contact_id": contact["id"], "created_at": "2026-01-01T00:00:00Z"}
    value = own.get(field, "")
    return json.dumps(value) if isinstance(value, list) else str(value)


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
