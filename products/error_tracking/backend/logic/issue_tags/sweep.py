import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import batched
from uuid import UUID

from django.db import transaction
from django.db.models import Q

import structlog

from posthog.schema import PropertyGroupFilterValue

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, HogQLGlobalSettings
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.dataclasses import frozen
from posthog.models import Team

from products.error_tracking.backend.logic.issue_tags.enabled import _active_rules, lock_active_rule_definition
from products.error_tracking.backend.logic.issue_tags.gate import issue_tags_enabled
from products.error_tracking.backend.logic.issue_tags.rules import _read_properties
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagAnswer
from products.error_tracking.backend.logic.issue_tags.writer import set_issue_tag
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag, ErrorTrackingIssueTagRule

logger = structlog.get_logger(__name__)

# A filter on the exception list reads the full exceptions and stack traces of every event in the window. On the
# events table that costs far more than the other properties, so the sweep leaves these rules to the issue-created
# tagger, which reads one event per issue.
EXPENSIVE_PROPERTIES = frozenset({"$exception_list"})
QUERY_MAX_EXECUTION_SECONDS = 300
# HogQL returns at most this many rows. Issue ids sort by creation time, so an order by issue id would cut the newest
# issues on every run. The query orders the rows by a hash of the issue id and the window's start date instead. Each
# retry of a run then cuts the same issues, and the next day's run cuts different issues.
MAX_ISSUES = MAX_SELECT_RETURNED_ROWS
TAG_READ_BATCH_SIZE = 1000
# How many ids of matching issues with no answer for the rule's tag each error_tracking_tag_rule_sweep_rule log line
# lists, so that a person can check some labels by hand.
SAMPLE_ISSUES = 10

# One row per issue with an exception in the window that matches at least one rule. `match_counts` holds the number
# of matching exceptions per rule, in rule order. `issue_id` maps an event to its issue through the fingerprint, so an
# exception of a merged issue counts for the issue it merged into. `any_rule` drops the events that match no rule before
# the grouping, so that the grouping holds only the matching issues.
_MATCHING_ISSUES = """
    SELECT issue_id, {match_counts} AS match_counts
    FROM events
    WHERE event = '$exception'
      AND timestamp >= {start} AND timestamp < {end}
      AND isNotNull(issue_id)
      AND {any_rule}
    GROUP BY issue_id
    ORDER BY cityHash64(concat(toString(issue_id), {order_seed}))
    LIMIT {max_issues}
"""


class TagRuleSweepSkipReason(StrEnum):
    DISABLED = "disabled"
    TEAM_MISSING = "team_missing"


@frozen
class RuleSweep:
    rule_id: UUID
    # Issues with at least one exception in the window that matches the rule.
    matching_issues: int
    # The matching issues without an answer for the rule's tag.
    labels_to_write: int
    labels_written: int


@frozen
class TeamTagRuleSweep:
    dry_run: bool
    rules: tuple[RuleSweep, ...]
    # Rules that filter on an expensive property, or whose filters no longer compile.
    rules_skipped: int
    # Issues that match at least one rule.
    matching_issues: int
    query_duration: timedelta

    @property
    def truncated(self) -> bool:
        """Whether the query returned MAX_ISSUES rows, so that some matching issues got no label in this run."""
        return self.matching_issues >= MAX_ISSUES


@frozen
class _SweepableRule:
    id: UUID
    key: str
    version: int
    match: ast.Expr


@frozen
class _Matches:
    # The matching issue ids of each rule, in rule order.
    issue_ids: tuple[tuple[UUID, ...], ...]
    matching_issues: int
    duration: timedelta


_NO_MATCHES = _Matches(issue_ids=(), matching_issues=0, duration=timedelta(0))


def teams_with_tag_rules() -> list[int]:
    """The teams of each project with an enabled tag rule, child environments included. Checks no flag."""
    projects = ErrorTrackingIssueTagRule.objects.unscoped().filter(disabled_data__isnull=True).values("team_id")
    teams = Team.objects.filter(Q(id__in=projects) | Q(parent_team_id__in=projects))
    return list(teams.order_by("id").values_list("id", flat=True))


def sweep_team_tag_rules(
    team_id: int,
    *,
    start: datetime,
    end: datetime,
    dry_run: bool = False,
    on_progress: Callable[[], object] = lambda: None,
) -> TeamTagRuleSweep | TagRuleSweepSkipReason:
    """Label each issue with an exception from `start` to `end` that matches a tag rule, unless the issue answers the
    rule's tag already.

    A label stays when later exceptions stop matching, and a person's answer is never replaced. A dry run counts the
    labels and writes none. The issue tags flag check comes first, so a team without issue tags reads no rule and no
    event.
    """
    if not issue_tags_enabled(team_id):
        return TagRuleSweepSkipReason.DISABLED
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return TagRuleSweepSkipReason.TEAM_MISSING
    rules, rules_skipped = _sweepable_rules(team)
    matches = _NO_MATCHES
    if rules:
        matches = _matching_issues(team, rules, start=start, end=end)
        on_progress()
    swept = tuple(
        _label_issues(team, rule, issue_ids, dry_run=dry_run, on_progress=on_progress)
        for rule, issue_ids in zip(rules, matches.issue_ids)
    )
    return TeamTagRuleSweep(
        dry_run=dry_run,
        rules=swept,
        rules_skipped=rules_skipped,
        matching_issues=matches.matching_issues,
        query_duration=matches.duration,
    )


