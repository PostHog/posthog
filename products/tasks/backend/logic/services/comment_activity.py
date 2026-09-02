from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q

import structlog

from posthog.models import Comment

from products.tasks.backend.models import Channel, Task, TaskArtifact, TaskCommentActivity, TaskRun
from products.tasks.backend.visibility import task_visibility_q

logger = structlog.get_logger(__name__)

COMMENT_ACTIVITY_SCOPES = frozenset({"task", "task_artifact", "desktop_canvas"})


def _visible_tasks(team_id: int, user_id: int | None):
    return Task.objects.filter(team_id=team_id, deleted=False).filter(task_visibility_q(user_id))


def target_is_accessible(
    *, team_id: int, user_id: int | None, task_id: str | UUID, scope: str, item_id: str | None
) -> bool:
    try:
        parsed_task_id = UUID(str(task_id))
    except ValueError:
        return False

    task = _visible_tasks(team_id, user_id).filter(id=parsed_task_id).first()
    if task is None or not item_id or scope not in COMMENT_ACTIVITY_SCOPES:
        return False
    if scope == "task":
        return str(task.id) == str(item_id)
    if scope != "task_artifact":
        return False

    try:
        if TaskArtifact.objects.for_team(team_id).filter(task_id=task.id, id=item_id).exists():
            return True
    except (ValueError, DjangoValidationError):
        pass
    return TaskRun.objects.filter(
        team_id=team_id,
        task_id=task.id,
        artifacts__contains=[{"id": item_id}],
    ).exists()


def _notification_tasks(team_id: int):
    return _visible_tasks(team_id, None).exclude(channel__channel_type=Channel.ChannelType.PERSONAL)


def notifications_allowed(*, team_id: int, task_id: str | UUID) -> bool:
    try:
        parsed_task_id = UUID(str(task_id))
    except ValueError:
        return False
    return _notification_tasks(team_id).filter(id=parsed_task_id).exists()


def comment_task_id(comment: Comment) -> UUID | None:
    if comment.scope not in COMMENT_ACTIVITY_SCOPES:
        return None
    raw_task_id = comment.item_id if comment.scope == "task" else (comment.item_context or {}).get("taskId")
    if not isinstance(raw_task_id, str):
        return None
    try:
        return UUID(raw_task_id)
    except ValueError:
        return None


def project_comment_activity(
    *,
    team_id: int,
    comment_id: UUID,
    mentioned_user_ids: Sequence[int],
    include_relationship_recipients: bool,
    target_owner_id: int | None,
    activity_at: datetime | None,
) -> None:
    comment = Comment.objects.filter(team_id=team_id, id=comment_id).first()
    if comment is None or comment.created_by_id is None:
        return
    task_id = comment_task_id(comment)
    if task_id is None:
        return
    task = _notification_tasks(team_id).filter(id=task_id).only("created_by_id").first()
    if task is None:
        return

    root_comment_id = comment.source_comment_id or comment.id
    recipients: dict[int, str] = {}
    if include_relationship_recipients:
        if comment.source_comment_id:
            participant_ids = (
                Comment.objects.filter(team_id=team_id, deleted=False)
                .filter(Q(id=root_comment_id) | Q(source_comment_id=root_comment_id))
                .values_list("created_by_id", flat=True)
            )
            recipients.update(
                (participant_id, TaskCommentActivity.Kind.THREAD_REPLY)
                for participant_id in participant_ids
                if participant_id
            )
        else:
            owner_id = target_owner_id
            if owner_id is None and comment.scope == "task_artifact":
                try:
                    owner_id = (
                        TaskArtifact.objects.for_team(team_id)
                        .filter(task_id=task_id, id=comment.item_id)
                        .values_list("created_by_id", flat=True)
                        .first()
                    )
                except (ValueError, DjangoValidationError):
                    pass
            owner_id = owner_id or task.created_by_id
            if owner_id:
                recipients[owner_id] = TaskCommentActivity.Kind.OWNED_ITEM_COMMENT

    recipients.update((user_id, TaskCommentActivity.Kind.MENTION) for user_id in mentioned_user_ids)
    recipients.pop(comment.created_by_id, None)
    TaskCommentActivity.record_many(
        team_id=team_id,
        task_id=task_id,
        activity_at=activity_at or comment.created_at,
        comment_id=comment_id,
        root_comment_id=root_comment_id,
        recipients=recipients,
    )
    _enqueue_slack_dms(team_id=team_id, comment_id=comment_id, task_id=task_id, recipients=recipients)


def _enqueue_slack_dms(*, team_id: int, comment_id: UUID, task_id: UUID, recipients: dict[int, str]) -> None:
    """Hand the same recipient map to the Slack DM channel. Never fails the projection: the
    Activity row is the notification that has to land."""
    if not recipients:
        return

    def _enqueue() -> None:
        try:
            from products.tasks.backend.tasks.tasks import (  # noqa: PLC0415 — avoids the service/task circular import
                deliver_comment_slack_dms,
            )

            deliver_comment_slack_dms.delay(
                team_id=team_id,
                comment_id=str(comment_id),
                task_id=str(task_id),
                recipients={str(user_id): kind for user_id, kind in recipients.items()},
            )
        except Exception:
            logger.exception("comment_slack_dm_enqueue_failed", comment_id=str(comment_id))

    # The worker re-reads the comment, so it must not start before the write is visible.
    transaction.on_commit(_enqueue)
