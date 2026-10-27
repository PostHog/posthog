from __future__ import annotations

import pytest
from unittest.mock import patch

from click.testing import CliRunner
from hogli_commands.test_runner import ChangedTests
from hogli_commands.verify_layers import (
    ChangeKind,
    ComplexityLayer,
    _print_manual_layers,
    classify,
    plan_verification,
    verify,
)


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
    def test_an_advisory_check_and_no_tests_leave_the_diff_unverified(self) -> None:
        no_tests = ChangedTests(directly_changed=set(), discovered=set(), skipped_playwright_specs=set())
        with (
            patch("hogli_commands.verify_layers.changed_files", return_value=["posthog/models/team/team.py"]),
            patch("hogli_commands.verify_layers._run_diff_check", return_value=("advisory", "run mypy")),
            patch("hogli_commands.verify_layers.changed_test_files", return_value=no_tests),
            patch("hogli_commands.verify_layers.subprocess.run") as run,
        ):
            result = CliRunner().invoke(verify, ["--changed"])

        assert result.exit_code == 0
        assert "[type-check] did not run: run mypy." in result.output
        assert "No tests were found for the changed files" in result.output
        assert "are enough for this diff" not in result.output
        run.assert_not_called()