def _sweepable_rules(team: Team) -> tuple[list[_SweepableRule], int]:
    """The team's enabled rules as HogQL conditions, and the number of rules skipped."""
    rules: list[_SweepableRule] = []
    skipped = 0
    for rule in _active_rules(team.id).order_by("created_at", "id").only("id", "key", "version", "filters"):
        if _read_properties(rule.filters) & EXPENSIVE_PROPERTIES:
            _log_rule_skipped(team, rule, reason="expensive_property")
            skipped += 1
            continue
        try:
            match = property_to_expr(PropertyGroupFilterValue(**rule.filters), team, strict=True)
        except (BaseHogQLError, ValueError, TypeError, AssertionError):
            _log_rule_skipped(team, rule, reason="invalid_filters")
            skipped += 1
            continue
        rules.append(_SweepableRule(id=rule.id, key=rule.key, version=rule.version, match=match))
    return rules, skipped


def _matching_issues(team: Team, rules: Sequence[_SweepableRule], *, start: datetime, end: datetime) -> _Matches:
    started = time.monotonic()
    response = execute_hogql_query(
        query=_MATCHING_ISSUES,
        placeholders={
            "match_counts": ast.Array(exprs=[ast.Call(name="countIf", args=[rule.match]) for rule in rules]),
            "any_rule": ast.Or(exprs=[rule.match for rule in rules]),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "order_seed": ast.Constant(value=start.date().isoformat()),
            "max_issues": ast.Constant(value=MAX_ISSUES),
        },
        team=team,
        query_type="ErrorTrackingTagRuleSweep",
        # A daily batch job, so no person waits for the result.
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.ERROR_TRACKING,
        settings=HogQLGlobalSettings(max_execution_time=QUERY_MAX_EXECUTION_SECONDS),
    )
    duration = timedelta(seconds=time.monotonic() - started)
    rows = response.results or []
    issue_ids: list[list[UUID]] = [[] for _ in rules]
    for issue_id, match_counts in rows:
        issue_uuid = UUID(str(issue_id))
        for rule_issue_ids, count in zip(issue_ids, match_counts):
            if count > 0:
                rule_issue_ids.append(issue_uuid)
    return _Matches(issue_ids=tuple(tuple(ids) for ids in issue_ids), matching_issues=len(rows), duration=duration)


def _label_issues(
    team: Team,
    rule: _SweepableRule,
    issue_ids: Sequence[UUID],
    *,
    dry_run: bool,
    on_progress: Callable[[], object],
) -> RuleSweep:
    tags = ErrorTrackingIssueTag.objects.for_team(team.parent_team_id or team.id, canonical=True).filter(key=rule.key)
    answered: set[UUID] = set()
    for batch in batched(issue_ids, TAG_READ_BATCH_SIZE, strict=False):
        answered.update(tags.filter(issue_id__in=batch).values_list("issue_id", flat=True))
    unanswered = [issue_id for issue_id in issue_ids if issue_id not in answered]
    written = 0 if dry_run or not unanswered else _write_labels(team, rule, unanswered, on_progress)
    logger.info(
        "error_tracking_tag_rule_sweep_rule",
        team_id=team.id,
        rule_id=str(rule.id),
        dry_run=dry_run,
        matching_issues=len(issue_ids),
        labels_to_write=len(unanswered),
        labels_written=written,
        sample_issue_ids=[str(issue_id) for issue_id in unanswered[:SAMPLE_ISSUES]],
    )
    return RuleSweep(
        rule_id=rule.id, matching_issues=len(issue_ids), labels_to_write=len(unanswered), labels_written=written
    )


def _write_labels(
    team: Team, rule: _SweepableRule, issue_ids: Sequence[UUID], on_progress: Callable[[], object]
) -> int:
    answer = TagAnswer(value=True, probability=None, model=str(rule.id), question_version=rule.version, set_by=None)
    written = 0
    for issue_id in issue_ids:
        # A person can edit or delete the rule while the query or the writes run. A label from the edited rule would
        # carry an answer to the old filters, and a label from the deleted rule would stay after the delete removed the
        # rule's tags. The rule lock lasts until the label commits, so each label checks the rule as it stands.
        with transaction.atomic():
            definition = lock_active_rule_definition(team.id, rule.id)
            if definition is None or definition.question_version != rule.version or definition.key != rule.key:
                logger.info("error_tracking_tag_rule_sweep_rule_changed", team_id=team.id, rule_id=str(rule.id))
                return written
            try:
                if set_issue_tag(team.id, issue_id, definition, answer, ErrorTrackingIssueTag.Source.RULE):
                    written += 1
            except ErrorTrackingIssue.DoesNotExist:
                # A merge or a delete removed the issue after ClickHouse read the fingerprint's issue.
                pass
        on_progress()
    return written


def _log_rule_skipped(team: Team, rule: ErrorTrackingIssueTagRule, *, reason: str) -> None:
    logger.warning("error_tracking_tag_rule_sweep_rule_skipped", team_id=team.id, rule_id=str(rule.id), reason=reason)
