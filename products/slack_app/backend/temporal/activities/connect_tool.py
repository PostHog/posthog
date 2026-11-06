from temporalio import activity

from products.slack_app.backend.temporal.types import PostHogCodeSlackMentionWorkflowInputs


@activity.defn
def offer_slack_app_tool_connections_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    user_id: int,
    workflow_id: str,
) -> bool:
    from products.slack_app.backend.logic.connect_tool import offer_tool_connections
    from products.slack_app.backend.services.workspace_integrations import get_workspace_integration

    integration = get_workspace_integration(inputs.integration_id, inputs.slack_team_id)
    if integration is None:
        return False
    return offer_tool_connections(
        integration,
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
        user_id=user_id,
        text=str(inputs.event.get("text") or ""),
        workflow_id=workflow_id,
    )
