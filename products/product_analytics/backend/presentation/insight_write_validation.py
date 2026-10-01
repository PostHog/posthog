"""Report an insight write whose query no runner can execute.

An insight whose query breaks a validation rule saves cleanly and then fails on every render,
so a dashboard can hold a tile that has never drawn. `first_query_rule_violation` runs the
runner's own rules against the query being written, which reports the problem once instead of
on every read.

A rejection is recorded but not raised until the enforcement flag is on for the team. That
shows which saves the rules would refuse before any save starts to fail.
"""

import logging
from typing import Any

from django.contrib.auth.models import AnonymousUser

from prometheus_client import Counter
from pydantic import BaseModel
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.event_usage import report_user_action
from posthog.hogql_queries.validation.validate_query import first_query_rule_violation
from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false
from posthog.synthetic_user import SyntheticUser

logger = logging.getLogger(__name__)

INSIGHT_WRITE_VALIDATION_ENFORCED_FLAG = "insight-write-validation-enforced"

INSIGHT_WRITE_VALIDATION_COUNTER = Counter(
    "posthog_insight_write_validation_rejected_total",
    "Insight writes holding a query the runner's validation rules reject, by rule and query "
    "kind. Writes counted in shadow mode were still saved.",
    labelnames=["rule_code", "query_kind", "mode"],
)

Writer = User | AnonymousUser | SyntheticUser


@frozen
class InsightWriteRejection:
    rule_code: str
    message: str
    query_kind: str


def validate_insight_write(
    *,
    query: dict[str, Any] | None,
    team: Team,
    user: Writer,
    request: Request | None = None,
) -> None:
    """Record, and once enforced reject, an insight write that no runner could execute."""
    rejection = find_insight_write_rejection(query=query, team=team, user=user)
    if rejection is None:
        return

    enforced = is_insight_write_validation_enforced(user, team)
    _record(rejection, enforced=enforced, team=team, user=user, request=request)
    if not enforced:
        return

    raise ValidationError(
        {"query": ErrorDetail(rejection.message, code=rejection.rule_code)},
    )


def find_insight_write_rejection(
    *,
    query: dict[str, Any] | None,
    team: Team,
    user: Writer,
) -> InsightWriteRejection | None:
    """The first validation rule the written query breaks, or None if every rule passes."""
    if query:
        return _rejection_for(query, team=team, user=user)

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
    team: Team,
    user: Writer,
) -> InsightWriteRejection | None:
    violation = first_query_rule_violation(query, team=team, user=user if isinstance(user, User) else None)
    if violation is None:
        return None

    return InsightWriteRejection(
        rule_code=violation.code,
        message=violation.message,
        query_kind=violation.query_kind,
    )


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
        mode=mode,
    ).inc()

    try:
        report_user_action(
            user,
            "insight write validation rejected",
            {
                "rule_code": rejection.rule_code,
                "query_kind": rejection.query_kind,
                "mode": mode,
            },
            team=team,
            organization=team.organization,
            request=request,
        )
    except Exception:
        logger.exception("Failed to report an insight write validation rejection")
