import io
import os
import sys
import json
import base64
import shutil
import socket
import hashlib
import zipfile
import subprocess
from asyncio import CancelledError
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import replace
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.parse import urlsplit

import pytest

from products.stacks.backend.engine import AbortRun, read_bindings, run_diff, run_push, translate_in
from products.stacks.backend.engine.record_backend import RecordDelivery, record_backend
from products.stacks.backend.engine.tests.test_binding_lifecycle import _project
from products.stacks.backend.engine.types import Credentials, EngineInput, StackDescription


@pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="The real push needs a local mirror and binary.",
)
@pytest.mark.parametrize("failure", [None, AbortRun("lease taken over"), RuntimeError("storage unavailable")])
def test_push_reports_a_checkpoint_before_the_last_create_finishes(tmp_path: Path, failure: Exception | None) -> None:
    records: list[bytes] = []
    intermediate = Event()
    writes: list[str] = []

    def receive(record: bytes) -> None:
        records.append(record)
        if len(read_bindings(record)) == 2:
            intermediate.set()
            if failure is not None:
                raise failure

    class API(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            writes.append(body["name"])
            if len(writes) == 2:
                # OpenTofu 1.12 enforces a minimum 20-second interval between intermediate writes.
                intermediate.wait(21)
            if len(writes) == 3 and not intermediate.wait(5):
                self.send_error(409)
                return
            data = json.dumps({**body, "id": len(writes), "deleted": False, "pinned": False}).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

    description: StackDescription = {
        "version": 1,
        "resources": [{"kind": "dashboard", "key": name, "body": {"name": name}} for name in ("one", "two", "three")],
    }
    engine_input = translate_in(description, [], {"mirror": os.environ["POSTHOG_STACK_MIRROR"], "refresh": False})
    with HTTPServer(("127.0.0.1", 0), API) as server:
        credentials: Credentials = {
            "api_key": "example-key",
            "host": f"http://127.0.0.1:{server.server_port}",
            "project_id": 1,
        }
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            diff, saved, _ = run_diff(tmp_path, engine_input, None, credentials)
            assert diff["errors"] == []
            if failure is not None:
                with pytest.raises(type(failure)) as raised:
                    run_push(tmp_path, engine_input, saved, None, credentials, on_record=receive)
                assert raised.value is failure
            else:
                pushed, latest = run_push(tmp_path, engine_input, saved, None, credentials, on_record=receive)
                assert pushed["errors"] == []
                assert records[-1] == latest
            if isinstance(failure, AbortRun):
                assert len(writes) == 2
                assert [len(read_bindings(record)) for record in records] == [2, 2]
                assert [b["key"] for b in read_bindings(records[-1])] == sorted(writes)
            else:
                assert sorted(writes) == ["one", "three", "two"]
                assert [len(read_bindings(record)) for record in records] == [2, 3, 3]
            assert records[-2] == records[-1]
        finally:
            server.shutdown()
            thread.join()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(not shutil.which("tofu"), reason="The callback needs the local binary.")
def test_callback_error_surfaces_after_the_final_record_even_if_the_callback_recovers(tmp_path: Path) -> None:
    engine_input = EngineInput(
        description={"version": 1, "resources": []},
        config={"output": {"example": {"value": "sample"}}},
        options={"mirror": tmp_path},
    )
    credentials: Credentials = {"api_key": "example-key", "host": "https://127.0.0.1:1", "project_id": 1}
    diff, first_diff, _ = run_diff(tmp_path, engine_input, None, credentials)
    assert diff["errors"] == []
    attempts: list[bytes] = []
    failure = RuntimeError("example private diagnostic")

    def fail_once(record: bytes) -> None:
        attempts.append(record)
        if len(attempts) == 1:
            raise failure

    with pytest.raises(RuntimeError) as raised:
        run_push(tmp_path, engine_input, first_diff, None, credentials, on_record=fail_once)
    assert raised.value is failure
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    first = attempts[-1]
    diff, saved, _ = run_diff(tmp_path, engine_input, first, credentials)
    assert not diff["changes"] and not diff["errors"]

    def fail(record: bytes) -> None:
        attempts.append(record)
        raise failure

    with pytest.raises(RuntimeError) as raised:
        run_push(tmp_path, engine_input, saved, first, credentials, on_record=fail)
    assert raised.value is failure
    assert attempts[2:] == [first]
    assert json.loads(first)["outputs"]["example"]["value"] == "sample"
    assert not list(tmp_path.iterdir())


def test_cancelled_storage_call_surfaces_after_final_delivery() -> None:
    records: list[bytes] = []
    cancelled = CancelledError()

    def save(record: bytes) -> None:
        records.append(record)
        if len(records) == 1:
            raise cancelled

    delivery = RecordDelivery(save)
    delivery.publish(b"first")
    delivery.publish(b"final")
    with pytest.raises(CancelledError) as raised:
        delivery.raise_if_failed()
    assert raised.value is cancelled and records == [b"first", b"final"]


@pytest.mark.skipif(not shutil.which("tofu"), reason="The push needs the local binary.")
def test_losing_the_lease_stops_children_outside_the_engines_pipes(tmp_path: Path) -> None:
    executable = shutil.which("tofu")
    assert executable
    workdir = tmp_path / "runs"
    binary = tmp_path / "engine"
    records: list[bytes] = []

    def abort(record: bytes) -> None:
        records.append(record)
        raise AbortRun

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(3)
        binary.write_text(
            f"""#!{sys.executable}
import os
import socket
import sys

if sys.argv[1] == "apply":
    with socket.create_connection({listener.getsockname()!r}, timeout=10) as witness:
        if os.fork() == 0:
            os.close(1)
            os.close(2)
            witness.recv(1)
            os._exit(0)
os.execv({executable!r}, [{executable!r}, *sys.argv[1:]])
"""
        )
        binary.chmod(0o700)
        engine_input = EngineInput(
            config={"output": {"example": {"value": "complete"}}},
            description={"version": 1, "resources": []},
            options={"mirror": tmp_path, "binary": binary},
        )
        credentials: Credentials = {"project_id": 1, "host": "https://127.0.0.1:1", "api_key": "example-key"}
        diff, saved, _ = run_diff(workdir, engine_input, None, credentials)
        assert diff["errors"] == []
        with pytest.raises(AbortRun):
            run_push(workdir, engine_input, saved, None, credentials, on_record=abort)
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(2)
            assert connection.recv(1) == b""

    assert len(records) == 2 and records[0] == records[1]
    assert json.loads(records[-1])["outputs"]["example"]["value"] == "complete"
    assert not list(workdir.iterdir())


def test_backend_keeps_the_last_valid_record_and_rejects_unauthenticated_reads(tmp_path: Path) -> None:
    path = tmp_path / "stack.record"
    record = b'{"serial":7,"resources":[]}'
    writes: list[bytes] = []
    with record_backend(path, read_bindings, writes.append) as env:
        url = urlsplit(env["TF_HTTP_ADDRESS"])
        assert url.hostname == "127.0.0.1"
        with closing(HTTPConnection(url.hostname, url.port, timeout=2)) as client:
            client.request("GET", url.path)
            assert client.getresponse().status == 403
            token = base64.b64encode(f"{env['TF_HTTP_USERNAME']}:{env['TF_HTTP_PASSWORD']}".encode()).decode()
            auth = {"Authorization": f"Basic {token}"}
            for raw, expected in ((record, 200), (b'{"serial":8', 400), (b'{"serial":8,"resources":[null]}', 400)):
                client.request("POST", url.path, raw, auth)
                assert client.getresponse().status == expected
            client.request("GET", url.path, headers=auth)
            assert client.getresponse().read() == record
    assert path.read_bytes() == record and writes == [record]


@pytest.mark.skipif(not shutil.which("tofu"), reason="The older saved diff needs the local binary.")
def test_existing_saved_local_diff_applies_without_replanning(tmp_path: Path) -> None:
    legacy = tmp_path / "old"
    legacy.mkdir()
    description: StackDescription = {"version": 1, "resources": []}
    credentials: Credentials = {"api_key": "example-key", "host": "https://127.0.0.1:1", "project_id": 1}
    engine_input = EngineInput(
        config={"output": {"example": {"value": "reviewed"}}}, description=description, options={"mirror": tmp_path}
    )
    # The saved file carries its own backend and the values the caller reviewed.
    target = {
        "host": credentials["host"],
        "project": str(credentials["project_id"]),
        "description": hashlib.sha256(b'{"resources":[],"version":1}').hexdigest(),
    }
    config = {**engine_input.config, "variable": {"stack_run_target": {"type": "map(string)", "default": target}}}
    (legacy / "main.tf.json").write_text(json.dumps(config))
    binary = shutil.which("tofu")
    assert binary
    for args in (["init", "-input=false"], ["plan", "-input=false", "-out=old.diff"]):
        subprocess.run([binary, *args], cwd=legacy, capture_output=True, check=True)
    updated_input = replace(engine_input, config={"output": {"example": {"value": "later"}}})
    observed: list[bytes] = []
    result, record = run_push(
        tmp_path, updated_input, (legacy / "old.diff").read_bytes(), None, credentials, on_record=observed.append
    )
    assert result["errors"] == []
    assert json.loads(record)["outputs"]["example"]["value"] == "reviewed"
    assert observed and all(candidate == record for candidate in observed)


@pytest.mark.skipif(
    not os.getenv("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="Needs the installed stack mirror and binary.",
)
def test_saved_diff_is_portable_without_session_credentials_or_work_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbidden: list[bytes] = []
    metadata: list[bytes] = []

    @contextmanager
    def observe_backend(
        path: Path, validate: Callable[[bytes], object], on_write: Callable[[bytes], None] | None
    ) -> Iterator[dict[str, str]]:
        with record_backend(path, validate, on_write) as env:
            forbidden.extend(
                [
                    str(path.parent).encode(),
                    env["TF_HTTP_ADDRESS"].encode(),
                    env["TF_HTTP_PASSWORD"].encode(),
                    base64.b64encode(f"stack:{env['TF_HTTP_PASSWORD']}".encode()),
                ]
            )
            yield env
            metadata.extend(
                file.read_bytes()
                for file in (path.parent / ".terraform.lock.hcl", path.parent / ".terraform" / "terraform.tfstate")
            )

    monkeypatch.setattr("products.stacks.backend.engine.runner.record_backend", observe_backend)
    mirror = os.environ["POSTHOG_STACK_MIRROR"]
    forbidden.append(mirror.encode())
    description: StackDescription = {
        "version": 1,
        "resources": [{"kind": "dashboard", "key": "sample", "body": {"name": "Sample"}}],
    }
    target = translate_in(description, [], {"mirror": mirror})
    created = {"id": 17, "name": "Sample", "deleted": False, "pinned": False}
    with _project({"POST /api/projects/7/dashboards/": created}) as (credentials, requests):
        forbidden.append(credentials["api_key"].encode())
        diff, saved, _ = run_diff(tmp_path / "review", target, None, credentials)
        assert not diff["errors"]
        with zipfile.ZipFile(io.BytesIO(saved)) as archive:
            payloads = [archive.read(name) for name in archive.namelist()]
            assert ".terraform.lock.hcl" in archive.namelist()
        pushed, record = run_push(tmp_path / "push", target, saved, None, credentials)
        assert not pushed["errors"]
    assert requests == [("POST", "/api/projects/7/dashboards/")]
    assert read_bindings(record) == [{"kind": "dashboard", "key": "sample", "entity_id": 17}]
    for payload in [json.dumps(diff).encode(), *payloads, *metadata]:
        assert all(value not in payload for value in forbidden)
    assert not list((tmp_path / "review").iterdir()) and not list((tmp_path / "push").iterdir())
