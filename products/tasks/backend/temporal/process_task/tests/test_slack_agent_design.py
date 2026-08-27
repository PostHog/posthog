from typing import ClassVar

from unittest.mock import patch

from django.test import TestCase, override_settings

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.tasks.backend.temporal.process_task.activities.slack_agent_design import (
    StopSlackAgentDesignStreamInput,
    stop_slack_agent_design_stream,
)


@override_settings(SITE_URL="https://us.posthog.com")
class TestSlackAgentDesignStream(TestCase):
    org: ClassVar[Organization]
    team: ClassVar[Team]
    integration: ClassVar[Integration]

    @classmethod
    def setUpTestData(cls) -> None:
        cls.org = Organization.objects.create(name="TestOrg")
        cls.team = Team.objects.create(organization=cls.org, name="TestTeam")
        cls.integration = Integration.objects.create(team=cls.team, kind="slack", integration_id="T123", config={})

    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.footer_enabled", return_value=False)
    @patch("products.slack_app.backend.slack_thread.SlackThreadHandler.stop_status_stream")
    def test_streamed_final_answer_has_object_tags_rewritten(self, mock_stop, _mock_footer) -> None:
        stop_slack_agent_design_stream(
            StopSlackAgentDesignStreamInput(
                slack_thread_context={"integration_id": self.integration.id, "channel": "C1", "thread_ts": "1.0"},
                ts="2.0",
                final_markdown='The <insight id="9pQx3">checkout funnel</insight> dropped.',
            )
        )

        mock_stop.assert_called_once()
        final_markdown = mock_stop.call_args.kwargs["final_markdown"]
        assert final_markdown == (
            f"The [checkout funnel](https://us.posthog.com/project/{self.team.id}/insights/9pQx3?unfurl=false) dropped."
        )
