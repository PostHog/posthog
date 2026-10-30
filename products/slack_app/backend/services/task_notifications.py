from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.models import SlackThreadTaskMapping


def task_slack_notifications_muted(
    *, integration_id: int, channel: str, thread_ts: str, slack_user_id: str | None, private_only: bool = False
) -> bool:
    if not slack_user_id and not private_only:
        return False
    mappings = SlackThreadTaskMapping.objects.filter(
        integration_id=integration_id, channel=channel, thread_ts=thread_ts
    )
    if private_only:
        mappings = mappings.filter(conversation_type=SlackThreadTaskMapping.ConversationType.IM)
    mapping = mappings.first()
    if mapping is None:
        return False
    slack_user_id = slack_user_id or mapping.mentioning_slack_user_id

    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415 — keeps tasks off Slack startup

    user_ids = set(
        UserIntegration.objects.filter(
            kind=UserIntegration.IntegrationKind.SLACK,
            integration_id=slack_user_id,
            config__slack_team_id=mapping.slack_workspace_id,
        ).values_list("user_id", flat=True)
    )
    run = tasks_facade.get_task_run(mapping.task_run_id, team_id=mapping.team_id)
    if run is not None:
        actor_id = run.state.get("slack_actor_user_id")
        if run.state.get("slack_actor_slack_user_id") == slack_user_id and type(actor_id) is int:
            user_ids.add(actor_id)
        elif mapping.mentioning_slack_user_id == slack_user_id and run.created_by_id is not None:
            user_ids.add(run.created_by_id)
    return any(
        tasks_facade.task_mobile_push_taken_over(task_id=str(mapping.task_id), team_id=mapping.team_id, user_id=user_id)
        for user_id in user_ids
    )
