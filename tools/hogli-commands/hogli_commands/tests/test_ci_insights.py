from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from unittest.mock import patch

from click.testing import CliRunner
from hogli_commands import ci_insights


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def ready() -> Iterator[None]:
    """Backend binary present and authenticated."""
    with (
        patch.object(ci_insights.shutil, "which", return_value="/usr/bin/mendral"),
        patch.object(ci_insights, "_capture", return_value="Authenticated"),
    ):
        yield


def test_missing_binary_reports_install_hint(runner: CliRunner) -> None:
    with patch.object(ci_insights.shutil, "which", return_value=None):
        result = runner.invoke(ci_insights.ci_insights, [])
    assert result.exit_code != 0
    assert "brew install mendral-ai/tap/mendral" in result.output


def test_unauthenticated_reports_login_hint(runner: CliRunner) -> None:
    with (
        patch.object(ci_insights.shutil, "which", return_value="/usr/bin/mendral"),
        patch.object(ci_insights, "_capture", return_value="Not authenticated. Run 'mendral auth login'."),
    ):
        result = runner.invoke(ci_insights.ci_insights, [])
    assert result.exit_code != 0
    assert "auth login" in result.output


@pytest.mark.parametrize(
    "argv, expected",
    [
        ([], ("mendral", "here")),
        (["search", "flaky timeout"], ("mendral", "insight", "search", "flaky timeout")),
        (["view", "01ABC"], ("mendral", "insight", "view", "01ABC")),
        (["view", "01ABC", "--json"], ("mendral", "insight", "view", "01ABC", "--json")),
    ],
)
def test_verb_maps_to_backend_call(runner: CliRunner, ready: None, argv: list[str], expected: tuple[str, ...]) -> None:
    with patch.object(ci_insights, "_run", return_value=0) as run:
        result = runner.invoke(ci_insights.ci_insights, argv)
    assert result.exit_code == 0
    run.assert_called_once_with(*expected)


@pytest.mark.parametrize("argv", [[], ["search", "x"], ["view", "01ABC"]])
def test_backend_exit_code_propagates(runner: CliRunner, ready: None, argv: list[str]) -> None:
    with patch.object(ci_insights, "_run", return_value=7):
        result = runner.invoke(ci_insights.ci_insights, argv)
    assert result.exit_code == 7


@pytest.mark.parametrize("argv", [["--help"], ["search", "--help"], ["view", "--help"], ["plan", "--help"]])
def test_help_works_without_backend(runner: CliRunner, argv: list[str]) -> None:
    with patch.object(ci_insights.shutil, "which", return_value=None):
        result = runner.invoke(ci_insights.ci_insights, argv)
    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "not found" not in result.output


_INSIGHT = {
    "actions": [
        {"id": "a1", "recommended": True, "status": "merged", "title": "Old fix", "full_plan": "merged plan"},
        {"id": "a2", "recommended": True, "status": "proposed", "title": "New fix", "full_plan": "do X then Y"},
    ]
}


def test_plan_prints_actionable_recommended_plan(runner: CliRunner) -> None:
    with (
        patch.object(ci_insights.shutil, "which", return_value="/usr/bin/mendral"),
        patch.object(ci_insights, "_capture", side_effect=["Authenticated", json.dumps(_INSIGHT)]),
    ):
        result = runner.invoke(ci_insights.ci_insights, ["plan", "01XYZ"])
    assert result.exit_code == 0
    assert "New fix" in result.output
    assert "do X then Y" in result.output


def test_plan_errors_when_no_actions(runner: CliRunner) -> None:
    with (
        patch.object(ci_insights.shutil, "which", return_value="/usr/bin/mendral"),
        patch.object(ci_insights, "_capture", side_effect=["Authenticated", json.dumps({"actions": []})]),
    ):
        result = runner.invoke(ci_insights.ci_insights, ["plan", "01XYZ"])
    assert result.exit_code != 0
    assert "No remediation plan" in result.output


@pytest.mark.parametrize("payload", ["", "not json{", '{"actions": [null]}'])
def test_plan_reports_clean_error_on_bad_response(runner: CliRunner, payload: str) -> None:
    with (
        patch.object(ci_insights.shutil, "which", return_value="/usr/bin/mendral"),
        patch.object(ci_insights, "_capture", side_effect=["Authenticated", payload]),
    ):
        result = runner.invoke(ci_insights.ci_insights, ["plan", "01XYZ"])
    assert result.exit_code != 0
    assert "Traceback" not in result.output


def test_plan_errors_when_recommended_action_has_no_plan_text(runner: CliRunner) -> None:
    insight = {"actions": [{"id": "a", "recommended": True, "status": "proposed", "full_plan": ""}]}
    with (
        patch.object(ci_insights.shutil, "which", return_value="/usr/bin/mendral"),
        patch.object(ci_insights, "_capture", side_effect=["Authenticated", json.dumps(insight)]),
    ):
        result = runner.invoke(ci_insights.ci_insights, ["plan", "01XYZ"])
    assert result.exit_code != 0
    assert "no plan text" in result.output


def test_plan_warns_when_only_fix_is_merged(runner: CliRunner) -> None:
    insight = {"actions": [{"id": "a", "recommended": True, "status": "merged", "title": "X", "full_plan": "the plan"}]}
    with (
        patch.object(ci_insights.shutil, "which", return_value="/usr/bin/mendral"),
        patch.object(ci_insights, "_capture", side_effect=["Authenticated", json.dumps(insight)]),
    ):
        result = runner.invoke(ci_insights.ci_insights, ["plan", "01XYZ"])
    assert result.exit_code == 0
    assert "already been merged" in result.output
    assert "the plan" in result.output


@pytest.mark.parametrize(
    "actions, expected_id",
    [
        ([], None),
        ([{"id": "a", "status": "merged"}], "a"),
        (
            [
                {"id": "a", "recommended": True, "status": "merged"},
                {"id": "b", "recommended": True, "status": "proposed"},
            ],
            "b",
        ),
        ([{"id": "a", "recommended": True, "status": "merged"}], "a"),
        (
            [
                {"id": "a", "recommended": False, "status": "proposed"},
                {"id": "b", "recommended": True, "status": "rejected"},
            ],
            "b",
        ),
    ],
)
def test_recommended_action_selection(actions: list[dict[str, object]], expected_id: str | None) -> None:
    chosen = ci_insights._recommended_action(actions)
    assert (chosen or {}).get("id") == expected_id
