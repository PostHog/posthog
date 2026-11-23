import sys
import json
import signal
import socket
import hashlib
import subprocess
from pathlib import Path

import pytest

from products.stacks.backend.engine.deadline import remaining
from products.stacks.backend.engine.local import main
from products.stacks.backend.engine.runner import run_diff, run_push
from products.stacks.backend.engine.tests.test_translate_out import ENGINE_WORDS
from products.stacks.backend.engine.types import Credentials, EngineInput, StackDescription

DESCRIPTION: StackDescription = {"version": 1, "resources": []}
CREDENTIALS: Credentials = {
    "host": "https://127.0.0.1:1",
    "project_id": 7,
    "api_key": "example-api-key",
    "secrets": {"token": "example-secret"},
}


def _stalled_engine(tmp_path: Path, listener: socket.socket, stage: str) -> Path:
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(5)
    binary = tmp_path / "engine"
    binary.write_text(
        rf"""#!{sys.executable}
import json
import os
import socket
import sys
import time
from pathlib import Path

command = sys.argv[1]
if command == "plan":
    Path("saved.diff").write_bytes(b"{{}}")
if command == {stage!r}:
    child = os.fork()
    if child == 0:
        with socket.create_connection(("127.0.0.1", {listener.getsockname()[1]})) as witness:
            witness.sendall(json.dumps(sorted(p.name for p in Path.cwd().iterdir())).encode() + b"\n")
            time.sleep(3)
        os._exit(0)
    os.waitpid(child, 0)
if command == "show":
    print(Path("saved.diff").read_text())
"""
    )
    binary.chmod(0o700)
    return binary


def _reviewed_diff() -> bytes:
    description = json.dumps(DESCRIPTION, sort_keys=True, separators=(",", ":")).encode()
    target = {"host": CREDENTIALS["host"], "project": "7", "description": hashlib.sha256(description).hexdigest()}
    return json.dumps({"variables": {"stack_run_target": {"value": target}}}).encode()


def test_large_finite_timeout_allows_completed_commands(tmp_path: Path) -> None:
    with socket.socket() as listener:
        binary = _stalled_engine(tmp_path, listener, "none")
        engine_input = EngineInput(
            config={}, description=DESCRIPTION, options={"binary": binary, "mirror": tmp_path, "timeout_seconds": 1e30}
        )
        diff, saved, _ = run_diff(tmp_path, engine_input, None, CREDENTIALS)
    assert diff["errors"] == []
    assert saved


@pytest.mark.parametrize("stage", ["init", "plan", "show", "apply"])
def test_timeout_stops_children_and_removes_private_files(tmp_path: Path, stage: str) -> None:
    workdir = tmp_path / "runs"
    with socket.socket() as listener:
        binary = _stalled_engine(tmp_path, listener, stage)
        engine_input = EngineInput(
            config={},
            description=DESCRIPTION,
            options={"mirror": tmp_path, "binary": binary, "timeout_seconds": 0.5},
            secret_names=frozenset({"token"}),
        )
        if stage in ("show", "apply"):
            pushed, _ = run_push(workdir, engine_input, _reviewed_diff(), None, CREDENTIALS)
            errors = pushed["errors"]
        else:
            diff, saved, _ = run_diff(workdir, engine_input, None, CREDENTIALS)
            assert not saved
            errors = diff["errors"]

        assert [error["code"] for error in errors] == ["run_timeout"]
        assert not ENGINE_WORDS.search(errors[0]["message"])
        connection, _ = listener.accept()
        with connection, connection.makefile("rb") as child:
            private_files = json.loads(child.readline())
            if stage == "plan":
                assert "inputs.auto.tfvars.json" in private_files
            if stage != "init":
                assert "saved.diff" in private_files
            connection.settimeout(1)
            assert child.read(1) == b""
    assert list(workdir.iterdir()) == []


