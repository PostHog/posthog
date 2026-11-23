from __future__ import annotations

import io
import os
import json
import shutil
import zipfile
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest
from unittest.mock import patch

from products.stacks.backend.engine.addresses import address
from products.stacks.backend.engine.local import main
from products.stacks.backend.engine.natural_keys import natural_imports
from products.stacks.backend.engine.runner import read_bindings, run_diff, run_push
from products.stacks.backend.engine.tests.test_translate_out import ENGINE_WORDS
from products.stacks.backend.engine.translate_in import translate_in
from products.stacks.backend.engine.types import Credentials, EngineError, EngineInput, StackDescription

CREDENTIALS: Credentials = {"host": "https://127.0.0.1:1", "project_id": 7, "api_key": "example-personal-key"}
EMPTY: StackDescription = {"version": 1, "resources": []}


def test_diff_requires_an_installed_mirror_or_explicit_downloads(tmp_path: Path) -> None:
    engine_input = EngineInput(config={}, description=EMPTY)
    diff, saved, _ = run_diff(tmp_path, engine_input, None, CREDENTIALS)
    assert diff["errors"][0]["code"] in {"mirror_missing", "runner_unavailable"}
    assert saved == b""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(shutil.which("tofu") is None, reason="The saved diff round trip needs the local stack binary.")
def test_push_uses_reviewed_values_and_rejects_other_targets_and_stale_diffs(tmp_path: Path) -> None:
    engine_input = EngineInput(
        config={
            "variable": {"stack_secrets": {"type": "map(string)", "sensitive": True}},
            "output": {"reviewed_value": {"value": '${var.stack_secrets["token"]}', "sensitive": True}},
        },
        description=EMPTY,
        options={"mirror": tmp_path},
        secret_names=frozenset({"token"}),
    )
    literal_secret = 'example-${literal}-%{text}-"quoted"'
    diff, saved, serial = run_diff(tmp_path, engine_input, None, {**CREDENTIALS, "secrets": {"token": literal_secret}})
    assert diff["errors"] == []
    assert serial == 0
    with zipfile.ZipFile(io.BytesIO(saved)) as archive:
        assert all(CREDENTIALS["api_key"].encode() not in archive.read(name) for name in archive.namelist())
    rejected, empty = run_push(tmp_path, engine_input, saved, None, {**CREDENTIALS, "project_id": 8})
    assert rejected["errors"][0]["code"] == "stack_moved"
    assert empty == b""

    changed = replace(
        engine_input,
        config={"output": {"reviewed_value": {"value": "edited after diff", "sensitive": True}}},
        secret_names=frozenset(),
    )
    pushed, snapshot = run_push(tmp_path, changed, saved, None, CREDENTIALS)
    assert pushed == {"errors": [], "bindings": []}
    assert json.loads(snapshot)["outputs"]["reviewed_value"]["value"] == literal_secret

    diff, next_saved, serial = run_diff(tmp_path, changed, snapshot, CREDENTIALS)
    assert diff["errors"] == []
    assert serial == json.loads(snapshot)["serial"]
    result, newer = run_push(tmp_path, changed, next_saved, snapshot, CREDENTIALS)
    assert result["errors"] == []
    stale, preserved = run_push(tmp_path, changed, next_saved, newer, CREDENTIALS)
    assert stale["errors"][0]["code"] == "stack_moved"
    assert preserved == newer
    assert list(tmp_path.iterdir()) == []


def test_bindings_exclude_layouts_and_deposed_entities() -> None:
    def managed(kind: str, entity_id: str | int, *, layout: bool = False) -> dict:
        resource_type, name = address(kind, "demo", layout=layout).split(".")
        return {
            "mode": "managed",
            "type": resource_type,
            "name": name,
            "instances": [{"attributes": {"id": entity_id}}, {"deposed": "abc", "attributes": {"id": 999}}],
        }

    snapshot = {
        "serial": 3,
        "resources": [
            managed("dashboard", 12),
            managed("dashboard", 12, layout=True),
            managed("destination", "example-id"),
        ],
    }
    assert read_bindings(json.dumps(snapshot).encode()) == [
        {"kind": "dashboard", "key": "demo", "entity_id": 12},
        {"kind": "destination", "key": "demo", "entity_id": "example-id"},
    ]


