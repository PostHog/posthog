"""Training metrics as events in the internal analytics project.

`metadata.json` is the durable record of a candidate, but one JSON object per day in S3 cannot be
charted. Every training run also captures its metrics as events into the dogfood project, the
same project the label events land in, keyed by `model_version` and stamped with the partition
day. Per-head stability is then a trends insight with a `head` breakdown, and a drop in
readability is an insight alert. Delivery is best-effort and never fails an asset.
"""

import datetime
from collections.abc import Mapping
from typing import Any

import dagster

from posthog import settings
from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen
from posthog.ph_client import get_client

from products.signals.dags.inbox_ranking.common import snapshot_bounds
from products.signals.dags.inbox_ranking.training.promotion import PromotionDecision

# Not a person: one fixed id for the whole dag, and no person profile is created for it. Local dev
# runs get their own id so they never blend into the prod series.
DISTINCT_ID = "inbox_ranking_training"
LOCAL_DISTINCT_ID = "inbox_ranking_training_local"
LOCAL_ENVIRONMENT = "local"
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
    """One event per head: the head's metrics plus the candidate context. A head the candidate
    could not fit still gets an event (`trained` false, `readable` false), so a per-head alert sees
    a bad day instead of a missing one."""
    context = {key: metadata.get(key) for key in _CANDIDATE_CONTEXT_KEYS}
    trained = [
        TrainingEvent(
            event=CANDIDATE_TRAINED_EVENT,
            properties={
                **context,
                "trained": True,
                **{key: value for key, value in head.items() if key not in _HEAD_FILE_KEYS},
            },
        )
        for head in metadata.get("heads", [])
    ]
    skipped = [
        TrainingEvent(
            event=CANDIDATE_TRAINED_EVENT,
            properties={**context, "head": head, "trained": False, "readable": False, "skip_reason": "nothing to fit"},
        )
        for head in metadata.get("skipped_heads", [])
    ]
    return [*trained, *skipped]


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
    incumbent_champion_version: str,
    champion_aucs: Mapping[str, float],
) -> TrainingEvent:
    """`champion_aucs` were scored by the incumbent on this candidate's holdout; after a promotion
    `champion_version` is the candidate, so the incumbent is carried separately."""
    return TrainingEvent(
        event=PROMOTION_DECIDED_EVENT,
        properties={
            "model_version": partition_key,
            "run_id": run_id,
            "would_promote": decision.promote,
            "promoted": promoted,
            "reason": decision.reason,
            "champion_version": champion_version,
            "incumbent_champion_version": incumbent_champion_version,
            **{f"champion_{head}_auc_on_this_holdout": auc for head, auc in champion_aucs.items()},
        },
    )


def event_timestamp(partition_key: str) -> datetime.datetime:
    """Midday UTC of the partition day. The run happens the next morning, so wall-clock time would
    chart a candidate one day late, and midnight UTC falls on the previous day in the dogfood
    project's US/Pacific timezone."""
    start, _ = snapshot_bounds(partition_key)
    return start + datetime.timedelta(hours=12)


def capture_allowed() -> bool:
    """Cloud, or a developer's DEBUG stack. A self-hosted instance running this dag must not
    report into PostHog's own project, which is the gate `ph_client.ScopedCapture` applies; local
    dev runs are let through on purpose so laptop experiments land on the same dashboard."""
    return is_cloud() or bool(settings.DEBUG)


def capture_training_events(
    context: dagster.AssetExecutionContext, partition_key: str, events: list[TrainingEvent]
) -> None:
    """Best-effort: a failed capture is logged, never raised, so telemetry cannot fail a training
    run. Local runs are marked twice, by `environment` and by their own distinct id, so a chart
    that forgets to filter still shows them as a separate series."""
    if not capture_allowed():
        return
    environment = settings.CLOUD_DEPLOYMENT or LOCAL_ENVIRONMENT
    distinct_id = DISTINCT_ID if environment != LOCAL_ENVIRONMENT else LOCAL_DISTINCT_ID
    timestamp = event_timestamp(partition_key)
    base = {"$process_person_profile": False, "partition": partition_key, "environment": environment}
    # A fresh client per call, flushed on shutdown, for the same reason `ph_scoped_capture` builds
    # one: the step process exits right after the asset, before a shared client's background
    # thread would deliver.
    client = get_client("US")
    if client is None:
        return
    try:
        for event in events:
            client.capture(
                distinct_id=distinct_id,
                event=event.event,
                properties={**base, **event.properties},
                timestamp=timestamp,
            )
    except Exception:
        context.log.warning(f"training telemetry capture failed for dt={partition_key}", exc_info=True)
    finally:
        client.shutdown()
