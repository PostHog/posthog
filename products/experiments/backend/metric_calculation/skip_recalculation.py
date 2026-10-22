"""Decides which metrics a recalculation run skips, from the metric histories the caller loads.

Pure: no database, ORM or Temporal access. The caller loads every `MetricHistory` of a run in one read,
and this module only compares values. The checks live in `skip_recalculation_checks`.
"""

from collections.abc import Callable, Sequence
from datetime import datetime

import structlog

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)


@frozen
class MetricKey:
    """Saved metrics share one uuid across experiments, so the experiment id is part of the key."""

    experiment_id: int
    metric_uuid: str


@frozen
class MetricRunOutcome:
    """The result of one metric in one earlier run. `error_type` is None when the metric succeeded."""

    recalculation_id: str
    error_type: str | None
    calculation_key: str | None
    failed_at: datetime | None


@frozen
class MetricHistory:
    key: MetricKey
    calculation_key: str
    # Newest run first.
    outcomes: tuple[MetricRunOutcome, ...]

    @property
    def latest_outcome(self) -> MetricRunOutcome | None:
        return self.outcomes[0] if self.outcomes else None


@frozen
class MetricSkip:
    reason: str
    skipped_error_type: str
    failed_recalculation_id: str
    failed_at: datetime | None


SkipCheck = Callable[[MetricHistory], MetricSkip | None]


def find_metric_skips(histories: Sequence[MetricHistory], checks: Sequence[SkipCheck]) -> dict[MetricKey, MetricSkip]:
    """The first skip that `checks`, in order, return for each metric. Metrics without a skip are absent."""
    skips: dict[MetricKey, MetricSkip] = {}
    for history in histories:
        skip = _first_skip(history, checks)
        if skip is not None:
            skips[history.key] = skip
    return skips


def _first_skip(history: MetricHistory, checks: Sequence[SkipCheck]) -> MetricSkip | None:
    for check in checks:
        try:
            skip = check(history)
        except Exception:
            # A wrong skip hides a metric from the user, so a check that fails runs the metric.
            logger.exception(
                "experiment_recalculation_skip_check_failed",
                check=getattr(check, "__name__", repr(check)),
                experiment_id=history.key.experiment_id,
                metric_uuid=history.key.metric_uuid,
            )
            continue
        if skip is not None:
            return skip
    return None
