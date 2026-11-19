import json
import time
from collections.abc import Collection, Iterator, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.dataclasses import frozen
from posthog.errors import CH_TRANSIENT_ERRORS
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
# The window starts at the issue's first_seen, the timestamp cymbal stored for the first event of its first fingerprint.
# A split issue's created_at is the time of the split, which can be days after its events. The window starts a day
# earlier for a late event. It ends an hour later for an issue without a first_seen, which falls back to created_at:
# cymbal sets that after it processes the event, and the hosts' clocks can differ.
FIRST_EVENT_LEAD = timedelta(days=1)
FIRST_EVENT_LAG = timedelta(hours=1)
# The most time between the first_seen values in one batch, so that one old issue does not widen a batch's window.
EVENT_BATCH_SPAN = timedelta(days=1)
# The retry policy of the issue-created tag activity: three attempts, with the waits between them. The ClickHouse read
# of each batch uses it too.
RETRY_DELAYS = (timedelta(seconds=2), timedelta(seconds=4))

# The inner query finds each issue's first event from small columns. The outer query then reads `properties`, a large
# column, for those events only, so the other events of a busy issue cost no properties read. `issue_id` maps an event
# to its issue through the fingerprint. An event keeps the `$exception_issue_id` it was ingested with, so after a split
# that property names the old issue.
_FIRST_EXCEPTION_EVENTS = """
    SELECT issue_id, properties
    FROM events
    WHERE event = '$exception'
      AND timestamp >= {earliest} AND timestamp <= {latest}
      AND issue_id IN {issue_ids}
      AND uuid IN (
          SELECT argMin(uuid, timestamp)
          FROM events
          WHERE event = '$exception'
            AND timestamp >= {earliest} AND timestamp <= {latest}
            AND issue_id IN {issue_ids}
          GROUP BY issue_id
      )
    LIMIT 1 BY issue_id
    LIMIT {max_rows}
"""


@frozen
class IssueTaggerRerun:
    # The issues with a tag to re-run, up to the limit. A dry run counts them and runs nothing.
    selected: int
    ran: int
    # No first event in ClickHouse, or run_issue_taggers skipped the issue: it merged away, or no selected tagger
    # applies to it any more.
    skipped: int
    # A tagger, or the ClickHouse read of the issue's batch, still failed after the retries.
    failed: int


@frozen
class _StaleIssue:
    id: UUID
    first_seen: datetime
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
    answered = {definition.key for _, definitions in applicable for definition in definitions}
    if keys is not None and (unanswered := set(keys) - answered):
        raise ValueError(f"no selected tagger answers the issue tags {sorted(unanswered)} for team {team_id}")

    stale = _stale_issues(team, applicable, answered, since=timezone.now() - timedelta(days=days), limit=limit)
    if dry_run:
        return IssueTaggerRerun(selected=len(stale), ran=0, skipped=0, failed=0)

    ran = skipped = failed = 0
    for batch in _event_batches(stale):
        try:
            events = _first_exception_events_with_retries(team, batch)
        except CH_TRANSIENT_ERRORS as error:
            logger.warning(
                "error_tracking_issue_tagger_rerun_events_unavailable",
                team_id=team_id,
                issues=len(batch),
                error_type=type(error).__name__,
            )
            failed += len(batch)
            continue
        # One issue at a time, because Jev has a rate limit.
        for issue in batch:
            properties = events.get(issue.id)
            if properties is None:
                logger.info("error_tracking_issue_tagger_rerun_event_missing", team_id=team_id, issue_id=str(issue.id))
                skipped += 1
                continue
            result = _run_with_retries(team_id, issue, properties)
            if isinstance(result, IssueTaggingSkipReason):
                logger.info(
                    "error_tracking_issue_tagger_rerun_skipped", team_id=team_id, issue_id=str(issue.id), reason=result
                )
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
    return row.question_version != definition.question_version or (
        source == Source.RULE and row.model != str(definition.tagger_config(RuleTaggerConfig).rule_id)
    )


