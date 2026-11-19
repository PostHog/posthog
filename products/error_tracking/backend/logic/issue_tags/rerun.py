import json
import time
import itertools
from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.dataclasses import frozen
from posthog.models import Team

from products.error_tracking.backend.logic.issue_tags.gate import issue_tags_enabled
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition, RuleTaggerConfig
from products.error_tracking.backend.logic.issue_tags.runner import (
    IssueTaggingSkipReason,
    TaggerRun,
    applicable_taggers,
    run_issue_taggers,
)
from products.error_tracking.backend.logic.issue_tags.taggers.base import Tagger
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag
from products.ml_inference.backend.facade.contracts import DecisionGatewayError, DecisionGatewayUnreachableError

logger = structlog.get_logger(__name__)

Source = ErrorTrackingIssueTag.Source

BATCH_SIZE = 100
# Cymbal creates an issue when it processes the issue's first event, so that event's timestamp is before created_at.
# The window starts a day earlier for a late event, and ends an hour later for clock skew between hosts.
FIRST_EVENT_LEAD = timedelta(days=1)
FIRST_EVENT_LAG = timedelta(hours=1)
# The retry policy of the issue-created tag activity: three attempts, with the waits between them.
RETRY_DELAYS = (timedelta(seconds=2), timedelta(seconds=4))

# The inner query finds each issue's first event from small columns. The outer query then reads `properties`, a large
# column, for those events only, so the other events of a busy issue cost no properties read.
_FIRST_EXCEPTION_EVENTS = """
    SELECT properties.$exception_issue_id, properties
    FROM events
    WHERE event = '$exception'
      AND timestamp >= {earliest} AND timestamp <= {latest}
      AND properties.$exception_issue_id IN {issue_ids}
      AND uuid IN (
          SELECT argMin(uuid, timestamp)
          FROM events
          WHERE event = '$exception'
            AND timestamp >= {earliest} AND timestamp <= {latest}
            AND properties.$exception_issue_id IN {issue_ids}
          GROUP BY properties.$exception_issue_id
      )
    LIMIT 1 BY properties.$exception_issue_id
    LIMIT {max_rows}
"""


@frozen
class IssueTaggerRerun:
    # The issues with a tag to re-run, up to the limit. A dry run counts them and runs nothing.
    selected: int
    ran: int
    # No first event in ClickHouse, or the issue merged away during the run.
    skipped: int
    # A tagger still failed after the retries.
    failed: int


@frozen
class _StaleIssue:
    id: UUID
    created_at: datetime
    taggers: tuple[Tagger, ...]
    keys: frozenset[str]


def rerun_issue_taggers(
    team_id: int,
    *,
    days: int,
    taggers: tuple[Tagger, ...],
    keys: Collection[str] | None,
    limit: int,
    dry_run: bool,
) -> IssueTaggerRerun | IssueTaggingSkipReason:
    """Re-run `taggers` on the team's active issues created in the last `days` days, newest first.

    A tagger runs on a tag where the issue has no row for the tag, or the tagger's own row has an old question
    version or model. A tagger that answers no writes no row, so it runs again on each re-run. The flag check comes
    first, so a team without issue tags reads no issue, rule or event.

    Raise ValueError for a key in `keys` that no tagger in `taggers` answers for the team.
    """
    if not issue_tags_enabled(team_id):
        return IssueTaggingSkipReason.DISABLED
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return IssueTaggingSkipReason.TEAM_MISSING
    applicable = applicable_taggers(team_id, taggers, keys)
    if keys is not None:
        unanswered = set(keys) - {definition.key for _, definitions in applicable for definition in definitions}
        if unanswered:
            raise ValueError(f"no selected tagger answers the issue tags {sorted(unanswered)} for team {team_id}")

    stale = _stale_issues(team, applicable, since=timezone.now() - timedelta(days=days), limit=limit)
    if dry_run:
        return IssueTaggerRerun(selected=len(stale), ran=0, skipped=0, failed=0)

    ran = skipped = failed = 0
    for batch in itertools.batched(stale, BATCH_SIZE, strict=False):
        events = _first_exception_events(team, batch)
        # One issue at a time, because Jev has a rate limit.
        for issue in batch:
            properties = events.get(issue.id)
            if properties is None:
                logger.info("error_tracking_issue_tagger_rerun_event_missing", team_id=team_id, issue_id=str(issue.id))
                skipped += 1
                continue
            result = _run_with_retries(team_id, issue, properties)
            if isinstance(result, IssueTaggingSkipReason):
                skipped += 1
            elif any(run.error is not None for run in result):
                _log_failures(team_id, issue, result)
                failed += 1
            else:
                ran += 1
    return IssueTaggerRerun(selected=len(stale), ran=ran, skipped=skipped, failed=failed)


