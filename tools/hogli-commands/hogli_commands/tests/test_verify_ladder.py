from __future__ import annotations

import pytest

from hogli_commands.verify_ladder import ChangeKind, Rung, classify, plan_ladder


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
            ("posthog/models/team/team.py", ChangeKind.PURE_LOGIC),
        ],
    )
    def test_kind(self, path: str, expected_kind: ChangeKind) -> None:
        assert classify(path).kind == expected_kind


class TestPlanLadder:
    @pytest.mark.parametrize(
        "paths,runs_unit_tests,rungs_by_hand",
        [
            (["docs/internal/monorepo-layout.md", ".github/workflows/ci-backend.yml"], False, ()),
            (["posthog/models/team/team.py", "posthog/api/test/test_team.py"], True, ()),
            (
                ["frontend/src/scenes/insights/Insight.tsx", "posthog/api/insight.py", "posthog/settings/web.py"],
                True,
                (Rung.OPENAPI, Rung.STORYBOOK, Rung.STACK),
            ),
        ],
    )
    def test_rungs(self, paths: list[str], runs_unit_tests: bool, rungs_by_hand: tuple[Rung, ...]) -> None:
        plan = plan_ladder(paths)
        assert plan.runs_unit_tests is runs_unit_tests
        assert plan.rungs_by_hand == rungs_by_hand