def _stale_issues(
    team: Team,
    applicable: Sequence[tuple[Tagger, tuple[IssueTagDefinition, ...]]],
    keys: Collection[str],
    *,
    since: datetime,
    limit: int,
) -> list[_StaleIssue]:
    if not keys:
        return []
    issues = (
        ErrorTrackingIssue.objects.with_first_seen()
        .filter(team_id=team.id, status=ErrorTrackingIssue.Status.ACTIVE, created_at__gte=since)
        .order_by("-created_at", "-id")
    )
    tags = ErrorTrackingIssueTag.objects.for_team(team.parent_team_id or team.id, canonical=True)
    stale: list[_StaleIssue] = []
    page = issues
    # Page by keyset, not iterator(), which reads the whole result into memory when pgbouncer turns off server-side
    # cursors.
    while batch := list(page.values_list("id", "created_at", "first_seen")[:BATCH_SIZE]):
        last_id, last_created_at, _ = batch[-1]
        # The created_at bound lets the scan seek to the page in et_issue_active_created_idx. The OR alone only filters.
        page = issues.filter(created_at__lte=last_created_at).filter(
            Q(created_at__lt=last_created_at) | Q(created_at=last_created_at, id__lt=last_id)
        )
        rows = tags.filter(issue_id__in=[issue_id for issue_id, *_ in batch], key__in=keys)
        stored = {
            (row.issue_id, row.key): row for row in rows.only("issue_id", "key", "source", "question_version", "model")
        }
        for issue_id, created_at, first_seen in batch:
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
                    first_seen=first_seen or created_at,
                    taggers=tuple(dict.fromkeys(tagger for tagger, _ in reruns)),
                    keys=frozenset(definition.key for _, definition in reruns),
                )
            )
            if len(stale) == limit:
                return stale
    return stale


def _event_batches(issues: Sequence[_StaleIssue]) -> Iterator[list[_StaleIssue]]:
    """Group the issues by first_seen, at most BATCH_SIZE to a batch and EVENT_BATCH_SPAN apart."""
    batch: list[_StaleIssue] = []
    for issue in sorted(issues, key=lambda issue: issue.first_seen):
        if batch and (len(batch) == BATCH_SIZE or issue.first_seen - batch[0].first_seen > EVENT_BATCH_SPAN):
            yield batch
            batch = []
        batch.append(issue)
    if batch:
        yield batch


def _first_exception_events_with_retries(team: Team, issues: Sequence[_StaleIssue]) -> dict[UUID, dict[str, object]]:
    delays = iter(RETRY_DELAYS)
    while True:
        try:
            return _first_exception_events(team, issues)
        except CH_TRANSIENT_ERRORS:
            if (delay := next(delays, None)) is None:
                raise
            time.sleep(delay.total_seconds())


def _first_exception_events(team: Team, issues: Sequence[_StaleIssue]) -> dict[UUID, dict[str, object]]:
    """The properties of each issue's earliest exception event, by issue id. An issue without one is left out."""
    response = execute_hogql_query(
        query=_FIRST_EXCEPTION_EVENTS,
        placeholders={
            "earliest": ast.Constant(value=min(issue.first_seen for issue in issues) - FIRST_EVENT_LEAD),
            "latest": ast.Constant(value=max(issue.first_seen for issue in issues) + FIRST_EVENT_LAG),
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
            events[UUID(str(issue_id))] = properties
    return events


def _run_with_retries(
    team_id: int, issue: _StaleIssue, properties: dict[str, object]
) -> tuple[TaggerRun, ...] | IssueTaggingSkipReason:
    delays = iter(RETRY_DELAYS)
    while True:
        result = run_issue_taggers(team_id, issue.id, lambda team: properties, taggers=issue.taggers, keys=issue.keys)
        if (
            isinstance(result, IssueTaggingSkipReason)
            or not any(_model_unavailable(run.error) for run in result)
            or (delay := next(delays, None)) is None
        ):
            return result
        time.sleep(delay.total_seconds())


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
