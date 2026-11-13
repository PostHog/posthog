import re
from enum import StrEnum
from typing import TYPE_CHECKING

from django.db import transaction

from posthog.dataclasses import frozen

from products.slack_app.backend.models import SlackThreadJoin, SlackThreadTaskMapping
from products.tasks.backend.facade import api as tasks_facade

if TYPE_CHECKING:
    from posthog.models.user import User

_HANDOVER_COMMAND = re.compile(
    r"^\s*(?:<@\w+>\s*)?hand\s*over\s+to\s+<@(\w+)(?:\|[^>]*)?>\s*[.!]?\s*$",
    re.IGNORECASE,
)


class HandoverOutcome(StrEnum):
    HANDED_OVER = "handed_over"
    NOT_OWNER = "not_owner"
    ALREADY_OWNER = "already_owner"
    NO_PROJECT_ACCESS = "no_project_access"
    NO_GITHUB = "no_github"
    REFUSED = "refused"


@frozen
class SlackTaskHandover:
    outcome: HandoverOutcome
    reply: str


def parse_handover_target(text: str) -> str | None:
    match = _HANDOVER_COMMAND.match(text or "")
    return match.group(1) if match else None


def hand_over_slack_task(
    mapping: SlackThreadTaskMapping,
    *,
    sender_slack_user_id: str,
    target_slack_user_id: str,
    target_user: "User | None",
) -> SlackTaskHandover:
    owner_slack_user_id = mapping.mentioning_slack_user_id
    if sender_slack_user_id != owner_slack_user_id:
        return SlackTaskHandover(
            outcome=HandoverOutcome.NOT_OWNER,
            reply=f"Only <@{owner_slack_user_id}> can hand over this task, because they own it.",
        )
    if target_slack_user_id == owner_slack_user_id:
        return SlackTaskHandover(outcome=HandoverOutcome.ALREADY_OWNER, reply="You already own this task.")
    if target_user is None:
        return SlackTaskHandover(
            outcome=HandoverOutcome.NO_PROJECT_ACCESS,
            reply=(
                f"I can't hand over this task, because <@{target_slack_user_id}> has no access to this "
                "PostHog project. You still own it."
            ),
        )
    if mapping.task.repository and not tasks_facade.user_has_usable_personal_github(target_user.id):
        return SlackTaskHandover(
            outcome=HandoverOutcome.NO_GITHUB,
            reply=(
                f"I can't hand over this task yet. <@{target_slack_user_id}> must connect GitHub to PostHog first. "
                "You still own it."
            ),
        )
    try:
        handed_over = tasks_facade.handoff_task(
            mapping.task_id, mapping.team_id, mapping.task.created_by_id, target_user_id=target_user.id
        )
    except tasks_facade.TaskHandoffError as exc:
        return SlackTaskHandover(
            outcome=HandoverOutcome.REFUSED, reply=f"I can't hand over this task. {exc} You still own it."
        )
    if handed_over is None:
        return SlackTaskHandover(
            outcome=HandoverOutcome.REFUSED, reply="I can't hand over this task. You still own it."
        )

    with transaction.atomic():
        SlackThreadTaskMapping.objects.filter(id=mapping.id).update(
            mentioning_slack_user_id=target_slack_user_id,
            latest_actor_slack_user_id=target_slack_user_id,
        )
        SlackThreadJoin.objects.for_team(mapping.team_id).filter(thread_mapping_id=mapping.id).delete()
    return SlackTaskHandover(
        outcome=HandoverOutcome.HANDED_OVER,
        reply=(
            f"<@{target_slack_user_id}> You own this task now, so I use your GitHub account for it. "
            f"<@{owner_slack_user_id}> can still help in this thread."
        ),
    )
