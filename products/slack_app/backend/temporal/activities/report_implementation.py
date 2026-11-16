from django.core.cache import cache
from django.db import transaction

from temporalio import activity

from posthog.models.integration import SlackIntegration
from posthog.models.user import User
from posthog.temporal.common.utils import close_db_connections

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.slack_app.backend.logic.reply_suggestions import REPORT_IMPLEMENTATION_ACTION_ID
from products.slack_app.backend.logic.thread_join import ThreadJoinDecision, decide_thread_join
from products.slack_app.backend.models import SlackThreadTaskMapping
from products.slack_app.backend.services.slack_messages import post_slack_thread_reply
from products.slack_app.backend.services.workspace_integrations import require_workspace_integration
from products.slack_app.backend.temporal.types import PostHogCodeSlackMentionWorkflowInputs


@activity.defn
@close_db_connections
def prepare_slack_report_implementation_activity(inputs: PostHogCodeSlackMentionWorkflowInputs) -> bool:
    from products.signals.backend.facade import (  # noqa: PLC0415 - keeps the signals model graph off the webhook import path
        api as signals_facade,
        report_tasks,
    )
    from products.tasks.backend.facade import api as tasks_facade

    integration = require_workspace_integration(inputs.integration_id, inputs.slack_team_id)
    user = User.objects.get(id=inputs.user_id, is_active=True)
    access = UserAccessControl(user, team=integration.team)
    if not access.has_project_access or not access.check_access_level_for_resource("task", "editor"):
        return False
    channel = inputs.event["channel"]
    thread_ts = inputs.event.get("thread_ts") or inputs.event["ts"]
    report_id = signals_facade.report_id_for_slack_thread(
        team_id=integration.team_id, slack_workspace_id=inputs.slack_team_id, channel=channel, thread_ts=thread_ts
    )
    if report_id is None:
        return False
    mapping = SlackThreadTaskMapping.objects.filter(
        integration_id=integration.id, channel=channel, thread_ts=thread_ts
    ).first()
    if mapping is not None:
        slack_user_id = inputs.event["user"]
        if slack_user_id != mapping.mentioning_slack_user_id:
            join = decide_thread_join(integration, mapping, slack_user_id)
            if join != ThreadJoinDecision.ALLOW:
                if join != ThreadJoinDecision.DENY:
                    from products.slack_app.backend.api import post_thread_join_prompt  # noqa: PLC0415

                    post_thread_join_prompt(
                        SlackIntegration(integration),
                        integration,
                        inputs,
                        channel=channel,
                        thread_ts=thread_ts,
                        owner_slack_user_id=mapping.mentioning_slack_user_id,
                        joiner_slack_user_id=slack_user_id,
                        opens_thread=join == ThreadJoinDecision.ASK_FOR_THREAD,
                        plan_name=plan.plan_name
                        if (plan := tasks_facade.get_run_plan(mapping.task_run.state))
                        else None,
                    )
                return False
        try:
            with transaction.atomic():
                tasks_facade.mark_slack_task_manual_billing(team_id=integration.team_id, task_id=str(mapping.task_id))
                if not report_tasks.is_report_implementation_task(
                    team_id=integration.team_id, report_id=report_id, task_id=str(mapping.task_id)
                ):
                    report_tasks.enforce_report_task_cap(
                        team_id=integration.team_id,
                        report_id=report_id,
                        relationship=None,
                        created_by_id=inputs.user_id,
                    )
                    report_tasks.record_report_task(
                        team_id=integration.team_id, report_id=report_id, task_id=str(mapping.task_id)
                    )
        except report_tasks.ReportTaskCapExceeded as exc:
            post_slack_thread_reply(
                SlackIntegration(integration).client, channel=channel, thread_ts=thread_ts, text=exc.detail
            )
            return False
    return True


@activity.defn
@close_db_connections
def finish_slack_report_implementation_activity(inputs: PostHogCodeSlackMentionWorkflowInputs, started: bool) -> None:
    channel = inputs.event["channel"]
    message_ts = inputs.report_implementation_message_ts
    if message_ts is None:
        return
    claim_key = f"slack_app_reply_suggestion_claim:{inputs.integration_id}:{channel}:{message_ts}"
    if not started:
        cache.delete(claim_key)
        return
    integration = require_workspace_integration(inputs.integration_id, inputs.slack_team_id)
    client = SlackIntegration(integration).client
    response = client.conversations_replies(
        channel=channel, ts=message_ts, oldest=message_ts, latest=message_ts, inclusive=True, limit=1
    )
    message = next((m for m in response.get("messages") or [] if m.get("ts") == message_ts), None)
    if message is None:
        return
    blocks = []
    for block in message.get("blocks") or []:
        if block.get("type") == "actions":
            elements = [e for e in block.get("elements") or [] if e.get("action_id") != REPORT_IMPLEMENTATION_ACTION_ID]
            if elements:
                blocks.append({**block, "elements": elements})
        else:
            blocks.append(block)
    client.chat_update(channel=channel, ts=message_ts, text=message.get("text") or "", blocks=blocks)
