import contextlib

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from products.slack_app.backend.temporal.activities import repo_selection
from products.slack_app.backend.temporal.types import PostHogCodeSlackMentionWorkflowInputs
from products.tasks.backend.facade.repo_selection import RepoSelectionUsageLimitError


@pytest.mark.asyncio
async def test_usage_limited_selection_posts_the_credits_message_instead_of_a_picker() -> None:
    event = {"channel": "C1", "ts": "1.2", "thread_ts": "1.0", "user": "U1", "text": "fix the bug"}
    inputs = PostHogCodeSlackMentionWorkflowInputs(event=event, integration_id=1, slack_team_id="T1", user_id=42)
    integration = MagicMock(team_id=7)
    objects = MagicMock()
    objects.select_related.return_value.aget = AsyncMock(return_value=integration)

    with (
        patch("posthog.models.integration.Integration.objects", objects),
        patch("posthog.models.integration.SlackIntegration"),
        patch.object(repo_selection, "Heartbeater", return_value=contextlib.nullcontext()),
        patch(
            "products.tasks.backend.facade.repo_selection.select_repository",
            AsyncMock(side_effect=RepoSelectionUsageLimitError("API Error: 402 out of credits")),
        ),
        patch("products.slack_app.backend.api.post_quota_exhausted_denial") as denial,
    ):
        outcome = await repo_selection.discover_posthog_code_repository_via_agent_activity(inputs, "C1", event, [], 42)

    assert outcome.usage_limited is True
    assert outcome.repository is None
    assert denial.call_args.kwargs["thread_ts"] == "1.0"
    assert denial.call_args.kwargs["slack_user_id"] == "U1"