def test_natural_adoption_paginates_without_sending_credentials_to_other_hosts() -> None:
    description: StackDescription = {
        "version": 1,
        "resources": [{"kind": "flag", "key": "checkout", "body": {"key": "checkout", "name": "Checkout"}}],
    }
    engine_input = translate_in(description, [], {})
    with patch("http.client.HTTPSConnection", autospec=True) as connection:
        client = connection.return_value
        response = client.getresponse.return_value
        response.status = 200
        response.read.side_effect = [
            b'{"results":[{"id":2,"key":"new-checkout"}],"next":"?offset=1"}',
            b'{"results":[{"id":3,"key":"checkout"}],"next":null}',
        ]
        assert natural_imports(engine_input, set(), CREDENTIALS) == [{"to": address("flag", "checkout"), "id": "3"}]
        assert [call.args[1] for call in client.request.call_args_list] == [
            "/api/projects/7/feature_flags/",
            "/api/projects/7/feature_flags/?offset=1",
        ]
        response.read.side_effect = [b'{"results":[],"next":"https://127.0.0.2:1/api/projects/7/feature_flags/"}']
        with pytest.raises(EngineError, match="project URL"):
            natural_imports(engine_input, set(), CREDENTIALS)
        assert all(call.args[0] == "127.0.0.1" for call in connection.call_args_list)


@pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="This test uses an installed stack mirror and binary.",
)
def test_local_partial_push_preserves_the_successful_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    writes = []

    class API(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            writes.append((self.path, self.headers["Authorization"]))
            payload: dict[str, object]
            if body["name"] == "Unavailable":
                status = 400
                payload = {"detail": "Choose another name. Supplied key: " + CREDENTIALS["api_key"]}
            else:
                status = 201
                payload = {**body, "id": 17, "deleted": False, "pinned": False}
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

    description: StackDescription = {
        "version": 1,
        "resources": [
            {"kind": "dashboard", "key": "first", "body": {"name": "Example"}},
            {"kind": "dashboard", "key": "second", "body": {"name": "Unavailable"}},
        ],
    }
    definition, saved, snapshot = (tmp_path / name for name in ("description.json", "saved.diff", "snapshot"))
    definition.write_text(json.dumps(description))
    monkeypatch.setenv("POSTHOG_API_KEY", CREDENTIALS["api_key"])
    with HTTPServer(("127.0.0.1", 0), API) as server:
        args = [
            str(definition),
            "--host",
            f"http://127.0.0.1:{server.server_port}",
            "--project-id",
            "7",
            "--state",
            str(snapshot),
            "--saved-diff",
            str(saved),
        ]
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            assert main(["diff", *args]) == 2
            diff = json.loads(capsys.readouterr().out)
            assert diff["errors"] == []
            assert diff["summary"]["create"] == 2
            assert main(["push", *args]) == 1
            result = json.loads(capsys.readouterr().out)
        finally:
            server.shutdown()
            worker.join()
    assert result["errors"][0]["code"] == "body_invalid"
    assert result["errors"][0]["message"] == "Choose another name. Supplied key: [redacted]"
    assert (
        read_bindings(snapshot.read_bytes())
        == result["bindings"]
        == [{"kind": "dashboard", "key": "first", "entity_id": 17}]
    )
    assert set(writes) == {("/api/projects/7/dashboards/", "Bearer example-personal-key")}
    assert all(path.stat().st_mode & 0o077 == 0 for path in (saved, snapshot))
    monkeypatch.delenv("POSTHOG_API_KEY")
    assert main(["diff", *args]) == 1
    assert saved.read_bytes() == b""


def test_cli_hides_private_flags_and_never_echoes_unknown_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["diff", "--help"])
    assert "--snapshot" in (help_text := capsys.readouterr().out)
    assert "--timeout-seconds" in help_text and not ENGINE_WORDS.search(help_text)
    assert "--state" not in help_text
    with pytest.raises(SystemExit):
        main(["diff", "--provider-secret=value"])
    assert "provider-secret" not in capsys.readouterr().err
