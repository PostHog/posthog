from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from products.posthog_ai.eval_harness.harness.__main__ import use_dashboard
from products.posthog_ai.eval_harness.harness.cli import DEFAULT_AGENT_MODEL_BY_RUNTIME, SkillDelivery, parse_args


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (["suite", "--compare"], list(DEFAULT_AGENT_MODEL_BY_RUNTIME.items())),
        (
            ["suite", "--compare-model", "codex:gpt-example", "--compare-model", "codex:gpt-other"],
            [("codex", "gpt-example"), ("codex", "gpt-other")],
        ),
        (["suite", "--compare-model", "codex:gpt-example"], None),
        (["suite", "--compare-model", "unknown:model"], None),
        (["suite", "--compare-model", "claude:"], None),
        (["suite", "--compare-model", "claude:model", "--compare-model", "claude:model"], None),
        (["--compare"], None),
        (["suite", "--compare", "--agent-runtime", "codex"], None),
        (["suite", "--compare", "--tui"], None),
        (["--comparison-dir", "example"], None),
    ],
)
def test_model_comparison_arguments(arguments: list[str], expected: list[tuple[str, str]] | None) -> None:
    if expected is None:
        with pytest.raises(SystemExit) as error:
            parse_args(arguments)
        assert error.value.code == 2
    else:
        assert [(target.runtime, target.model) for target in parse_args(arguments).comparison_models] == expected


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
    "stdout_tty,hogli_stdout_tty,ci,expected",
    [
        (True, None, False, True),
        (True, None, True, False),
        (False, "1", False, True),
        (False, "0", False, False),
    ],
    ids=["terminal", "ci", "secrets-wrapper-pipe", "redirected-hogli-output"],
)
def test_interactive_output_selection(
    monkeypatch: pytest.MonkeyPatch, stdout_tty: bool, hogli_stdout_tty: str | None, ci: bool, expected: bool
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", MagicMock(return_value=True))
    monkeypatch.setattr("sys.stdout.isatty", MagicMock(return_value=stdout_tty))
    if hogli_stdout_tty is None:
        monkeypatch.delenv("HOGLI_STDOUT_TTY", raising=False)
    else:
        monkeypatch.setenv("HOGLI_STDOUT_TTY", hogli_stdout_tty)
    monkeypatch.setenv("TERM", "xterm-256color")
    if ci:
        monkeypatch.setenv("CI", "true")
    else:
        monkeypatch.delenv("CI", raising=False)
    assert use_dashboard(parse_args([])) is expected