def _needs_rerun(source: Source, definition: IssueTagDefinition, row: ErrorTrackingIssueTag | None) -> bool:
    """Whether the tagger `source` answers `definition` again on an issue whose stored answer is `row`.

    A Jev row is compared on its question version only. The gateway names the model in its answer, so the model is
    not known before the call.
    """
    if row is None:
        return True
    if row.source in definition.sources_ranked_above(source):
        return False
    if row.source != source:
        return True
    model = str(definition.tagger_config(RuleTaggerConfig).rule_id) if source == Source.RULE else None
    return row.question_version != definition.question_version or (model is not None and row.model != model)


def _stale_issues(
    team: Team,
    applicable: Sequence[tuple[Tagger, tuple[IssueTagDefinition, ...]]],
    *,
    since: datetime,
    limit: int,
) -> list[_StaleIssue]:
    keys = {definition.key for _, definitions in applicable for definition in definitions}
    if not keys:
        return []
    issues = (
        ErrorTrackingIssue.objects.filter(
            team_id=team.id, status=ErrorTrackingIssue.Status.ACTIVE, created_at__gte=since
        )
        .order_by("-created_at")
        .values_list("id", "created_at")
    )
    tags = ErrorTrackingIssueTag.objects.for_team(team.parent_team_id or team.id, canonical=True)
    stale: list[_StaleIssue] = []
    for batch in itertools.batched(issues.iterator(chunk_size=BATCH_SIZE), BATCH_SIZE, strict=False):
        rows = tags.filter(issue_id__in=[issue_id for issue_id, _ in batch], key__in=keys)
        stored = {
            (row.issue_id, row.key): row for row in rows.only("issue_id", "key", "source", "question_version", "model")
        }
        for issue_id, created_at in batch:
            reruns = [
                (tagger, definition)
                for tagger, definitions in applicable
                for definition in definitions
                if _needs_rerun(tagger.source, definition, stored.get((issue_id, definition.key)))
            ]
            if not reruns:
                continue
            stale.append(
                _StaleIssue(
                    id=issue_id,
                    created_at=created_at,
                    taggers=tuple(dict.fromkeys(tagger for tagger, _ in reruns)),
                    keys=frozenset(definition.key for _, definition in reruns),
                )
            )
            if len(stale) == limit:
                return stale
    return stale


def _first_exception_events(team: Team, issues: Sequence[_StaleIssue]) -> dict[UUID, dict[str, object]]:
    """The properties of each issue's earliest exception event, by issue id. An issue without one is left out."""
    response = execute_hogql_query(
        query=_FIRST_EXCEPTION_EVENTS,
        placeholders={
            "earliest": ast.Constant(value=min(issue.created_at for issue in issues) - FIRST_EVENT_LEAD),
            "latest": ast.Constant(value=max(issue.created_at for issue in issues) + FIRST_EVENT_LAG),
            "issue_ids": ast.Constant(value=[str(issue.id) for issue in issues]),
            "max_rows": ast.Constant(value=len(issues)),
        },
        team=team,
        query_type="ErrorTrackingIssueTaggerRerunEventProperties",
        # A staff backfill, so no person waits on screen for the result.
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.ERROR_TRACKING,
    )
    events: dict[UUID, dict[str, object]] = {}
    for issue_id, properties in response.results or []:
        if isinstance(properties, str):
            properties = json.loads(properties)
        if isinstance(properties, dict):
            events[UUID(issue_id)] = properties
    return events


def _run_with_retries(
    team_id: int, issue: _StaleIssue, properties: dict[str, object]
) -> tuple[TaggerRun, ...] | IssueTaggingSkipReason:
    result = _run(team_id, issue, properties)
    for delay in RETRY_DELAYS:
        if isinstance(result, IssueTaggingSkipReason) or not any(_model_unavailable(run.error) for run in result):
            break
        time.sleep(delay.total_seconds())
        result = _run(team_id, issue, properties)
    return result


def _run(
    team_id: int, issue: _StaleIssue, properties: dict[str, object]
) -> tuple[TaggerRun, ...] | IssueTaggingSkipReason:
    return run_issue_taggers(team_id, issue.id, lambda team: properties, taggers=issue.taggers, keys=issue.keys)


def _model_unavailable(error: Exception | None) -> bool:
    """Whether the error is a transient gateway failure that a retry can fix, as the issue-created activity counts it."""
    match error:
        case DecisionGatewayUnreachableError():
            return True
        case DecisionGatewayError(status_code=status_code):
            return status_code == 429 or status_code >= 500
    return False


def _log_failures(team_id: int, issue: _StaleIssue, runs: tuple[TaggerRun, ...]) -> None:
    for run in runs:
        if run.error is not None:
            logger.warning(
                "error_tracking_issue_tagger_rerun_failed",
                team_id=team_id,
                issue_id=str(issue.id),
                tagger=run.source,
                # The message can quote an event property value, so it stays out of the log.
                error_type=type(run.error).__name__,
            )
