from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command

from posthog.temporal.mcp_analytics.intent_topics.models import IntentTopicsRunResult, IntentTopicsWorkflowResult


class TestRunMCPIntentTopicsCommand(APIBaseTest):
    def test_asks_temporal_for_the_typed_result_and_prints_each_run(self) -> None:
        result = IntentTopicsWorkflowResult(
            team_id=self.team.pk,
            kind="sync",
            runs=[IntentTopicsRunResult(team_id=self.team.pk, kind="sync", status="succeeded", run_id="sync-1")],
        )
        client = MagicMock()
        client.execute_workflow = AsyncMock(return_value=result)

        with patch(
            "products.mcp_analytics.backend.management.commands.run_mcp_intent_topics.async_connect",
            AsyncMock(return_value=client),
        ):
            call_command("run_mcp_intent_topics", team_id=self.team.pk, kind="sync")

        assert client.execute_workflow.call_args.kwargs["result_type"] is IntentTopicsWorkflowResult
