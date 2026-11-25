from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.temporal.activities.thread import collect_posthog_code_thread_messages_activity
from products.slack_app.backend.temporal.types import PostHogCodeSlackMentionWorkflowInputs


class TestCollectThreadMessagesActivity(TestCase):
    def test_a_forked_run_reads_the_seed_thread_it_answers_in(self):
        # The workflow drops a run whose thread reads empty, as a retracted prompt. A fork
        # must come back with the seed the bot posted, not with an empty list.
        org = Organization.objects.create(name="TestOrg")
        team = Team.objects.create(organization=org, name="TestTeam")
        integration = Integration.objects.create(team=team, kind="slack", integration_id="T_SLACK", config={})
        slack = MagicMock()
        slack.client.auth_test.return_value = {"bot_id": "B1"}
        slack.client.conversations_replies.return_value = {
            "messages": [{"ts": "999.1", "user": "UBOT1", "bot_id": "B1", "text": "give me a joke please"}]
        }
        inputs = PostHogCodeSlackMentionWorkflowInputs(
            event={"type": "message", "channel": "D_ALICE", "ts": "999.1", "thread_ts": "999.1", "user": "U_ALICE"},
            integration_id=integration.id,
            slack_team_id="T_SLACK",
            user_id=1,
            fork_source_channel="C_SOURCE",
            fork_source_thread_ts="111.1",
            fork_source_message_ts="111.2",
        )

        with (
            patch("posthog.models.integration.SlackIntegration", return_value=slack),
            patch(
                "products.slack_app.backend.services.slack_messages.get_slack_user_info",
                return_value={"user": {"profile": {"display_name": "PostHog"}}},
            ),
        ):
            messages = collect_posthog_code_thread_messages_activity(inputs, "D_ALICE", "999.1")

        assert slack.client.conversations_replies.call_args.kwargs["channel"] == "D_ALICE"
        assert [(message.ts, message.user) for message in messages] == [("999.1", "PostHog")]
