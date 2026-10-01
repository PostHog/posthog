from __future__ import annotations

import io
import os
import shlex
import hashlib
import builtins
import importlib
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import BinaryIO

import pytest
from unittest.mock import MagicMock

import click
from boto3.session import Session
from botocore.response import StreamingBody
from botocore.stub import Stubber
from click.testing import CliRunner
from hogli_commands.devbox import eval_env

from products.posthog_ai.eval_harness.environment import download


@pytest.fixture
def s3_download(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stubber]:
    client = Session(
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        aws_session_token="testing",
        region_name="us-east-1",
    ).client("s3", endpoint_url="https://s3.amazonaws.com")
    session = MagicMock()
    session.client.return_value = client
    monkeypatch.setattr(download.boto3, "Session", MagicMock(return_value=session))
    with Stubber(client) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()
    client.close()


@pytest.mark.parametrize("checksum", ["invalid", "0" * 64])
def test_invalid_bundle_checksum_does_not_start_or_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checksum: str
) -> None:
    bundle = tmp_path / "environment.tar.gz"
    bundle.write_bytes(b"invented environment bundle")
    start = MagicMock()
    process = MagicMock()
    monkeypatch.setattr(eval_env, "start_or_create_workspace", start)
    monkeypatch.setattr(eval_env.subprocess, "run", process)

    result = CliRunner().invoke(
        eval_env.cmd_prepare_eval_env, ["-n", "eval1", "--bundle", str(bundle), "--sha256", checksum]
    )

    assert result.exit_code != 0
    assert "--sha256" in result.output
    start.assert_not_called()
    process.assert_not_called()


