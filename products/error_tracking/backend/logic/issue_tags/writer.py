from datetime import timedelta
from functools import partial
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.user import User

from products.error_tracking.backend.logic.issue_tags.gate import issue_tags_enabled
from products.error_tracking.backend.logic.issue_tags.registry import get_issue_tag_definition
from products.error_tracking.backend.logic.issue_tags.sync import sync_issue_tag_to_clickhouse
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagAnswer
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag


def set_issue_tag(
    team_id: int, issue_id: UUID | str, key: str, answer: TagAnswer, source: ErrorTrackingIssueTag.Source
) -> bool:
    """Store the answer unless issue tags are off for the team, or a higher-ranked source answered the tag already.

    Return whether it was stored.
    """
    if not issue_tags_enabled(team_id):
        return False
    sources_above = get_issue_tag_definition(key).sources_ranked_above(source)
    issue = ErrorTrackingIssue.objects.select_related("team").get(team_id=team_id, id=issue_id)
    tags = ErrorTrackingIssueTag.objects.for_team(issue.team.parent_team_id or issue.team_id, canonical=True)
    fields = {
        "source": source,
        "value": answer.value,
        "probability": answer.probability,
        "model": answer.model,
        "question_version": answer.question_version,
        "set_by": answer.set_by,
    }
    after: dict[str, object] = {"key": key, "value": answer.value, "source": source}

    with transaction.atomic():
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
            before = {"key": key, "value": tag.value, "source": tag.source}
            # Pods do not share one clock, so a later write can read an earlier time. Each write to the
            # locked row moves updated_at forward, which keeps the ClickHouse versions of a tag in commit order.
            updated_at = max(timezone.now(), tag.updated_at + timedelta(microseconds=1))
            tags.filter(pk=tag.pk).update(**fields, updated_at=updated_at)
        if before != after:
            _log_tag_change(issue, answer.set_by, before, after)
        transaction.on_commit(
            partial(
                sync_issue_tag_to_clickhouse,
                team_id=issue.team_id,
                issue_id=issue.id,
                key=key,
                value=answer.value,
                updated_at=updated_at,
            ),
            # The tag is already stored when this runs, so a failed produce must not fail the caller.
            robust=True,
        )
    return True


def _log_tag_change(
    issue: ErrorTrackingIssue, user: User | None, before: dict[str, object] | None, after: dict[str, object]
) -> None:
    log_activity(
        organization_id=issue.team.organization_id,
        team_id=issue.team_id,
        user=user,
        was_impersonated=False,
        item_id=str(issue.id),
        scope="ErrorTrackingIssue",
        activity="updated",
        strict=True,
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
