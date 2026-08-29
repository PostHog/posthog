"""Training metrics as events in the internal analytics project.

`metadata.json` is the durable record of a candidate, but one JSON object per day in S3 cannot be
charted. Every training run also captures its metrics as events into the dogfood project, the
same project the label events land in, keyed by `model_version` and stamped with the partition
day. Per-head stability is then a trends insight with a `head` breakdown, and a drop in
readability is an insight alert. Delivery is best-effort and never fails an asset.
"""

import logging
import datetime
from collections.abc import Mapping
from typing import Any

import dagster

from posthog import settings
from posthog.dataclasses import frozen
from posthog.ph_client import ph_scoped_capture

from products.signals.dags.inbox_ranking.common import snapshot_bounds
from products.signals.dags.inbox_ranking.training.promotion import PromotionDecision

logger = logging.getLogger(__name__)

# Not a person: one fixed id for the whole dag, and no person profile is created for it.
DISTINCT_ID = "inbox_ranking_training"
CANDIDATE_TRAINED_EVENT = "inbox_ranking_candidate_trained"
EXAMPLES_BUILT_EVENT = "inbox_ranking_examples_built"
PROMOTION_DECIDED_EVENT = "inbox_ranking_promotion_decided"

# Candidate metadata copied onto every per-head event so a chart can filter or break down on it.
_CANDIDATE_CONTEXT_KEYS = (
    "model_version",
    "run_id",
    "dataset_version",
    "feature_schema_version",
    "lookback_days",
    "holdout_days",
)
# Object names inside the models prefix; meaningless on a chart.
_HEAD_FILE_KEYS = ("file", "holdout_file")


@frozen
class TrainingEvent:
    event: str
    properties: dict[str, object]


@frozen
class HeadExampleCounts:
    rows: int
    positives: int


def candidate_events(metadata: Mapping[str, Any]) -> list[TrainingEvent]:
    """One event per trained head: the head's metrics plus the candidate context."""
    context = {key: metadata.get(key) for key in _CANDIDATE_CONTEXT_KEYS}
    return [
        TrainingEvent(
            event=CANDIDATE_TRAINED_EVENT,
            properties={**context, **{key: value for key, value in head.items() if key not in _HEAD_FILE_KEYS}},
        )
        for head in metadata.get("heads", [])
    ]


def examples_events(
    *,
    partition_key: str,
    run_id: str,
    snapshots: int,
    backfilled_rows: int,
    per_head: Mapping[str, HeadExampleCounts],
) -> list[TrainingEvent]:
    """One event per head with its example and positive counts; the run-level counts repeat on each."""
    return [
        TrainingEvent(
            event=EXAMPLES_BUILT_EVENT,
            properties={
                "model_version": partition_key,
                "run_id": run_id,
                "snapshots": snapshots,
                "backfilled_state_rows_excluded": backfilled_rows,
                "head": head,
                "rows": counts.rows,
                "positives": counts.positives,
            },
        )
        for head, counts in per_head.items()
    ]


def promotion_event(
    *,
    partition_key: str,
    run_id: str,
    decision: PromotionDecision,
    promoted: bool,
    champion_version: str,
    champion_aucs: Mapping[str, float],
) -> TrainingEvent:
    return TrainingEvent(
        event=PROMOTION_DECIDED_EVENT,
        properties={
            "model_version": partition_key,
            "run_id": run_id,
            "would_promote": decision.promote,
            "promoted": promoted,
            "reason": decision.reason,
            "champion_version": champion_version,
            **{f"champion_{head}_auc_on_this_holdout": auc for head, auc in champion_aucs.items()},
        },
    )


def event_timestamp(partition_key: str) -> datetime.datetime:
    """Midday UTC of the partition day. The run happens the next morning, so wall-clock time would
    chart a candidate one day late, and midnight UTC falls on the previous day in the dogfood
    project's US/Pacific timezone."""
    start, _ = snapshot_bounds(partition_key)
    return start + datetime.timedelta(hours=12)


def capture_training_events(
    context: dagster.AssetExecutionContext, partition_key: str, events: list[TrainingEvent]
) -> None:
    """Best-effort: a failed capture is logged, never raised, so telemetry cannot fail a training
    run. Off Cloud the client captures nothing (see `ph_client.ScopedCapture`)."""
    timestamp = event_timestamp(partition_key)
    base = {
        "$process_person_profile": False,
        "partition": partition_key,
        "environment": settings.CLOUD_DEPLOYMENT or "local",
    }
    try:
        with ph_scoped_capture() as capture:
            for event in events:
                capture(
                    distinct_id=DISTINCT_ID,
                    event=event.event,
                    properties={**base, **event.properties},
                    timestamp=timestamp,
                )
    except Exception:
        context.log.warning(f"training telemetry capture failed for dt={partition_key}", exc_info=True)
