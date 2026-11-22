from collections.abc import Mapping
from datetime import datetime, timedelta
from functools import partial
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.user import User

from products.error_tracking.backend.logic.issue_tags.gate import issue_tags_enabled
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition
from products.error_tracking.backend.logic.issue_tags.sync import sync_issue_tag_to_clickhouse
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagAnswer
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag


def set_issue_tag(
    team_id: int,
    issue_id: UUID | str,
    definition: IssueTagDefinition,
    answer: TagAnswer,
    source: ErrorTrackingIssueTag.Source,
    *,
    was_impersonated: bool = False,
) -> bool:
    """Store the answer unless issue tags are off for the team, or a higher-ranked source answered the tag already.

    Return whether it was stored. An answer that the tag already holds, field for field, writes nothing and counts as
    stored.
    """
    if not issue_tags_enabled(team_id):
        return False
    key = definition.key
    sources_above = definition.sources_ranked_above(source)
    fields = {
        "source": source,
        "value": answer.value,
        "probability": answer.probability,
        "model": answer.model,
        "question_version": answer.question_version,
        "set_by_id": answer.set_by.id if answer.set_by else None,
    }
    after: dict[str, object] = {"key": key, "value": answer.value, "source": source}

    with transaction.atomic():
        # A merge locks its issues and then their tags. This writer takes its locks in the same order, because in the
        # other order a first answer and a merge can each wait for a lock that the other holds, which is a deadlock.
        issue = (
            ErrorTrackingIssue.objects.select_for_update(no_key=True, of=("self",))
            .select_related("team")
            .get(team_id=team_id, id=issue_id)
        )
        tags = ErrorTrackingIssueTag.objects.for_team(issue.team.parent_team_id or issue.team_id, canonical=True)
        # The row lock makes a concurrent writer wait until this transaction commits, so the rank check and the
        # logged before value both see the answer that this write replaces.
        tag, created = tags.select_for_update().get_or_create(
            issue=issue, key=key, defaults={"team": issue.team, **fields}
        )
        before: dict[str, object] | None = None
        updated_at = tag.updated_at
        if not created:
            if tag.source in sources_above:
                return False
            if all(getattr(tag, name) == value for name, value in fields.items()):
                return True
            before, updated_at = _replace_tag(tags, tag, fields)
        # A rule answer tells whether the event matched a property that some members may not read, and every member
        # can read the activity log. So the log holds no rule answer, as a change or as the value a correction replaced.
        if before != after and source != ErrorTrackingIssueTag.Source.RULE:
            _log_tag_change(issue, answer.set_by, was_impersonated, before, after, strict=True)
        _sync_tag_on_commit(issue, key, answer.value, updated_at)
    return True


def carry_issue_tags_on_merge(target: ErrorTrackingIssue, source_issue_ids: list[UUID]) -> None:
    """Copy the labels applied on the source issues to the target, before the merge deletes the sources.

    The merge calls this inside its transaction, with the issues locked and the issue tags flag already checked.
    A removal is not carried, because it was a decision about the issue it was made on.
    """
    team = target.team
    tags = ErrorTrackingIssueTag.objects.for_team(team.parent_team_id or team.id, canonical=True)
    target_tags: dict[str, ErrorTrackingIssueTag] = {}
    carried: dict[str, ErrorTrackingIssueTag] = {}
    for tag in tags.select_for_update().filter(issue_id__in=[target.id, *source_issue_ids]).order_by("issue_id", "key"):
        if tag.issue_id == target.id:
            target_tags[tag.key] = tag
        elif tag.value is True and _carried_label_replaces(tag, carried.get(tag.key)):
            carried[tag.key] = tag

    for key, label in carried.items():
        current = target_tags.get(key)
        if not _carried_label_replaces(label, current):
            continue
        fields = {
            "source": label.source,
            "value": True,
            "probability": label.probability,
            "model": label.model,
            "question_version": label.question_version,
            "set_by_id": label.set_by_id,
        }
        before: dict[str, object] | None = None
        if current is None:
            updated_at = tags.create(team=team, issue=target, key=key, **fields).updated_at
        else:
            before, updated_at = _replace_tag(tags, current, fields)
        # The activity log holds no rule answer, for the reason in set_issue_tag.
        if label.source != ErrorTrackingIssueTag.Source.RULE:
            after: dict[str, object] = {"key": key, "value": True, "source": label.source}
            # strict=False defers the activity insert and its internal event until the merge releases its row locks.
            _log_tag_change(target, user=None, was_impersonated=False, before=before, after=after, strict=False)
        _sync_tag_on_commit(target, key, True, updated_at)


def _carried_label_replaces(label: ErrorTrackingIssueTag, current: ErrorTrackingIssueTag | None) -> bool:
    """Whether an applied label from a merged issue replaces `current`, the answer that it competes with.

    A person's answer ranks above every tagger, so it is never replaced, and it replaces any tagger's answer.
    Between two taggers an applied answer stays, because the label shows either way.
    """
    if current is None:
        return True
    if current.source == ErrorTrackingIssueTag.Source.MANUAL:
        return False
    return label.source == ErrorTrackingIssueTag.Source.MANUAL or current.value is not True


def _replace_tag(
    tags: QuerySet[ErrorTrackingIssueTag], tag: ErrorTrackingIssueTag, fields: Mapping[str, object]
) -> tuple[dict[str, object] | None, datetime]:
    """Overwrite the locked row with `fields`. Return the answer it held, for the activity log, and its new updated_at.

    The answer is None when a rule wrote it, because the activity log holds no rule answer.
    """
    # Pods do not share one clock, so a later write can read an earlier time. Each write to the
    # locked row moves updated_at forward, which keeps the ClickHouse versions of a tag in commit order.
    updated_at = max(timezone.now(), tag.updated_at + timedelta(microseconds=1))
    tags.filter(pk=tag.pk).update(**fields, updated_at=updated_at)
    if tag.source == ErrorTrackingIssueTag.Source.RULE:
        return None, updated_at
    return {"key": tag.key, "value": tag.value, "source": tag.source}, updated_at


def _sync_tag_on_commit(issue: ErrorTrackingIssue, key: str, value: bool | None, updated_at: datetime) -> None:
    transaction.on_commit(
        partial(
            sync_issue_tag_to_clickhouse,
            team_id=issue.team_id,
            issue_id=issue.id,
            key=key,
            value=value,
            updated_at=updated_at,
        ),
        # The tag is already stored when this runs, so a failed produce must not fail the caller.
        robust=True,
    )


def _log_tag_change(
    issue: ErrorTrackingIssue,
    user: User | None,
    was_impersonated: bool,
    before: dict[str, object] | None,
    after: dict[str, object],
    *,
    strict: bool,
) -> None:
    log_activity(
        organization_id=issue.team.organization_id,
        team_id=issue.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(issue.id),
        scope="ErrorTrackingIssue",
        activity="updated",
        strict=strict,
        detail=Detail(
            name=issue.name,
            changes=[
                Change(
                    type="ErrorTrackingIssue",
                    field="tag",
                    action="created" if before is None else "changed",
                    before=before,
                    after=after,
                )
            ],
        ),
    )
