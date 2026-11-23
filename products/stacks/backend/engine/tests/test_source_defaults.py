from __future__ import annotations

import os
import json
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest

from products.stacks.backend.engine import Credentials, StackDescription, run_diff, run_push, translate_in


@pytest.mark.parametrize("reject_connection", [False, True], ids=["discover-tables", "failed-connection-check"])
@pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="The source round trip needs the local binary and mirror.",
)
def test_source_creation_with_automatic_table_discovery(tmp_path: Path, reject_connection: bool) -> None:
    source_id = "4d732952-65a0-432b-ad2d-b58cde5bafdb"
    collection = "/api/projects/7/external_data_sources/"
    requests: list[str] = []
    requested_tables: list[object] = []

    class SourceAPI(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def reply(self, status: int, body: object) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_POST(self) -> None:
            requests.append(self.path)
            if self.path != collection:
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requested_tables.append(body["payload"]["schemas"])
            if reject_connection:
                self.reply(
                    400, {"detail": "The connection check rejected " + body["payload"]["stripe_secret_key"] + "."}
                )
            else:
                self.reply(201, {"id": source_id})

        def do_GET(self) -> None:
            requests.append(self.path)
            if self.path != f"{collection}{source_id}/":
                self.send_error(404)
                return
            self.reply(
                200,
                {
                    "id": source_id,
                    "source_type": "Stripe",
                    "job_inputs": {"stripe_account_id": "example-account"},
                    "schemas": [{"name": "charges", "should_sync": True}, {"name": "events", "should_sync": False}],
                },
            )

    description: StackDescription = {
        "version": 1,
        "resources": [
            {
                "kind": "source",
                "key": "revenue",
                "body": {
                    "source_type": "Stripe",
                    "payload": {"stripe_account_id": "example-account", "stripe_secret_key": {"$secret": "stripe"}},
                },
            }
        ],
    }
    engine_input = translate_in(description, [], {"mirror": os.environ["POSTHOG_STACK_MIRROR"]})
    with HTTPServer(("127.0.0.1", 0), SourceAPI) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            credentials: Credentials = {
                "host": f"http://127.0.0.1:{server.server_port}",
                "project_id": 7,
                "api_key": "example-key",
                "secrets": {"stripe": "example-secret"},
            }
            first, saved, _ = run_diff(tmp_path, engine_input, None, credentials)
            assert first["errors"] == []
            result, record = run_push(tmp_path, engine_input, saved, None, credentials)
            if reject_connection:
                assert result["errors"] == [
                    {
                        "code": "body_invalid",
                        "kind": "source",
                        "key": "revenue",
                        "message": "The connection check rejected [redacted].",
                    }
                ]
                return
            assert result["errors"] == []
            following, _, _ = run_diff(tmp_path, engine_input, record, credentials)
        finally:
            server.shutdown()
            thread.join()

    assert requests == [collection, f"{collection}{source_id}/"]
    assert requested_tables == [[]]
    assert following["errors"] == []
    assert following["changes"] == []
    assert following["drift"] == []
    assert first["changes"][0]["action"] == "create"
    assert {field["path"] for field in first["changes"][0]["fields"]} == {"source_type", "payload"}
