from __future__ import annotations

from typing import Any

import pytest

from click.testing import CliRunner
from hogli.cli import cli

runner = CliRunner()


def test_wait_command_registered() -> None:
    result = runner.invoke(cli, ["wait", "--help"])

    assert result.exit_code == 0
    assert "Block until the detached dev stack is ready" in result.output


def test_stop_command_registered() -> None:
    result = runner.invoke(cli, ["stop", "--help"])

    assert result.exit_code == 0
    assert "Stop the detached dev stack gracefully" in result.output


def test_up_command_registered_as_start_alias() -> None:
    result = runner.invoke(cli, ["up", "--help"])

    assert result.exit_code == 0
    assert "Alias for `hogli start`" in result.output


def test_down_command_registered_as_stop_alias() -> None:
    result = runner.invoke(cli, ["down", "--help"])

    assert result.exit_code == 0
    assert "Alias for `hogli stop`" in result.output


def test_up_forwards_detached_flag_to_start_script(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command, **kwargs) -> None:
        captured["command"] = command
        captured["kwargs"] = kwargs

    monkeypatch.setattr("hogli.command_types._run", fake_run)

    result = runner.invoke(cli, ["up", "-d"])

    assert result.exit_code == 0
    command = captured["command"]
    assert command[0].endswith("/bin/start")
    assert command[1:] == ["-d"]


def test_wait_forwards_args_and_preserves_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command, **kwargs) -> None:
        captured["command"] = command
        captured["kwargs"] = kwargs
        raise SystemExit(3)

    monkeypatch.setattr("hogli.command_types._run", fake_run)

    result = runner.invoke(cli, ["wait", "--timeout", "1", "--json"])

    assert result.exit_code == 3
    assert captured["command"] == ["phrocs", "wait", "--timeout", "1", "--json"]
    assert captured["kwargs"]["preserve_exit_code"] is True


def test_stop_forwards_timeout_and_preserves_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command, **kwargs) -> None:
        captured["command"] = command
        captured["kwargs"] = kwargs
        raise SystemExit(2)

    monkeypatch.setattr("hogli.command_types._run", fake_run)

    result = runner.invoke(cli, ["stop", "--timeout", "42"])

    assert result.exit_code == 2
    assert captured["command"] == ["phrocs", "stop", "--timeout", "42"]
    assert captured["kwargs"]["preserve_exit_code"] is True


def test_down_forwards_timeout_and_preserves_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command, **kwargs) -> None:
        captured["command"] = command
        captured["kwargs"] = kwargs
        raise SystemExit(2)

    monkeypatch.setattr("hogli.command_types._run", fake_run)

    result = runner.invoke(cli, ["down", "--timeout", "42"])

    assert result.exit_code == 2
    assert captured["command"] == ["phrocs", "stop", "--timeout", "42"]
    assert captured["kwargs"]["preserve_exit_code"] is True
