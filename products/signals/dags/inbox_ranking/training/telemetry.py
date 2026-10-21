"""Training metrics as events in the internal analytics project.

`metadata.json` is the durable record of a candidate, but one JSON object per day in S3 cannot be
charted. Every training run also captures its metrics as events into the dogfood project, the
same project the label events land in, keyed by `model_name` and `model_version` and stamped with
the partition day. Per-head stability is then a trends insight with a `head` breakdown, one line
per model family, and a drop in readability is an insight alert. Delivery is best-effort and never
fails an asset.
"""

import datetime
from collections.abc import Mapping, Sequence
from typing import Any

from posthog import settings
from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen
from posthog.ph_client import get_client

from products.signals.backend.ranking.serving_manifest import ServingManifest
from products.signals.dags.inbox_ranking.common import RunContext, snapshot_bounds
from products.signals.dags.inbox_ranking.training.promotion import PromotionDecision
from products.signals.dags.inbox_ranking.training.unseen import CANDIDATE_ROLE, HeadGrade

# Not a person: one fixed id for the whole dag, and no person profile is created for it. Local dev
# runs get their own id so they never blend into the prod series.
DISTINCT_ID = "inbox_ranking_training"
LOCAL_SUFFIX = "_local"
LOCAL_DISTINCT_ID = f"{DISTINCT_ID}{LOCAL_SUFFIX}"
LOCAL_ENVIRONMENT = "local"
CANDIDATE_TRAINED_EVENT = "inbox_ranking_candidate_trained"
PROMOTION_DECIDED_EVENT = "inbox_ranking_promotion_decided"
MODEL_PROMOTED_EVENT = "inbox_ranking_model_promoted"
UNSEEN_HEAD_GRADED_EVENT = "inbox_ranking_unseen_head_graded"
UNSEEN_HEAD_EVALUATED_EVENT = "inbox_ranking_unseen_head_evaluated"
UNSEEN_REPORT_GRADED_EVENT = "inbox_ranking_unseen_report_graded"
UNSEEN_CALIBRATION_EVENT = "inbox_ranking_unseen_calibration"
HOLDOUT_CALIBRATION_EVENT = "inbox_ranking_holdout_calibration"
SERVING_MANIFEST_PUBLISHED_EVENT = "inbox_ranking_serving_manifest_published"

# Candidate metadata copied onto every per-head event so a chart can filter or break down on it.
_CANDIDATE_CONTEXT_KEYS = (
    "model_name",
    "model_version",
    "run_id",
    "dataset_version",
    "feature_schema_version",
    "lookback_days",
    "holdout_days",
    "recipe_hash",
)
# Object names inside the models prefix; meaningless on a chart.
_HEAD_FILE_KEYS = ("file", "holdout_file")


@frozen
class TrainingEvent:
    event: str
    properties: dict[str, object]


def candidate_events(metadata: Mapping[str, Any]) -> list[TrainingEvent]:
    """One event per head: the head's metrics plus the candidate context. A head the candidate
    could not fit still gets an event (`trained` false, `readable` false), so a per-head alert sees
    a bad day instead of a missing one. The role is stamped rather than read from the metadata: this
    asset only ever fits candidates, and the unseen events carry both roles, so without it a chart
    filtered to the candidate keeps the unseen line and drops these rows."""
    context = {key: metadata.get(key) for key in _CANDIDATE_CONTEXT_KEYS} | {"model_role": CANDIDATE_ROLE}
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


