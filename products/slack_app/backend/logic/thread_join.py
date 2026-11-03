"""Whether someone other than the thread creator may send messages to the thread's task."""

from enum import StrEnum
from typing import TYPE_CHECKING

from products.slack_app.backend.models import SlackThreadJoin, ThreadJoinMode
from products.slack_app.backend.services.slack_settings import resolve_thread_join_mode
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

if TYPE_CHECKING:
    from products.slack_app.backend.models import SlackThreadTaskMapping


class ThreadJoinDecision(StrEnum):
    ALLOW = "allow"
    # Ask the creator, and let only this person join.
    ASK_FOR_PERSON = "ask_for_person"
    # Ask the creator, and let anyone join the thread once they approve.
    ASK_FOR_THREAD = "ask_for_thread"
    DENY = "deny"


def decide_thread_join(
    integration: "WorkspaceIntegration", mapping: "SlackThreadTaskMapping", slack_user_id: str
) -> ThreadJoinDecision:
    """The creator's join mode applied to one person, given the approvals the thread already has.

    A person's approval holds whatever the mode is now, because a mode change applies to new
    people only.
    """
    from products.tasks.backend.facade import api as tasks_facade

    mode = resolve_thread_join_mode(
        integration,
        mapping.mentioning_slack_user_id,
        own_subscription=tasks_facade.uses_own_subscription(mapping.task_run.state),
    )
    if mode == ThreadJoinMode.ALLOW:
        return ThreadJoinDecision.ALLOW
    approved = set(
        SlackThreadJoin.objects.for_team(mapping.team_id)
        .filter(thread_mapping_id=mapping.id)
        .values_list("slack_user_id", flat=True)
    )
    if slack_user_id in approved or (mode == ThreadJoinMode.ASK_PER_THREAD and approved):
        return ThreadJoinDecision.ALLOW
    if mode == ThreadJoinMode.ASK_PER_PERSON:
        return ThreadJoinDecision.ASK_FOR_PERSON
    if mode == ThreadJoinMode.ASK_PER_THREAD:
        return ThreadJoinDecision.ASK_FOR_THREAD
    return ThreadJoinDecision.DENY
