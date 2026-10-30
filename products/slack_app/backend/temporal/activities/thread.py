from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.slack_app.backend.services.slack_messages import SlackThreadMessage
from products.slack_app.backend.services.workspace_integrations import require_workspace_integration
from products.slack_app.backend.temporal.types import PostHogCodeSlackMentionWorkflowInputs


@activity.defn
@close_db_connections
def collect_posthog_code_thread_messages_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
) -> list[SlackThreadMessage]:
    from posthog.models.integration import SlackIntegration

    from products.slack_app.backend.services.slack_messages import collect_thread_messages

    integration = require_workspace_integration(inputs.integration_id, inputs.slack_team_id)
    slack = SlackIntegration(integration)
    auth_response = slack.client.auth_test()
    our_bot_id = auth_response.get("bot_id")
    # Uncached: the snapshot feeds the persisted task description (the foundational
    # `<slack_thread_context>` block the agent reads forever); a 10-second-stale read
    # would silently bake missing messages into permanent state.
    # A fork clips the thread at the message it came from; the mention path passes no
    # bound and reads the thread as it stands.
    return collect_thread_messages(
        slack, integration, channel, thread_ts, our_bot_id, until_ts=inputs.fork_source_message_ts
    )