@pytest.mark.parametrize("usable_partial", ["errored.tfstate", "terraform.tfstate", "terraform.tfstate.backup", None])
def test_interrupted_snapshot_writes_keep_the_last_readable_snapshot(
    tmp_path: Path, usable_partial: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior = b'{"serial":2,"resources":[]}'
    partial = b'{"serial":3,"resources":[{"mode":"managed","type":"posthog_dashboard","name":"stack_demo","instances":[{"attributes":{"id":7}}]}]}'
    snapshots = {"errored.tfstate": b"{", "terraform.tfstate": b""}
    if usable_partial:
        snapshots[usable_partial] = partial

    def interrupted_command(
        binary: str, directory: Path, env: object, deadline: float, command: str, *args: str, **kwargs: object
    ) -> bytes:
        if command == "show":
            return (directory / "saved.diff").read_bytes()
        if command == "apply":
            for filename, contents in snapshots.items():
                (directory / filename).write_bytes(contents)
            # Recovery must see the interrupted write regardless of how long it took the worker to start.
            remaining(0)
        return b""

    monkeypatch.setattr("products.stacks.backend.engine.runner._command", interrupted_command)
    engine_input = EngineInput(
        config={}, description=DESCRIPTION, options={"binary": sys.executable, "mirror": tmp_path}
    )
    pushed, recovered = run_push(tmp_path / "runs", engine_input, _reviewed_diff(), prior, CREDENTIALS)

    assert [error["code"] for error in pushed["errors"]] == ["run_timeout"]
    assert recovered == (partial if usable_partial else prior)
    assert pushed["bindings"] == ([{"kind": "dashboard", "key": "demo", "entity_id": 7}] if usable_partial else [])
    assert list((tmp_path / "runs").iterdir()) == []


@pytest.mark.parametrize("interrupt", [signal.SIGINT, signal.SIGTERM])
def test_interrupted_runner_reaps_children_and_removes_secrets(tmp_path: Path, interrupt: signal.Signals) -> None:
    workdir = tmp_path / "runs"
    with socket.socket() as listener:
        binary = _stalled_engine(tmp_path, listener, "plan")
        script = f"""
from products.stacks.backend.engine.runner import run_diff
from products.stacks.backend.engine.types import EngineInput
engine_input = EngineInput(config={{}}, description={DESCRIPTION!r}, options={{"mirror": {str(tmp_path)!r}, "binary": {str(binary)!r}}}, secret_names=frozenset({{"token"}}))
run_diff({str(workdir)!r}, engine_input, None, {CREDENTIALS!r})
"""
        with subprocess.Popen(
            [sys.executable, "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ) as runner:
            connection, _ = listener.accept()
            with connection, connection.makefile("rb") as child:
                assert "inputs.auto.tfvars.json" in json.loads(child.readline())
                runner.send_signal(interrupt)
                assert runner.wait(timeout=3) != 0
                connection.settimeout(1)
                assert child.read(1) == b""
    assert list(workdir.iterdir()) == []


def test_local_diff_uses_the_requested_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    definition = tmp_path / "description.json"
    definition.write_text(json.dumps(DESCRIPTION))
    with socket.socket() as listener:
        binary = _stalled_engine(tmp_path, listener, "plan")
        monkeypatch.setenv("POSTHOG_API_KEY", "example-key")
        monkeypatch.setenv("POSTHOG_STACK_BINARY", str(binary))
        result = main(
            [
                "diff",
                str(definition),
                "--host",
                "https://127.0.0.1:1",
                "--project-id",
                "7",
                "--mirror",
                str(tmp_path),
                "--timeout-seconds",
                "0.5",
            ]
        )
    assert result == 1
    errors = json.loads(capsys.readouterr().out)["errors"]
    assert [error["code"] for error in errors] == ["run_timeout"]
    assert not ENGINE_WORDS.search(errors[0]["message"])


def test_an_engine_killed_during_push_reports_an_interrupted_run(tmp_path: Path) -> None:
    # A killed engine may have created an entity it never recorded, so the push must not read as an ordinary
    # failure: the service treats an interrupted run as uncertain and asks a person to reconcile.
    binary = tmp_path / "engine"
    binary.write_text(
        f"""#!{sys.executable}
import os, signal, sys
from pathlib import Path
if sys.argv[1] == "show":
    print(Path("saved.diff").read_text())
if sys.argv[1] == "apply":
    os.kill(os.getpid(), signal.SIGKILL)
"""
    )
    binary.chmod(0o700)
    engine_input = EngineInput(config={}, description=DESCRIPTION, options={"binary": binary, "mirror": tmp_path})

    result, _ = run_push(tmp_path / "runs", engine_input, _reviewed_diff(), None, CREDENTIALS)

    assert [error["code"] for error in result["errors"]] == ["stack_interrupted"]
    assert not ENGINE_WORDS.search(json.dumps(result["errors"]))
