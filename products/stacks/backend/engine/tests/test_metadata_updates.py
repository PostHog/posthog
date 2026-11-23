from __future__ import annotations

import os
import json
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import urlsplit

import pytest

from products.stacks.backend.engine import (
    Credentials,
    EngineOptions,
    StackDescription,
    run_diff,
    run_push,
    translate_in,
)
from products.stacks.backend.engine.types import Json


@pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="The metadata round trip needs the local binary and mirror.",
)
@pytest.mark.parametrize(
    ("kind", "entity_id", "definition", "initial", "lifecycle_edit", "code_edit"),
    [
        (
            "experiment",
            23,
            {"feature_flag_key": "checkout"},
            {"status": "draft"},
            {"status": "stopped", "conclusion": "inconclusive", "conclusion_comment": "Pending review"},
            {"conclusion_comment": "Reviewed in code"},
        ),
        (
            "survey",
            "60dca34f-60de-460c-b952-19dcfe155af5",
            {"type": "popover", "questions": [{"type": "open", "question": "How was checkout?"}]},
            {"archived": False},
            {
                "archived": True,
                "start_date": "2026-01-02T09:00:00Z",
                "end_date": "2026-01-10T09:00:00Z",
                "response_sampling_start_date": "2026-01-03T09:00:00Z",
            },
            {"response_sampling_start_date": "2026-01-04T09:00:00Z"},
        ),
    ],
)
def test_description_update_preserves_intervening_lifecycle_edit(
    tmp_path: Path,
    kind: str,
    entity_id: str | int,
    definition: dict[str, Json],
    initial: dict[str, Any],
    lifecycle_edit: dict[str, Any],
    code_edit: dict[str, Any],
) -> None:
    collection = f"/api/projects/7/{kind}s/"
    detail = f"{collection}{entity_id}/"
    remote: dict[str, Any] = {}
    creation: dict[str, Any] = {}
    edits: list[tuple[str, dict[str, Any]]] = []

    class API(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def reply(self, status: int, body: object) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == collection:
                self.reply(200, {"results": [remote] if remote else [], "next": None})
            elif path == detail and remote:
                self.reply(200, remote)
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if self.path != collection or remote:
                self.send_error(409)
                return
            creation.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            remote.update({"id": entity_id, **creation, **initial})
            self.reply(201, remote)

        def do_PATCH(self) -> None:
            if self.path != detail or not remote:
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            edits.append((self.command, body))
            remote.update(body)
            self.reply(200, remote)

        do_PUT = do_PATCH

    options: EngineOptions = {"mirror": os.environ["POSTHOG_STACK_MIRROR"]}
    description: StackDescription = {
        "version": 1,
        "resources": [
            {"kind": kind, "key": "checkout", "body": {"name": "Checkout", "description": "First", **definition}}
        ],
    }
    current = translate_in(description, [], options)
    with HTTPServer(("127.0.0.1", 0), API) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            credentials: Credentials = {
                "host": f"http://127.0.0.1:{server.server_port}",
                "project_id": 7,
                "api_key": "example-key",
            }
            first, saved, _ = run_diff(tmp_path, current, None, credentials)
            assert first["errors"] == [] and first["summary"]["create"] == 1
            created, record = run_push(tmp_path, current, saved, None, credentials)
            assert created["errors"] == []
            assert lifecycle_edit.keys().isdisjoint(creation)
            description["resources"][0]["body"]["description"] = "Reviewed"
            changed = translate_in(description, [{"kind": kind, "key": "checkout", "entity_id": entity_id}], options)
            reviewed, saved, _ = run_diff(tmp_path, changed, record, credentials)
            assert reviewed["errors"] == [] and reviewed["summary"]["update"] == 1
            assert [field["path"] for field in reviewed["changes"][0]["fields"]] == ["description"]
            remote.update(lifecycle_edit)
            pushed, record = run_push(tmp_path, changed, saved, record, credentials)
            assert pushed["errors"] == []
            assert edits == [("PATCH", {"description": "Reviewed"})]
            assert {field: remote[field] for field in lifecycle_edit} == lifecycle_edit
            subsequent, _, _ = run_diff(tmp_path, changed, record, credentials)
            assert not subsequent["changes"] and not subsequent["drift"] and not subsequent["errors"]

            description["resources"][0]["body"].update(code_edit)
            configured = translate_in(description, [{"kind": kind, "key": "checkout", "entity_id": entity_id}], options)
            reviewed, saved, _ = run_diff(tmp_path, configured, record, credentials)
            assert not reviewed["errors"]
            assert {row["path"]: row["after"] for row in reviewed["changes"][0]["fields"]} == code_edit
            pushed, record = run_push(tmp_path, configured, saved, record, credentials)
            assert pushed["errors"] == []
            subsequent, _, _ = run_diff(tmp_path, configured, record, credentials)
            assert not subsequent["changes"] and not subsequent["drift"] and not subsequent["errors"]
        finally:
            server.shutdown()
            thread.join()
    assert edits == [("PATCH", {"description": "Reviewed"}), ("PATCH", code_edit)]
    assert remote["description"] == "Reviewed"
    assert {field: remote[field] for field in lifecycle_edit} == {**lifecycle_edit, **code_edit}