def promotion_event(
    *,
    partition_key: str,
    run_id: str,
    model_name: str,
    decision: PromotionDecision,
    incumbent_champion_version: str,
    champion_aucs: Mapping[str, float],
    champion_eces: Mapping[str, float],
    recipe_hash: str | None = None,
    incumbent_recipe_hash: str | None = None,
) -> TrainingEvent:
    """`champion_aucs` and `champion_eces` were scored by the incumbent on this candidate's holdout.
    The incumbent is the served model when it has `model_name`, else `none`.

    Training never moves the served pointer, so `promoted` is always false. A person promotes
    through `inbox_ranking_promote_job`, which captures `MODEL_PROMOTED_EVENT`.
    The two recipe hashes are None for a version written before the hash existed."""
    return TrainingEvent(
        event=PROMOTION_DECIDED_EVENT,
        properties={
            "model_name": model_name,
            "model_version": partition_key,
            "run_id": run_id,
            "would_promote": decision.promote,
            "gates_passed": decision.gates_passed,
            "promoted": False,
            "reason": decision.reason,
            "skipped_heads": list(decision.skipped_heads),
            "champion_version": incumbent_champion_version,
            "incumbent_champion_version": incumbent_champion_version,
            "recipe_hash": recipe_hash,
            "incumbent_recipe_hash": incumbent_recipe_hash,
            **{f"champion_{head}_auc_on_this_holdout": auc for head, auc in champion_aucs.items()},
            **{f"champion_{head}_ece_on_this_holdout": ece for head, ece in champion_eces.items()},
        },
    )


def model_promoted_event(*, model_key: str, previous_key: str | None, reason: str, run_id: str) -> TrainingEvent:
    return TrainingEvent(
        event=MODEL_PROMOTED_EVENT,
        properties={"model_key": model_key, "previous_key": previous_key, "reason": reason, "run_id": run_id},
    )


def serving_manifest_event(
    *,
    partition_key: str,
    run_id: str,
    served_family: str,
    manifest: ServingManifest | None,
    reason: str,
    copied_keys: Sequence[str] = (),
    present_keys: Sequence[str] = (),
    bytes_copied: int = 0,
    mirror_published: bool | None = None,
    recipe_hashes: Mapping[str, str | None] | None = None,
) -> TrainingEvent:
    """What the day's manifest published. A run that wrote nothing still reports, with `reason`:
    the manifest is what makes the sweep serve anything, so a silent gap in this series would read
    the same as a day of ordinary publishing. `recipe_hashes` maps a model key to the `recipe_hash`
    of its `metadata.json`."""
    properties: dict[str, object] = {
        "model_version": partition_key,
        "run_id": run_id,
        "served_family": served_family,
        "published": manifest is not None,
        "reason": reason,
        "entries_copied": len(copied_keys),
        "entries_already_present": len(present_keys),
        "bytes_copied": bytes_copied,
    }
    if manifest is not None:
        properties |= {
            "manifest_version": manifest.manifest_version,
            "served_key": manifest.served.key,
            "model_keys": [entry.key for entry in manifest.models],
            "model_roles": {entry.key: entry.roles for entry in manifest.models},
            "model_recipe_hashes": {entry.key: (recipe_hashes or {}).get(entry.key) for entry in manifest.models},
        }
    if mirror_published is not None:
        properties["mirror_published"] = mirror_published
    return TrainingEvent(event=SERVING_MANIFEST_PUBLISHED_EVENT, properties=properties)


def unseen_head_graded_events(*, run_id: str, grades: Sequence[HeadGrade]) -> list[TrainingEvent]:
    """One event per (model, head): the unseen AUC that sits next to the head's holdout AUC. A head
    with rows but a single outcome class still reports, with a null AUC, so the series has no gap."""
    return [
        TrainingEvent(event=UNSEEN_HEAD_GRADED_EVENT, properties={**grade.as_dict(), "run_id": run_id})
        for grade in grades
    ]


