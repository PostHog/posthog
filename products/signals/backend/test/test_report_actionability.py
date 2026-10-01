from collections.abc import Callable
from datetime import UTC, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.report_actionability import ACTIONABILITY_CRITERIA
from products.signals.backend.report_generation.research import build_actionability_prompt
from products.signals.backend.scout_harness.prompt import build_run_prompt
from products.signals.backend.scout_harness.skill_loader import LoadedSkill


def _scout_prompt(allowed_tools: list[str]) -> Callable[[], str]:
    def build() -> str:
        return build_run_prompt(
            LoadedSkill(
                name="signals-scout-errors",
                version=1,
                body="watch",
                description="d",
                allowed_tools=allowed_tools,
                files=[],
                skill_id="skill-1",
                origin="canonical",
                authors=[],
            ),
            run_id="00000000-0000-0000-0000-000000000abc",
            team_id=1,
            started_at=datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC),
        )

    return build


class TestActionabilityCriteriaReachEveryJudge(SimpleTestCase):
    @parameterized.expand(
        [
            ("pipeline_research_agent", lambda: build_actionability_prompt(3)),
            ("scout_author", _scout_prompt(["emit_report"])),
            ("scout_author_and_editor", _scout_prompt(["emit_report", "edit_report"])),
        ]
    )
    def test_prompt_renders_the_shared_criteria(self, _name: str, build: Callable[[], str]) -> None:
        # A report-channel scout makes the actionability call on the report it authored, and the
        # pipeline's research agent makes it on a clustered one. The choice gates autostart the same
        # way on both paths, so a surface that states criteria of its own parks in PENDING_INPUT the
        # work the other path would have opened a draft PR for.
        assert ACTIONABILITY_CRITERIA in build()