@pytest.mark.parametrize(
    "cache_status,receive_status,restore_status", [(0, 0, 0), (3, 0, 0), (1, 0, 0), (3, 17, 0), (0, 0, 19)]
)
@pytest.mark.parametrize("source", ["local", "s3"])
def test_bundle_relay_restores_only_after_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    s3_download: Stubber,
    source: str,
    cache_status: int,
    receive_status: int,
    restore_status: int,
) -> None:
    payload = b"invented fixture bundle without private source data"
    bundle = tmp_path / "environment $(touch should-not-exist).tar.gz"
    bundle.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    state_dir = ".flox/cache/eval ' $(touch should-not-exist)"
    calls: list[list[str]] = []
    transferred: list[bytes] = []
    start = MagicMock(return_value="devbox-engineer-eval1")
    monkeypatch.setattr(eval_env.tempfile, "tempdir", str(tmp_path))
    if source == "s3":
        s3_download.add_response(
            "get_object",
            {"Body": StreamingBody(io.BytesIO(payload), len(payload)), "ContentLength": len(payload)},
            {"Bucket": "example-fixture-bucket", "Key": "environments/example.tar.gz"},
        )

    def run_transport(
        arguments: list[str], *, stdin: BinaryIO | int, **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        assert arguments[0] == "ssh"
        assert "coder.devbox-engineer-eval1" in arguments
        assert "example-reader" not in " ".join(arguments)
        if source == "s3":
            temporary = list(tmp_path.glob("posthog-eval-environment-*"))
            assert len(temporary) == 1
            assert temporary[0].stat().st_mode & 0o777 == 0o700
            assert (temporary[0] / f"download-{digest}.tar.gz").stat().st_mode & 0o777 == 0o600
        remote = shlex.split(arguments[-1])
        assert remote[:2] == ["bash", "-lc"]
        assert remote[3] == "bash"
        command = remote[4:]
        if command[:3] != ["-m", "products.posthog_ai.eval_harness.environment", "prepare"]:
            assert "s3://" not in " ".join(arguments)
        calls.append(command)
        if command[:3] == ["-m", eval_env.TRANSFER_MODULE, "check"]:
            return subprocess.CompletedProcess(arguments, cache_status)
        if command[:3] == ["-m", eval_env.TRANSFER_MODULE, "receive"]:
            assert not isinstance(stdin, int)
            transferred.append(stdin.read())
            return subprocess.CompletedProcess(arguments, receive_status)
        if command[:3] == ["-m", "products.posthog_ai.eval_harness.environment", "prepare"]:
            return subprocess.CompletedProcess(arguments, restore_status)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(eval_env, "start_or_create_workspace", start)
    monkeypatch.setattr(eval_env, "coder_ssh_alias_configured", lambda name: True)
    monkeypatch.setattr(eval_env.subprocess, "run", run_transport)
    monkeypatch.setattr(eval_env, "get_coder_url", lambda: "https://coder.example.com")
    monkeypatch.setattr(
        eval_env,
        "get_workspace",
        lambda name: {
            "owner_name": "engineer",
            "latest_build": {"resources": [{"agents": [{"apps": [{"slug": "app", "health": "healthy"}]}]}]},
        },
    )

    result = CliRunner().invoke(
        eval_env.cmd_prepare_eval_env,
        [
            "-n",
            "eval1",
            "--bundle",
            str(bundle) if source == "local" else "s3://example-fixture-bucket/environments/example.tar.gz",
            "--sha256",
            digest.upper(),
            "--state-dir",
            state_dir,
            "--user-id",
            "7",
            "--target-cutoff",
            "2025-01-15T00:00:00Z",
            *(["--aws-profile", "example-reader"] if source == "s3" else []),
        ],
    )

    failed = cache_status == 1 or receive_status != 0 or restore_status != 0
    assert result.exit_code == (1 if failed else 0), result.output
    assert transferred == ([payload] if cache_status == 3 else [])
    start.assert_called_once_with("eval1", None, eval_env.DEFAULT_TEMPLATE, eval_env.DEFAULT_PRESET, None, False, False)
    restore = [
        command for command in calls if command[:3] == ["-m", "products.posthog_ai.eval_harness.environment", "prepare"]
    ]
    if cache_status == 1 or receive_status != 0:
        assert not restore
        assert (
            "Verifying the cached bundle failed" if cache_status == 1 else "Copying the data bundle failed"
        ) in result.output
    else:
        assert restore == [
            [
                "-m",
                "products.posthog_ai.eval_harness.environment",
                "prepare",
                f"{state_dir}/upload-{digest}.tar.gz",
                "--sha256",
                digest,
                "--state-dir",
                state_dir,
                "--site-url",
                "https://app--devbox-engineer-eval1--engineer.coder.example.com",
                "--user-id",
                "7",
                "--target-cutoff",
                "2025-01-15T00:00:00Z",
                *(
                    ["--source-uri", "s3://example-fixture-bucket/environments/example.tar.gz"]
                    if source == "s3"
                    else []
                ),
            ]
        ]
    assert ("Eval environment ready" in result.output) is not failed
    assert not (tmp_path / "should-not-exist").exists()
    assert not list(tmp_path.glob("posthog-eval-environment-*"))
    assert isinstance(download.boto3.Session, MagicMock)
    if source == "s3":
        download.boto3.Session.assert_called_once_with(profile_name="example-reader")
    else:
        download.boto3.Session.assert_not_called()


@pytest.mark.parametrize("failure", ["access", "checksum", "truncated"])
def test_s3_download_failure_removes_private_download_before_creating_devbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, s3_download: Stubber, failure: str
) -> None:
    payload = b"invented environment bundle"
    digest = hashlib.sha256(payload).hexdigest()
    expected = {"Bucket": "example-fixture-bucket", "Key": "environments/example.tar.gz"}
    if failure == "access":
        s3_download.add_client_error(
            "get_object",
            service_error_code="AccessDenied",
            service_message="private-service-details",
            expected_params=expected,
        )
    else:
        size = len(payload) + int(failure == "truncated")
        s3_download.add_response(
            "get_object", {"Body": StreamingBody(io.BytesIO(payload), size), "ContentLength": size}, expected
        )
    start = MagicMock()
    process = MagicMock()
    monkeypatch.setattr(eval_env, "start_or_create_workspace", start)
    monkeypatch.setattr(eval_env.subprocess, "run", process)
    monkeypatch.setattr(eval_env.tempfile, "tempdir", str(tmp_path))

    result = CliRunner().invoke(
        eval_env.cmd_prepare_eval_env,
        [
            "-n",
            "eval1",
            "--bundle",
            "s3://example-fixture-bucket/environments/example.tar.gz",
            "--sha256",
            "0" * 64 if failure == "checksum" else digest,
        ],
    )

    assert result.exit_code == 1
    assert (
        "does not match --sha256" in result.output if failure == "checksum" else "S3 download failed" in result.output
    )
    assert "private-service-details" not in result.output
    start.assert_not_called()
    process.assert_not_called()
    assert not list(tmp_path.iterdir())
    assert isinstance(download.boto3.Session, MagicMock)
    download.boto3.Session.assert_called_once_with(profile_name=None)


