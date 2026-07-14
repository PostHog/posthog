import re
from io import StringIO

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command

from posthog.models.scoping import team_scope

from products.pulse.backend.management.commands.pulse_measure_recall import MissedSignals
from products.pulse.backend.models import ProductBrief

LLM_PATH = "products.pulse.backend.management.commands.pulse_measure_recall.MaxChatOpenAI"


def _brief(team, sections: list[dict[str, str]], **kwargs) -> ProductBrief:
    with team_scope(team.pk, canonical=True):
        return ProductBrief.objects.create(
            team=team,
            status=ProductBrief.Status.READY,
            trigger=ProductBrief.Trigger.SCHEDULED,
            sections=sections,
            **kwargs,
        )


def _mock_llm(judged: MissedSignals) -> MagicMock:
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = judged
    return llm


class TestPulseMeasureRecall(APIBaseTest):
    def test_prints_aggregate_miss_rate(self) -> None:
        _brief(
            self.team,
            sections=[{"kind": "what_happened", "title": "Signup drop", "markdown": "Signups fell 20%."}],
            created_by=self.user,
        )
        _brief(
            self.team,
            sections=[{"kind": "what_happened", "title": "Thin", "markdown": "Nothing much."}],
            created_by=self.user,
        )

        judged = MissedSignals(expected=["signup drop", "onboarding funnel"], missing=["onboarding funnel"])
        with patch(LLM_PATH, return_value=_mock_llm(judged)):
            out = StringIO()
            call_command("pulse_measure_recall", "--team-id", str(self.team.id), stdout=out)

        output = out.getvalue()
        match = re.search(r"miss_rate=([\d.]+)", output)
        assert match is not None
        assert float(match.group(1)) == 1.0

    def test_skips_briefs_without_sections(self) -> None:
        _brief(self.team, sections=[])

        with patch(LLM_PATH) as mock_llm_cls:
            out = StringIO()
            call_command("pulse_measure_recall", "--team-id", str(self.team.id), stdout=out)

        mock_llm_cls.assert_not_called()
        output = out.getvalue()
        match = re.search(r"miss_rate=([\d.]+)", output)
        assert match is not None
        assert "sampled=0" in output
