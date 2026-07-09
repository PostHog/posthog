from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models.scoping import team_scope

from products.pulse.backend.generation.schemas import BriefOut
from products.pulse.backend.models import ProductBrief


class TestEvalEngines(BaseTest):
    def test_renders_agent_brief_next_to_baseline(self):
        with team_scope(self.team.pk, canonical=True):
            brief = ProductBrief.objects.create(
                team=self.team,
                created_by=self.user,
                trigger=ProductBrief.Trigger.ON_DEMAND,
                status=ProductBrief.Status.READY,
                sections=[
                    {
                        "kind": "what_happened",
                        "title": "Agent section",
                        "markdown": "x",
                        "citations": [],
                        "confidence": 0.9,
                    }
                ],
                agent_session_ref="sb-1",
            )
        out = StringIO()
        with (
            patch("products.pulse.backend.management.commands.pulse_eval_engines.get_sources", return_value=[]),
            patch(
                "products.pulse.backend.management.commands.pulse_eval_engines.synthesize_brief",
                new_callable=AsyncMock,
                return_value=BriefOut(sections=[], opportunities=[]),
            ),
        ):
            call_command("pulse_eval_engines", f"--brief-id={brief.id}", f"--team-id={self.team.pk}", stdout=out)
        rendered = out.getvalue()
        assert "Agent section" in rendered
        assert "BASELINE" in rendered and "AGENT" in rendered

    def test_refuses_synthesize_engine_briefs(self):
        with team_scope(self.team.pk, canonical=True):
            brief = ProductBrief.objects.create(
                team=self.team, created_by=self.user, trigger=ProductBrief.Trigger.ON_DEMAND
            )
        with self.assertRaisesRegex(CommandError, "not written by the agent engine"):
            call_command("pulse_eval_engines", f"--brief-id={brief.id}", f"--team-id={self.team.pk}")
