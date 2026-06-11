"""Canary for feature-flags local evaluation.

Builds a configured team's local-eval payload on a schedule and checks that its
``group_type_mapping`` is non-empty and that its group-aggregated flags resolve to a
group type. Gated on ``FEATURE_FLAGS_CANARY_TEAM_ID``; unset means it does nothing.
"""

from typing import Any

from django.conf import settings

import structlog
from prometheus_client import CollectorRegistry, Counter, Gauge

from posthog.models.team import Team

from products.feature_flags.backend.local_evaluation import _get_flags_response_for_local_evaluation

logger = structlog.get_logger(__name__)


def _unresolved_group_aggregated_flags(payload: dict[str, Any], group_type_mapping: dict[str, str]) -> list[str]:
    """Keys of group-aggregated flags whose aggregation index is absent from the
    mapping, so the flag cannot resolve to a group type."""
    unresolved: list[str] = []
    for flag in payload.get("flags") or []:
        index = (flag.get("filters") or {}).get("aggregation_group_type_index")
        if index is not None and str(index) not in group_type_mapping:
            unresolved.append(flag.get("key", ""))
    return unresolved


def run_local_eval_canary(registry: CollectorRegistry | None) -> None:
    """Build the canary team's local-eval payload and record its health on the given
    registry. Does nothing when ``FEATURE_FLAGS_CANARY_TEAM_ID`` is unset.

    Metrics:
    - ``posthog_feature_flags_local_eval_canary_group_mapping_present``: 1 when the
      mapping is non-empty, else 0.
    - ``posthog_feature_flags_local_eval_canary_failure_total``: incremented on an
      empty mapping, an unresolved group flag, or an exception.
    """
    team_id = settings.FEATURE_FLAGS_CANARY_TEAM_ID
    if team_id is None:
        logger.debug("Feature flags local-eval canary not configured, skipping")
        return

    present_gauge = Gauge(
        "posthog_feature_flags_local_eval_canary_group_mapping_present",
        "Whether the canary team's local-eval group_type_mapping is non-empty (1) or empty/errored (0)",
        registry=registry,
    )
    failure_counter = Counter(
        "posthog_feature_flags_local_eval_canary_failure",
        "Failures of the feature-flags local-eval canary",
        registry=registry,
    )

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        present_gauge.set(0)
        failure_counter.inc()
        logger.exception("Feature flags local-eval canary team not found", team_id=team_id)
        return

    try:
        payload = _get_flags_response_for_local_evaluation(team, include_cohorts=True)
    except Exception as e:
        present_gauge.set(0)
        failure_counter.inc()
        logger.exception("Feature flags local-eval canary failed to build payload", team_id=team_id, error=str(e))
        return

    group_type_mapping = payload.get("group_type_mapping") or {}
    mapping_present = bool(group_type_mapping)
    present_gauge.set(1 if mapping_present else 0)

    unresolved = _unresolved_group_aggregated_flags(payload, group_type_mapping)
    if not mapping_present or unresolved:
        failure_counter.inc()
        logger.error(
            "Feature flags local-eval canary unhealthy",
            team_id=team_id,
            group_type_mapping_present=mapping_present,
            unresolved_group_flags=unresolved,
        )
        return

    logger.info(
        "Feature flags local-eval canary healthy",
        team_id=team_id,
        group_type_count=len(group_type_mapping),
    )
