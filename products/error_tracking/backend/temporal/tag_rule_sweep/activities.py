import dataclasses

import structlog
from prometheus_client import Counter, Histogram
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.errors import QueryErrorCategory, classify_query_error
from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.logic.issue_tags.sweep import (
    QUERY_MAX_EXECUTION_SECONDS,
    TagRuleSweepSkipReason,
    sweep_team_tag_rules,
    teams_with_tag_rules,
)
from products.error_tracking.backend.temporal.tag_rule_sweep.types import (
    SweepTeamTagRulesInputs,
    SweepTeamTagRulesResult,
)

logger = structlog.get_logger(__name__)

QUERY_LIMIT_ERROR_TYPE = "ErrorTrackingTagRuleSweepQueryLimit"
INVALID_RULE_ERROR_TYPE = "ErrorTrackingTagRuleSweepInvalidRule"

ERROR_TRACKING_TAG_RULE_SWEEP_TEAMS = Counter(
    "error_tracking_tag_rule_sweep_teams_total",
    "Teams that the daily tag rule sweep finished, skipped, or stopped at a query limit or an invalid rule, by "
    "outcome. The workflow's teams_failed counter also counts the stopped teams",
    labelnames=("outcome",),
)
ERROR_TRACKING_TAG_RULE_SWEEP_RULES = Counter(
    "error_tracking_tag_rule_sweep_rules_total",
    "Tag rules that the daily sweep ran or skipped, by outcome",
    labelnames=("outcome",),
)
ERROR_TRACKING_TAG_RULE_SWEEP_MATCHING_ISSUES = Counter(
    "error_tracking_tag_rule_sweep_matching_issues_total",
    "Issues with an exception in the sweep window that matches at least one tag rule",
)
ERROR_TRACKING_TAG_RULE_SWEEP_LABELS = Counter(
    "error_tracking_tag_rule_sweep_labels_total",
    "Rule labels on matching issues without an answer, by mode, and by whether the sweep found or wrote them",
    labelnames=("mode", "outcome"),
)
ERROR_TRACKING_TAG_RULE_SWEEP_QUERY_SECONDS = Histogram(
    "error_tracking_tag_rule_sweep_query_seconds",
    "Time of the tag rule query for one team",
    buckets=(1, 5, 15, 30, 60, 120, 180, 240, QUERY_MAX_EXECUTION_SECONDS),
)


@activity.defn
@close_db_connections
def list_tag_rule_teams_activity() -> list[int]:
    team_ids = teams_with_tag_rules()
    logger.info("error_tracking_tag_rule_sweep_teams_listed", teams=len(team_ids))
    return team_ids


@activity.defn
@close_db_connections
def sweep_team_tag_rules_activity(inputs: SweepTeamTagRulesInputs) -> SweepTeamTagRulesResult:
    try:
        sweep = sweep_team_tag_rules(
            inputs.team_id,
            start=inputs.start,
            end=inputs.end,
            dry_run=inputs.dry_run,
            on_progress=activity.heartbeat,
        )
    except Exception as error:
        category = classify_query_error(error)
        if category == QueryErrorCategory.USER_ERROR:
            ERROR_TRACKING_TAG_RULE_SWEEP_TEAMS.labels(outcome="invalid_rule").inc()
            # A rule's filters can compile when the rule is saved and still fail to resolve in the query. A retry reads
            # the same rules, so it fails the same way.
            raise ApplicationError(
                f"A tag rule of team {inputs.team_id} does not resolve in the query: {type(error).__name__}",
                type=INVALID_RULE_ERROR_TYPE,
                non_retryable=True,
            ) from error
        # A capacity error, such as a full cluster, is not a limit of this query, so Temporal retries it.
        if category != QueryErrorCategory.QUERY_PERFORMANCE_ERROR:
            raise
        ERROR_TRACKING_TAG_RULE_SWEEP_TEAMS.labels(outcome="query_limit").inc()
        # A retry reads the same events with the same rules, so it costs as much and stops at the same limit.
        raise ApplicationError(
            f"The tag rule query for team {inputs.team_id} hit its limit: {type(error).__name__}",
            type=QUERY_LIMIT_ERROR_TYPE,
            non_retryable=True,
        ) from error

    if isinstance(sweep, TagRuleSweepSkipReason):
        ERROR_TRACKING_TAG_RULE_SWEEP_TEAMS.labels(outcome=sweep.value).inc()
        logger.info("error_tracking_tag_rule_sweep_team_skipped", team_id=inputs.team_id, reason=sweep)
        return SweepTeamTagRulesResult(skipped=sweep)

    result = SweepTeamTagRulesResult(
        dry_run=sweep.dry_run,
        rules_run=len(sweep.rules),
        rules_skipped=sweep.rules_skipped,
        matching_issues=sweep.matching_issues,
        labels_to_write=sum(rule.labels_to_write for rule in sweep.rules),
        labels_written=sum(rule.labels_written for rule in sweep.rules),
        truncated=sweep.truncated,
    )
    mode = "dry_run" if result.dry_run else "write"
    ERROR_TRACKING_TAG_RULE_SWEEP_TEAMS.labels(outcome="swept").inc()
    ERROR_TRACKING_TAG_RULE_SWEEP_RULES.labels(outcome="ran").inc(result.rules_run)
    ERROR_TRACKING_TAG_RULE_SWEEP_RULES.labels(outcome="skipped").inc(result.rules_skipped)
    ERROR_TRACKING_TAG_RULE_SWEEP_MATCHING_ISSUES.inc(result.matching_issues)
    ERROR_TRACKING_TAG_RULE_SWEEP_LABELS.labels(mode=mode, outcome="to_write").inc(result.labels_to_write)
    ERROR_TRACKING_TAG_RULE_SWEEP_LABELS.labels(mode=mode, outcome="written").inc(result.labels_written)
    if result.rules_run:
        ERROR_TRACKING_TAG_RULE_SWEEP_QUERY_SECONDS.observe(sweep.query_duration.total_seconds())
    logger.info(
        "error_tracking_tag_rule_sweep_team",
        team_id=inputs.team_id,
        query_seconds=sweep.query_duration.total_seconds(),
        **dataclasses.asdict(result),
    )
    return result