@pytest.mark.parametrize(
    "source,options,expected",
    [
        ("s3://example-fixture-bucket/environment.tar.gz", [], "S3 bundles require --sha256"),
        ("environment.tar.gz", ["--aws-profile", "example-reader"], "--aws-profile applies only to an S3 bundle"),
        ("https://example.com/environment.tar.gz", [], "local .tar.gz file or an s3://"),
        ("missing.tar.gz", [], "does not exist"),
    ],
)
def test_invalid_bundle_source_is_rejected_before_creating_devbox(
    monkeypatch: pytest.MonkeyPatch, source: str, options: list[str], expected: str
) -> None:
    start = MagicMock()
    monkeypatch.setattr(eval_env, "start_or_create_workspace", start)

    result = CliRunner().invoke(eval_env.cmd_prepare_eval_env, ["-n", "eval1", "--bundle", source, *options])

    assert result.exit_code == 2
    assert expected in result.output
    start.assert_not_called()


@pytest.mark.parametrize("operation", ["help", "local", "s3"])
def test_optional_aws_sdk_is_only_required_for_s3_bundles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    import_module = builtins.__import__

    def without_sdk(
        name: str,
        globals_: Mapping[str, object] | None = None,
        locals_: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> ModuleType:
        if name == "products.posthog_ai.eval_harness.environment.download" or name.split(".")[0] in {
            "boto3",
            "botocore",
        }:
            raise ModuleNotFoundError("No module named 'boto3'", name="boto3")
        return import_module(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", without_sdk)
    importlib.reload(eval_env)
    bundle = tmp_path / "environment.tar.gz"
    bundle.write_bytes(b"invented environment bundle")
    monkeypatch.setattr(eval_env, "coder_ssh_alias_configured", lambda name: False)
    arguments = (
        ["--help"]
        if operation == "help"
        else [
            "-n",
            "eval1",
            "--bundle",
            str(bundle) if operation == "local" else "s3://example-fixture-bucket/environment.tar.gz",
            *(["--sha256", "0" * 64] if operation == "s3" else []),
        ]
    )

    result = CliRunner().invoke(eval_env.cmd_prepare_eval_env, arguments)

    if operation == "help":
        assert result.exit_code == 0
        assert "--aws-profile" in result.output
    else:
        assert result.exit_code == 1
        assert (
            "Coder SSH access is not configured"
            if operation == "local"
            else "uv tool install --python 3.13 --with boto3 ./tools/hogli"
        ) in result.output


def test_unhealthy_coder_app_does_not_report_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([0.0, 0.0, float(eval_env.APP_TIMEOUT + 1)])
    monkeypatch.setattr(eval_env.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(eval_env.time, "sleep", lambda delay: None)
    monkeypatch.setattr(eval_env, "get_workspace", lambda name: {"latest_build": {"resources": []}})

    with pytest.raises(click.ClickException, match="data was restored, but Coder"):
        eval_env.EvalEnvironmentDevbox("devbox-engineer-eval1", ".flox/cache/eval-environment").wait_for_app()


@pytest.mark.parametrize("available", [False, True])
def test_source_ref_requires_setup_in_the_selected_commit(monkeypatch: pytest.MonkeyPatch, available: bool) -> None:
    commit = "a" * 40
    process = MagicMock(
        side_effect=[
            subprocess.CompletedProcess([], 0, stdout=f"{commit}\n"),
            subprocess.CompletedProcess([], 0 if available else 1),
        ]
    )
    monkeypatch.setattr(eval_env.subprocess, "run", process)

    if available:
        assert eval_env.resolve_source_commit("feature/eval-setup") == commit
    else:
        with pytest.raises(click.ClickException, match="does not include eval environment setup"):
            eval_env.resolve_source_commit("feature/eval-setup")


@pytest.mark.parametrize("cutoff", ["not-a-date", "2025-01-15T00:00:00"])
def test_invalid_target_cutoff_is_rejected_before_creating_devbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cutoff: str
) -> None:
    bundle = tmp_path / "environment.tar.gz"
    bundle.write_bytes(b"invented bundle")
    start = MagicMock()
    monkeypatch.setattr(eval_env, "start_or_create_workspace", start)

    result = CliRunner().invoke(
        eval_env.cmd_prepare_eval_env, ["-n", "eval1", "--bundle", str(bundle), "--target-cutoff", cutoff]
    )

    assert result.exit_code == 2
    assert "--target-cutoff must be an ISO datetime with a timezone" in result.output
    start.assert_not_called()


def test_fifo_bundle_is_rejected_without_waiting_for_a_writer(tmp_path: Path) -> None:
    bundle = tmp_path / "environment.tar.gz"
    os.mkfifo(bundle)

    result = CliRunner().invoke(eval_env.cmd_prepare_eval_env, ["-n", "eval1", "--bundle", str(bundle)])

    assert result.exit_code == 1
    assert "regular .tar.gz file" in result.output


def test_remote_shell_preserves_arguments_and_binary_stdin(tmp_path: Path) -> None:
    home = tmp_path / "home"
    wrapper = home / "posthog/.codex/with-flox"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text('#!/bin/sh\nprintf "%s\\0" "$@" > "$HOME/arguments"\ncat > "$HOME/payload"\n')
    wrapper.chmod(0o700)
    state_dir = ".flox/cache/eval ' $(touch should-not-exist)"
    arguments = ["-m", eval_env.TRANSFER_MODULE, "receive", "--state-dir", state_dir]
    target = eval_env.EvalEnvironmentDevbox("devbox-engineer-eval1", state_dir)
    remote = shlex.split(target.run_python(*arguments)[-1])

    result = subprocess.run(
        ["bash", "-c", remote[2], *remote[3:]],
        input=b"invented\0binary fixture\xff",
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (home / "arguments").read_bytes().split(b"\0") == [
        argument.encode() for argument in ["python", *arguments, ""]
    ]
    assert (home / "payload").read_bytes() == b"invented\0binary fixture\xff"
    assert not (home / "posthog/should-not-exist").exists()


def test_readiness_waits_for_checkout_files_after_git_directory_appears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    checkout = home / "posthog"
    (checkout / ".git").mkdir(parents=True)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    git = binaries / "git"
    git.write_text("#!/bin/sh\nexit 0\n")
    git.chmod(0o700)
    run_shell = subprocess.run
    attempts = 0

    def probe(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            for relative in (".codex/with-flox", "bin/hogli"):
                executable = checkout / relative
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_text("#!/bin/sh\nexit 0\n")
                executable.chmod(0o700)
        remote = shlex.split(arguments[-1])
        return run_shell(
            ["bash", "-c", remote[2], *remote[3:]],
            env={"HOME": str(home), "PATH": f"{binaries}:/usr/bin:/bin"},
            capture_output=True,
            check=False,
        )

    clock = iter([0.0, 0.0, 1.0])
    monkeypatch.setattr(eval_env.subprocess, "run", probe)
    monkeypatch.setattr(eval_env.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(eval_env.time, "sleep", lambda delay: None)

    eval_env.EvalEnvironmentDevbox("devbox-engineer-eval1", ".flox/cache/eval-environment").wait_for_checkout()

    assert attempts == 2


@pytest.mark.parametrize("dirty,running", [(True, False), (False, True)])
def test_source_checkout_does_not_replace_edits_or_running_app(tmp_path: Path, dirty: bool, running: bool) -> None:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    home = tmp_path / "home"
    (home / "posthog").mkdir(parents=True)
    git = binaries / "git"
    git.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "rev-parse) printf '%s\\n' old-commit ;;\n"
        f"status) {'echo changed-file' if dirty else ':'} ;;\n"
        f"*) touch '{tmp_path / 'unexpected-mutation'}' ;;\n"
        "esac\n"
    )
    pgrep = binaries / "pgrep"
    pgrep.write_text(f"#!/bin/sh\nexit {0 if running else 1}\n")
    for executable in (git, pgrep):
        executable.chmod(0o700)

    result = subprocess.run(
        ["bash", "-c", eval_env._PREPARE_SOURCE, "bash", "a" * 40],
        env={"HOME": str(home), "PATH": f"{binaries}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert ("local changes" if dirty else "running or starting") in result.stderr
    assert not (tmp_path / "unexpected-mutation").exists()


@pytest.mark.parametrize("cache_ready,prepare_status", [(True, 0), (False, 0), (False, 9)])
def test_remote_bootstrap_prepares_missing_cache_and_propagates_failure(
    tmp_path: Path, cache_ready: bool, prepare_status: int
) -> None:
    home = tmp_path / "home"
    checkout = home / "posthog"
    transfer = checkout / eval_env.TRANSFER_PATH
    transfer.parent.mkdir(parents=True)
    transfer.touch()
    wrapper = checkout / ".codex/with-flox"
    wrapper.parent.mkdir()
    wrapper.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/environment-calls"\n'
        f'if [ "$1" = "--prepare" ]; then exit {prepare_status}; fi\n'
        f"exit {0 if cache_ready else 1}\n"
    )
    wrapper.chmod(0o700)

    result = subprocess.run(
        ["bash", "-c", eval_env._PREPARE_SOURCE, "bash", ""],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=False,
    )

    assert result.returncode == (0 if cache_ready else prepare_status)
    assert (home / "environment-calls").read_text().splitlines() == (
        ["true"] if cache_ready else ["true", "--prepare true"]
    )
