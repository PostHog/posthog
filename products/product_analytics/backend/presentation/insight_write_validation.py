"""Run the query runners' validation rules when an insight is written, not only when it runs.

The rules in `posthog/hogql_queries/validation` fire from `QueryRunner.calculate()`, so they
only see a query on the read path. An insight whose query no runner can execute saves
cleanly and then fails on every render, so a dashboard can hold a tile that has never drawn.
This module runs the same rule objects against the query that is being written, which
reports the problem once instead of on every read.

A rejection is recorded but not raised until the enforcement flag is on for the team. That
shows which saves the rules would refuse before any save starts to fail.
"""

import logging
from typing import Any, Literal

from django.contrib.auth.models import AnonymousUser

from prometheus_client import Counter
from pydantic import BaseModel
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.event_usage import report_user_action
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner_or_none
from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false
from posthog.synthetic_user import SyntheticUser

logger = logging.getLogger(__name__)

INSIGHT_WRITE_VALIDATION_ENFORCED_FLAG = "insight-write-validation-enforced"

INSIGHT_WRITE_VALIDATION_COUNTER = Counter(
    "posthog_insight_write_validation_rejected_total",
    "Insight writes holding a query the runner's validation rules reject, by rule, query kind "
    "and which field carried the query. Writes counted in shadow mode were still saved.",
    labelnames=["rule_code", "query_kind", "write_source", "mode"],
)

WriteSource = Literal["query", "filters"]

Writer = User | AnonymousUser | SyntheticUser


@frozen
class InsightWriteRejection:
    rule_code: str
    message: str
    query_kind: str
    write_source: WriteSource


@frozen
class _RuleError:
    message: str
    code: str


def validate_insight_write(
    *,
    query: dict[str, Any] | None,
    filters: dict[str, Any] | None,
    unchanged_query: dict[str, Any] | None = None,
    team: Team,
    user: Writer,
    request: Request | None = None,
) -> None:
    """Record, and once enforced reject, an insight write that no runner could execute."""
    rejection = find_insight_write_rejection(
        query=query,
        filters=filters,
        unchanged_query=unchanged_query,
        team=team,
        user=user,
    )
    if rejection is None:
        return

    enforced = is_insight_write_validation_enforced(user, team)
    _record(rejection, enforced=enforced, team=team, user=user, request=request)
    if not enforced:
        return

    raise ValidationError(
        {rejection.write_source: ErrorDetail(rejection.message, code=rejection.rule_code)},
    )


def find_insight_write_rejection(
    *,
    query: dict[str, Any] | None,
    filters: dict[str, Any] | None,
    unchanged_query: dict[str, Any] | None = None,
    team: Team,
    user: Writer,
) -> InsightWriteRejection | None:
    """The first validation rule the written query breaks, or None if every rule passes.

    An insight renders from `query` whenever it has one, and falls back to `filters` only
    when it does not. So a written query is what the rules must judge, and written filters
    matter only when no query remains on the insight after this write. `unchanged_query` is
    the stored query this write leaves in place, which keeps a filters write from being
    judged on a field that nothing renders.
    """
    if query:
        return _rejection_for(query, write_source="query", team=team, user=user)

    if filters and not unchanged_query:
        try:
            source = filter_to_query(filters)
        except Exception:
            # Filters this side can't convert never reach a runner here, and the app converts
            # them again in the browser, so we have nothing to say about them.
            return None
        return _rejection_for(source, write_source="filters", team=team, user=user)

    return None


def is_insight_write_validation_enforced(user: Writer, team: Team) -> bool:
    distinct_id = getattr(user, "distinct_id", None)
    if not distinct_id:
        return False

    return feature_enabled_or_false(
        INSIGHT_WRITE_VALIDATION_ENFORCED_FLAG,
        str(distinct_id),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
        send_feature_flag_events=False,
    )


def _rejection_for(
    query: dict[str, Any] | BaseModel,
    *,
    write_source: WriteSource,
    team: Team,
    user: Writer,
) -> InsightWriteRejection | None:
    runner = _runner_or_none(query, team=team, user=user)
    if runner is None:
        return None

    try:
        runner.validate()
    except ValidationError as error:
        rule_error = _first_error(error)
        return InsightWriteRejection(
            rule_code=rule_error.code,
            message=rule_error.message,
            query_kind=str(getattr(runner.query, "kind", "unknown")),
            write_source=write_source,
        )
    except Exception:
        # Only a rule saying "this can never run" is worth a 400. Anything else a rule throws
        # is our bug, and failing the save on it would block writes the read path accepts.
        logger.exception("Insight write validation rule failed")
        return None

    return None


def _runner_or_none(query: dict[str, Any] | BaseModel, *, team: Team, user: Writer) -> QueryRunner | None:
    try:
        return get_query_runner_or_none(query, team, user=user if isinstance(user, User) else None)
    except Exception:
        # A payload no runner can be built for is one the read path already handles its own
        # way. Rejecting it here would turn every shape we don't recognize into a 400.
        return None


def _first_error(error: ValidationError) -> _RuleError:
    detail: Any = error.detail
    if isinstance(detail, dict):
        detail = next(iter(detail.values()), "")
    if isinstance(detail, list):
        detail = detail[0] if detail else ""
    return _RuleError(message=str(detail), code=str(getattr(detail, "code", "invalid")))


def _record(
    rejection: InsightWriteRejection,
    *,
    enforced: bool,
    team: Team,
    user: Writer,
    request: Request | None,
) -> None:
    mode = "enforced" if enforced else "shadow"
    INSIGHT_WRITE_VALIDATION_COUNTER.labels(
        rule_code=rejection.rule_code,
        query_kind=rejection.query_kind,
        write_source=rejection.write_source,
        mode=mode,
    ).inc()

    try:
        report_user_action(
            user,
            "insight write validation rejected",
            {
                "rule_code": rejection.rule_code,
                "query_kind": rejection.query_kind,
                "write_source": rejection.write_source,
                "mode": mode,
            },
            team=team,
            organization=team.organization,
            request=request,
        )
    except Exception:
        logger.exception("Failed to report an insight write validation rejection")
