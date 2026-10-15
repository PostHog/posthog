from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from products.posthog_ai.eval_harness.harness.__main__ import use_dashboard
from products.posthog_ai.eval_harness.harness.cli import SkillDelivery, parse_args
from products.posthog_ai.eval_harness.harness.providers import PreflightError


@pytest.mark.parametrize(
    "argv,expected_delivery",
    [
        ([], "bundled"),
        (["--skill-delivery", "exec"], "exec"),
    ],
)
def test_skill_delivery_defaults_to_bundled_and_allows_exec(argv: list[str], expected_delivery: SkillDelivery) -> None:
    assert parse_args(argv).skill_delivery == expected_delivery


@pytest.mark.parametrize(
    "argv,expected",
    [([], 2), (["--infra-retries", "0"], 0), (["--infra-retries", "3"], 3), (["--infra-retries", "-1"], None)],
)
def test_infrastructure_retry_budget(argv: list[str], expected: int | None) -> None:
    if expected is None:
        with pytest.raises(SystemExit) as error:
            parse_args(argv)
        assert error.value.code == 2
    else:
        assert parse_args(argv).infrastructure_retries == expected


@pytest.mark.parametrize("argv,verbose", [([], False), (["--verbose"], True)])
def test_console_output_detail(argv: list[str], verbose: bool) -> None:
    assert parse_args(argv).verbose is verbose


@pytest.mark.parametrize(
    "argv,tty,ci,term,controlling_terminal,expected",
    [
        ([], True, False, "xterm-256color", False, True),
        ([], False, False, "xterm-256color", True, False),
        ([], True, True, "xterm-256color", False, False),
        ([], True, False, "dumb", False, False),
        (["--no-tui"], True, False, "xterm-256color", False, False),
        (["--tui"], True, True, "xterm-256color", False, True),
        (["--tui"], True, False, "dumb", False, True),
        (["--tui"], False, False, "xterm-256color", True, True),
        (["--tui"], False, False, "xterm-256color", False, None),
    ],
)
def test_interactive_output_selection(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    tty: bool,
    ci: bool,
    term: str,
    controlling_terminal: bool,
    expected: bool | None,
) -> None:
    for stream in ("stdin", "stdout"):
        monkeypatch.setattr(f"sys.{stream}.isatty", MagicMock(return_value=tty))
    monkeypatch.setattr("sys.stderr.isatty", MagicMock(return_value=False))
    terminal = MagicMock()
    if not controlling_terminal:
        terminal.side_effect = OSError("No controlling terminal")
    monkeypatch.setattr("products.posthog_ai.eval_harness.harness.__main__.open_terminal", terminal)
    monkeypatch.setenv("TERM", term)
    if ci:
        monkeypatch.setenv("CI", "true")
    else:
        monkeypatch.delenv("CI", raising=False)
    if expected is None:
        with pytest.raises(PreflightError, match="No controlling terminal"):
            use_dashboard(parse_args(argv))
    else:
        assert use_dashboard(parse_args(argv)) is expected
