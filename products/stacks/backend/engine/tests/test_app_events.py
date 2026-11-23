import os
import json
import shutil
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from products.stacks.backend.engine import read_bindings, run_diff, run_push, translate_in
from products.stacks.backend.engine.types import Binding, Credentials, EngineOptions, StackDescription

Catalog = dict[str, dict[str, dict[str, Any]]]


@contextmanager
def _catalog() -> Iterator[tuple[Credentials, Catalog]]:
    records: Catalog = {
        collection: {} for collection in ("event_definitions", "schema_property_groups", "event_schemas")
    }
    project = "/api/projects/7/"

    class API(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def reply(self, status: int, data: object) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def route(self) -> tuple[str, str] | None:
            path = urlsplit(self.path).path
            if self.headers.get("Authorization") != "Bearer example-fake-key" or not path.startswith(project):
                self.reply(403, {})
                return None
            collection, _, detail = path.removeprefix(project).rstrip("/").partition("/")
            if collection not in records:
                self.reply(404, {})
                return None
            return collection, detail

        def do_GET(self) -> None:
            if not (route := self.route()):
                return
            collection, detail = route
            rows = records[collection]
            query = parse_qs(urlsplit(self.path).query)
            if collection == "event_definitions" and detail == "by_name":
                result = next((r for r in rows.values() if [r["name"]] == query.get("name")), None)
            elif detail:
                result = rows.get(detail)
            else:
                values = list(rows.values())
                if collection == "event_schemas" and "event_definition" in query:
                    values = [r for r in values if [r["event_definition"]] == query["event_definition"]]
                self.reply(200, {"results": values, "next": None})
                return
            self.reply(200 if result else 404, result or {})

        def do_POST(self) -> None:
            if not (route := self.route()):
                return
            collection, detail = route
            if detail:
                self.reply(404, {})
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if collection == "event_schemas":
                if (
                    body["event_definition"] not in records["event_definitions"]
                    or body["property_group_id"] not in records["schema_property_groups"]
                ):
                    self.reply(400, {"detail": "Unknown event or property group."})
                    return
                body = {
                    "event_definition": body["event_definition"],
                    "property_group": records["schema_property_groups"][body["property_group_id"]],
                }
            elif any(r["name"] == body["name"] for r in records[collection].values()):
                self.reply(409, {"detail": "Name already exists."})
                return
            elif collection == "event_definitions":
                if body.keys() != {"name"}:
                    self.reply(400, {"detail": "These definitions only specify the event name."})
                    return
                body = {
                    "tags": [],
                    "enforcement_mode": "allow",
                    "owner": None,
                    "verified": False,
                    "hidden": False,
                    **body,
                }
            else:
                body = {"description": "", "properties": [], **body}
            record = {"id": str(uuid4()), **body}
            records[collection][record["id"]] = record
            self.reply(201, record)

    with HTTPServer(("127.0.0.1", 0), API) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield (
                {"api_key": "example-fake-key", "host": f"http://127.0.0.1:{server.server_port}", "project_id": 7},
                records,
            )
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.skipif(
    not os.getenv("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"), reason="Needs the installed development build"
)
def test_app_events_push_creates_all_events_groups_and_memberships_then_converges(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[5]
    folder = json.loads((root / "posthog.json").read_bytes())["stacks"]["app-events"]["dir"]
    desc: StackDescription = json.loads((root / folder / "description.json").read_bytes())
    options: EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    with _catalog() as (credentials, catalog):
        incoming = translate_in(desc, [], options)
        planned, saved, serial = run_diff(tmp_path, incoming, None, credentials)
        assert not planned["errors"] and saved and serial == 0
        assert planned["summary"]["create"] == 83
        result, snapshot = run_push(tmp_path, incoming, saved, None, credentials)
        assert not result["errors"] and snapshot
        bindings = read_bindings(snapshot)
        assert Counter(row["kind"] for row in bindings) == {"event": 79, "property_group": 4}
        assert {(b["kind"], b["key"]) for b in bindings} == {(d["kind"], d["key"]) for d in desc["resources"]}
        assert len(catalog["event_definitions"]) == 79 and len(catalog["schema_property_groups"]) == 4
        # The four inline groups take the name of the event declaring them.
        expected = {(d["key"], d["key"]) for d in desc["resources"] if d["kind"] == "property_group"}
        actual = {
            (catalog["event_definitions"][link["event_definition"]]["name"], link["property_group"]["name"])
            for link in catalog["event_schemas"].values()
        }
        assert len(catalog["event_schemas"]) == 4 and actual == expected
        following = translate_in(desc, [Binding(**row) for row in bindings], options)
        after, _, _ = run_diff(tmp_path, following, snapshot, credentials)
        assert not after["errors"] and not after["changes"] and not after["drift"]
