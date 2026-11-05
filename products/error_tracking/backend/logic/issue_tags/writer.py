from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity

from products.error_tracking.backend.logic.issue_tags.registry import get_issue_tag_definition
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagAnswer
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag


def set_issue_tag(
    team_id: int, issue_id: UUID | str, key: str, answer: TagAnswer, source: ErrorTrackingIssueTag.Source
) -> bool:
    """Store the answer unless a higher-ranked source answered the tag already. Return whether it was stored."""
    sources_by_rank = get_issue_tag_definition(key).sources_by_rank()
    if source not in sources_by_rank:
        raise ValueError(f"{source} does not answer the issue tag {key!r}")
    replaceable_sources = sources_by_rank[sources_by_rank.index(source) :]

    issue = ErrorTrackingIssue.objects.select_related("team").get(team_id=team_id, id=issue_id)
    tag = ErrorTrackingIssueTag.objects.for_team(team_id).filter(issue=issue, key=key)
    fields = {
        "source": source,
        "value": answer.value,
        "probability": answer.probability,
        "model": answer.model,
        "question_version": answer.question_version,
        "set_by": answer.set_by,
    }

    with transaction.atomic():
        previous = tag.only("value", "source").first()
        stored = False
        if previous is None:
            try:
                with transaction.atomic():
                    ErrorTrackingIssueTag(team=issue.team, issue=issue, key=key, **fields).save(force_insert=True)
                stored = True
            except IntegrityError:
                # Another writer inserted this tag after the read, so rank against its answer instead.
                previous = tag.only("value", "source").first()
        if not stored:
            # The source condition is re-checked against the latest row, so a concurrent write from a
            # higher-ranked source is never replaced.
            stored = tag.filter(source__in=replaceable_sources).update(**fields, updated_at=timezone.now()) > 0
        if stored and (previous is None or previous.value != answer.value or previous.source != source):
            _log_tag_change(issue, key, previous, answer, source)
    return stored


def _log_tag_change(
    issue: ErrorTrackingIssue,
    key: str,
    previous: ErrorTrackingIssueTag | None,
    answer: TagAnswer,
    source: ErrorTrackingIssueTag.Source,
) -> None:
    log_activity(
        organization_id=issue.team.organization_id,
        team_id=issue.team_id,
        user=answer.set_by,
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
                    action="created" if previous is None else "changed",
                    before=None
                    if previous is None
                    else {"key": key, "value": previous.value, "source": previous.source},
                    after={"key": key, "value": answer.value, "source": source},
                )
            ],
        ),
    )