def unseen_head_evaluated_events(
    *, run_id: str, grades: Sequence[HeadGrade], evaluation_partition: str, evaluated_at: datetime.datetime
) -> list[TrainingEvent]:
    # A separate stream keeps provisional negatives out of mature-only charts and alerts.
    events: list[TrainingEvent] = []
    for grade in grades:
        observed_days = (
            datetime.date.fromisoformat(evaluation_partition) - datetime.date.fromisoformat(grade.scoring_partition)
        ).days
        if not 0 <= observed_days <= grade.horizon_days:
            raise ValueError("Unseen evaluations must stay within the head's outcome horizon")
        events.append(
            TrainingEvent(
                event=UNSEEN_HEAD_EVALUATED_EVENT,
                properties={
                    **grade.as_dict(),
                    "run_id": run_id,
                    "evaluation_partition": evaluation_partition,
                    "evaluated_at": evaluated_at.isoformat(),
                    "observed_days": observed_days,
                    "is_mature": observed_days == grade.horizon_days,
                    "scored_rows": grade.scored_rows,
                    "cohort_coverage": grade.rows / grade.scored_rows if grade.scored_rows else None,
                },
            )
        )
    return events


def unseen_calibration_events(*, run_id: str, rows: Sequence[Mapping[str, Any]]) -> list[TrainingEvent]:
    """One event per (model, head, score decile) of the unseen grade: how much the decile predicted
    against how often the outcome happened. One event per bucket because a decile table on the head
    event would be a JSON array, which no insight can break down."""
    return [TrainingEvent(event=UNSEEN_CALIBRATION_EVENT, properties={**row, "run_id": run_id}) for row in rows]


def holdout_calibration_events(
    *, partition_key: str, run_id: str, model_name: str, rows: Sequence[Mapping[str, Any]]
) -> list[TrainingEvent]:
    """The same read on the candidate's holdout. The properties match the unseen event, so one
    insight holds both lines and a gap between them points at holdout optimism. These rows score the
    train-only fit and the unseen rows score the refit that ships, so the refit moves the gap too.
    The role is stamped rather than grouped on: a run grades only the candidate it just fit, and
    without it a chart filtered to the candidate keeps the unseen line and drops this one."""
    return [
        TrainingEvent(
            event=HOLDOUT_CALIBRATION_EVENT,
            properties={
                "model_name": model_name,
                "model_version": partition_key,
                "model_role": CANDIDATE_ROLE,
                "run_id": run_id,
                **row,
            },
        )
        for row in rows
    ]


def unseen_report_graded_events(*, run_id: str, rows: Sequence[Mapping[str, Any]]) -> list[TrainingEvent]:
    """One event per (report, model, horizon): the scores and what actually happened, for
    calibration reads. Stamped on the day the outcome was read; `scoring_partition` carries the day
    the report was scored, so a chart can be built on either axis."""
    return [TrainingEvent(event=UNSEEN_REPORT_GRADED_EVENT, properties={**row, "run_id": run_id}) for row in rows]


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
    context: RunContext,
    partition_key: str,
    events: list[TrainingEvent],
    *,
    timestamp: datetime.datetime | None = None,
    distinct_id: str = DISTINCT_ID,
) -> None:
    """Best-effort: a failed capture is logged, never raised, so telemetry cannot fail a training
    run. Local runs are marked twice, by `environment` and by their own distinct id, so a chart
    that forgets to filter still shows them as a separate series. `timestamp` defaults to the
    partition's midday; an event about a person's action passes the moment it happened. Another
    pipeline of this dag passes its own fixed `distinct_id`."""
    if not capture_allowed():
        return
    environment = settings.CLOUD_DEPLOYMENT or LOCAL_ENVIRONMENT
    if environment == LOCAL_ENVIRONMENT:
        distinct_id = f"{distinct_id}{LOCAL_SUFFIX}"
    timestamp = timestamp or event_timestamp(partition_key)
    base = {"$process_person_profile": False, "partition": partition_key, "environment": environment}
    # A fresh client per call, flushed on shutdown, for the same reason `ph_scoped_capture` builds
    # one: the step process exits right after the asset, before a shared client's background
    # thread would deliver. Its queue holds the whole batch, because the SDK drops an event that
    # meets a full queue and reports it only on its own logger: the grading asset enqueues one row
    # per report, model and horizon, which is more than the default 10,000 slots.
    client = get_client("US", max_queue_size=max(len(events), 1))
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
