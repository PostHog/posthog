from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

from click.testing import CliRunner
from hogli_commands import verify_stamp
from hogli_commands.test_runner import ChangedTests
from hogli_commands.verify_layers import (
    ChangeKind,
    ComplexityLayer,
    _print_manual_layers,
    classify,
    plan_verification,
    verify,
)
from hogli_commands.verify_stamp import (
    read_stamp,
    stamp_path,
    verify_gate,
    working_tree_content_hash,
    working_tree_snapshot,
    write_stamp,
)


@pytest.fixture
def repo(tmp_path: Path, git: Callable[..., str], monkeypatch: pytest.MonkeyPatch) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / "team.py").write_text("a = 1\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.setattr(verify_stamp, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("GIT_INDEX_FILE", raising=False)
    return tmp_path


class TestClassify:
    @pytest.mark.parametrize(
        "path,expected_kind",
        [
            ("posthog/api/test/test_insight.py", ChangeKind.TEST),
            ("posthog/api/test/__snapshots__/test_insight.ambr", ChangeKind.TEST),
            ("frontend/src/scenes/insights/Insight.test.tsx", ChangeKind.TEST),
            ("playwright/e2e/dashboards.spec.ts", ChangeKind.END_TO_END_TEST),
            ("posthog/api/insight.py", ChangeKind.API_SCHEMA),
            ("products/surveys/backend/api/survey.py", ChangeKind.API_SCHEMA),
            ("posthog/migrations/0999_add_field.py", ChangeKind.MIGRATION),
            ("frontend/src/scenes/insights/insightLogic.tsx", ChangeKind.KEA_LOGIC),
            ("frontend/src/scenes/insights/Insight.tsx", ChangeKind.REACT_COMPONENT),
            ("frontend/src/scenes/insights/Insight.stories.tsx", ChangeKind.REACT_COMPONENT),
            ("frontend/src/styles/base.scss", ChangeKind.CSS),
            ("posthog/hogql_queries/insights/trends/trends_query_runner.py", ChangeKind.SQL_OR_HOGQL),
            (".github/workflows/ci-backend.yml", ChangeKind.CI_WORKFLOW),
            (".agents/skills/verifying-changes/SKILL.md", ChangeKind.DOCS_OR_SKILLS),
            ("products/surveys/skills/creating-surveys/references/guide.md", ChangeKind.DOCS_OR_SKILLS),
            ("posthog/settings/web.py", ChangeKind.APP_WIRING),
            ("products/surveys/backend/routes.py", ChangeKind.APP_WIRING),
            ("posthog/csp_middleware.py", ChangeKind.APP_WIRING),
            ("posthog/models/team/team.py", ChangeKind.PURE_LOGIC),
            ("docs/onboarding/web-analytics/react.tsx", ChangeKind.REACT_COMPONENT),
            (".agents/skills/verifying-changes/scripts/check.py", ChangeKind.PURE_LOGIC),
            (".github/actions/paths-filter/action.yml", ChangeKind.CI_WORKFLOW),
            (".github/actions/paths-filter/__tests__/filter.test.ts", ChangeKind.TEST),
            (".github/actions/paths-filter/src/filter.ts", ChangeKind.PURE_LOGIC),
            ("posthog/templates/authorize_and_link.html", ChangeKind.DJANGO_TEMPLATE),
        ],
    )
    def test_kind(self, path: str, expected_kind: ChangeKind) -> None:
        assert classify(path).kind == expected_kind


class TestPlanVerification:
    @pytest.mark.parametrize(
        "paths,runs_unit_tests,manual_layers",
        [
            (["docs/internal/monorepo-layout.md", ".github/workflows/ci-backend.yml"], False, ()),
            (["posthog/models/team/team.py", "posthog/api/test/test_team.py"], True, ()),
            (
                ["frontend/src/scenes/insights/Insight.tsx", "posthog/api/insight.py", "posthog/settings/web.py"],
                True,
                (ComplexityLayer.OPENAPI, ComplexityLayer.STORYBOOK, ComplexityLayer.STACK),
            ),
        ],
    )
    def test_layers(self, paths: list[str], runs_unit_tests: bool, manual_layers: tuple[ComplexityLayer, ...]) -> None:
        plan = plan_verification(paths)
        assert plan.runs_unit_tests is runs_unit_tests
        assert plan.manual_layers == manual_layers

    @pytest.mark.parametrize(
        "outstanding,claims_enough",
        [((), True), (("[markdown-format] was skipped: needs node. Set up what it needs.",), False)],
    )
    def test_outstanding_check_does_not_claim_enough(
        self, capsys: pytest.CaptureFixture[str], outstanding: tuple[str, ...], claims_enough: bool
    ) -> None:
        _print_manual_layers(plan_verification(["docs/internal/monorepo-layout.md"]), outstanding)
        assert ("are enough for this diff" in capsys.readouterr().out) is claims_enough


class TestVerifyCommand:
    def test_an_advisory_check_and_no_tests_leave_the_diff_unverified(self, repo: Path) -> None:
        no_tests = ChangedTests(directly_changed=set(), discovered=set(), skipped_playwright_specs=set())
        with (
            patch("hogli_commands.verify_layers.changed_files", return_value=["posthog/models/team/team.py"]),
            patch("hogli_commands.verify_layers._run_diff_check", return_value=("advisory", "run mypy")),
            patch("hogli_commands.verify_layers.changed_test_files", return_value=no_tests),
            patch("hogli_commands.verify_layers.subprocess") as verify_subprocess,
        ):
            result = CliRunner().invoke(verify, ["--changed"])

        assert result.exit_code == 0
        assert "[type-check] did not run: run mypy." in result.output
        assert "No tests were found for the changed files" in result.output
        assert "are enough for this diff" not in result.output
        verify_subprocess.run.assert_not_called()
        stamp = read_stamp()
        assert stamp is not None
        assert (stamp.outcome, stamp.highest_layer, stamp.layers["unit_test"]) == ("unverified", "static", "no_tests")

    def test_a_file_written_while_checks_run_leaves_the_stamp_stale(
        self, repo: Path, git: Callable[..., str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (repo / "team.py").write_text("a = 2\n")

        def write_unchecked_file_during_check(*args: object, **kwargs: object) -> tuple[str, str]:
            (repo / "never_checked.py").write_text("b = 1\n")
            return ("pass", "ok")

        with (
            patch("hogli_commands.verify_layers.changed_files", return_value=["team.py"]),
            patch("hogli_commands.verify_layers._run_diff_check", side_effect=write_unchecked_file_during_check),
            patch("hogli_commands.verify_layers.plan_verification") as plan,
        ):
            plan.return_value.runs_unit_tests = False
            plan.return_value.manual_layers = ()
            plan.return_value.files_by_kind = {}
            CliRunner().invoke(verify, ["--changed"])
        git(repo, "add", "-A")
        message_file = repo / "COMMIT_EDITMSG"
        message_file.write_text("feat: x")
        monkeypatch.setenv("HOGLI_VERIFY_GATE", "enforce")

        result = CliRunner().invoke(verify_gate, [str(message_file)])

        assert (result.exit_code, "blocked (stale)" in result.output) == (3, True)


class TestVerifyGate:
    @pytest.mark.parametrize(
        "mode,stamp_outcome,highest_layer,edited_after_verify,message,exit_code,output,tracked",
        [
            (
                "observe",
                "verified",
                "unit_test",
                False,
                "feat: x",
                0,
                "verified, highest layer unit_test",
                ("verified", None, None),
            ),
            ("observe", "verified", "unit_test", True, "feat: x", 0, "would block (stale)", ("stale", None, 1)),
            ("enforce", "verified", "unit_test", True, "feat: x", 3, "blocked (stale)", ("stale", None, 1)),
            ("enforce", "failed", "none", False, "feat: x", 3, "blocked (failed)", ("failed", None, None)),
            ("enforce", "failed", "static", False, "feat: x", 3, "blocked (failed)", ("failed", None, None)),
            (
                "enforce",
                "unverified",
                "static",
                False,
                "feat: x",
                3,
                "blocked (unverified)",
                ("unverified", None, None),
            ),
            (
                "observe",
                "unverified",
                "static",
                False,
                "feat: x",
                0,
                "would block (unverified)",
                ("unverified", None, None),
            ),
            (
                "enforce",
                "verified",
                "unit_test",
                True,
                "feat: x\n\nUnverified: generated file only",
                0,
                "",
                ("escaped", "generated", 1),
            ),
            (
                "enforce",
                "verified",
                "unit_test",
                True,
                "feat: x\n\nUnverified: ran it by hand",
                0,
                "",
                ("escaped", "other", 1),
            ),
            ("off", "failed", "none", True, "feat: x", 0, "", None),
        ],
    )
    def test_gate_matches_the_committed_content_against_the_stamp(
        self,
        repo: Path,
        git: Callable[..., str],
        monkeypatch: pytest.MonkeyPatch,
        mode: str,
        stamp_outcome: str,
        highest_layer: str,
        edited_after_verify: bool,
        message: str,
        exit_code: int,
        output: str,
        tracked: tuple[str, str | None, int | None] | None,
    ) -> None:
        (repo / "team.py").write_text("a = 2\n")
        (repo / "new_module.py").write_text("b = 1\n")
        write_stamp(
            snapshot=working_tree_snapshot(),
            outcome=stamp_outcome,
            highest_layer=highest_layer,
            sufficient_layer="unit_test",
            layers={},
            checks={},
        )
        assert git(repo, "status", "--porcelain").splitlines() == ["M team.py", "?? new_module.py"]
        if edited_after_verify:
            (repo / "team.py").write_text("a = 3\n")
        git(repo, "add", "-A")
        message_file = repo / "COMMIT_EDITMSG"
        message_file.write_text(message)
        monkeypatch.setenv("HOGLI_VERIFY_GATE", mode)
        events: list[dict[str, Any]] = []
        monkeypatch.setattr(verify_stamp.telemetry, "track", lambda _event, properties: events.append(properties))

        result = CliRunner().invoke(verify_gate, [str(message_file)])

        assert result.exit_code == exit_code
        assert output in result.output
        assert [
            (event["verify_gate_verdict"], event["verify_gate_escape_reason"], event["verify_stale_files"])
            for event in events
        ] == ([tracked] if tracked else [])

    @pytest.mark.parametrize(
        "mode,message,exit_code,output",
        [
            ("enforce", "feat: x", 3, "blocked (error)"),
            ("observe", "feat: x", 0, "would block (error)"),
            ("enforce", "feat: x\n\nUnverified: stamp tooling broken", 0, ""),
        ],
    )
    def test_an_unreadable_stamp_is_reported_instead_of_passing_silently(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch, mode: str, message: str, exit_code: int, output: str
    ) -> None:
        stamp_path().write_text("{truncated")
        message_file = repo / "COMMIT_EDITMSG"
        message_file.write_text(message)
        monkeypatch.setenv("HOGLI_VERIFY_GATE", mode)

        result = CliRunner().invoke(verify_gate, [str(message_file)])

        assert result.exit_code == exit_code
        assert output in result.output


def test_hashing_the_working_tree_writes_no_objects_to_the_repository(repo: Path, git: Callable[..., str]) -> None:
    (repo / "local_secrets.txt").write_text("token=not-a-real-token\n")
    blob_id = git(repo, "hash-object", "local_secrets.txt").strip()

    working_tree_content_hash()

    assert subprocess.run(["git", "-C", str(repo), "cat-file", "-e", blob_id]).returncode != 0
