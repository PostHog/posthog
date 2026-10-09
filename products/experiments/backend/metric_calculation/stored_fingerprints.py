"""Rewrite the stored `fingerprint` of inline metrics to the current calculation key.

Create, update and launch stamp each inline metric in `Experiment.metrics` and `Experiment.metrics_secondary` with its
calculation key. After a change of the key version, the stored values hold the old version until the next save of
each experiment. That save rewrites every fingerprint, and the activity log then describes every metric as changed.
The rewrite here writes the values in place with a queryset update, so it logs no activity and leaves `version` and
`updated_at` alone.

Saved metrics store no fingerprint: the experiment API stamps theirs into each response.
"""

from collections.abc import Callable, Sequence
from typing import Any

from django.db import transaction

import structlog

from posthog.dataclasses import frozen

from products.experiments.backend.metric_calculation.config import (
    ExperimentCalculationSettings,
    stamp_calculation_keys,
    team_experiments_configs,
)
from products.experiments.backend.metric_resolution import MetricRole
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

logger = structlog.get_logger(__name__)

_INLINE_METRIC_FIELDS: tuple[tuple[str, MetricRole], ...] = (("metrics", "primary"), ("metrics_secondary", "secondary"))


@frozen
class FingerprintRewriteReport:
    experiments_scanned: int
    experiments_to_rewrite: int
    metrics_to_rewrite: int
    # Experiments whose rewrite raised. A later run retries them.
    experiments_failed: int


def _rewritten_fields(experiment: Experiment, team_config: TeamExperimentsConfig) -> tuple[dict[str, list[Any]], int]:
    """The inline metric fields whose stored fingerprints differ from the current keys, with only those fingerprints
    replaced, and how many metrics change. A metric without a stored fingerprint stays as it is."""
    settings = ExperimentCalculationSettings.from_experiment(experiment, team_config=team_config)
    fields: dict[str, list[Any]] = {}
    changed_metrics = 0
    for field_name, role in _INLINE_METRIC_FIELDS:
        metrics = getattr(experiment, field_name)
        if not isinstance(metrics, list) or not metrics:
            continue
        stamped = stamp_calculation_keys(metrics, role, settings)
        rewritten = []
        for stored, restamped in zip(metrics, stamped):
            if "fingerprint" in stored and stored["fingerprint"] != restamped["fingerprint"]:
                rewritten.append({**stored, "fingerprint": restamped["fingerprint"]})
                changed_metrics += 1
            else:
                rewritten.append(stored)
        if rewritten != metrics:
            fields[field_name] = rewritten
    return fields, changed_metrics


def _write(experiment_id: int, team_id: int, team_config: TeamExperimentsConfig) -> None:
    with transaction.atomic():
        # Recompute from the locked row, so that a save that landed after the unlocked read is not overwritten.
        locked = (
            Experiment.objects.select_for_update(no_key=True, of=("self",))
            .select_related("team", "feature_flag")
            .filter(id=experiment_id, team_id=team_id)
            .first()
        )
        if locked is None:
            return
        fields, _ = _rewritten_fields(locked, team_config)
        if fields:
            Experiment.objects.filter(id=experiment_id, team_id=team_id).update(**fields)


def rewrite_stored_fingerprints(
    *,
    apply: bool,
    team_ids: Sequence[int] | None = None,
    batch_size: int = 500,
    on_batch: Callable[[FingerprintRewriteReport], None] | None = None,
) -> FingerprintRewriteReport:
    """Find the non-deleted experiments whose stored inline fingerprints differ from the current keys, and rewrite
    them when `apply` is set. Experiments are read in id order, `batch_size` at a time. A second run finds nothing
    to rewrite."""
    # Read without creating a missing row: a team without one resolves to the model defaults, as a new row would.
    team_configs: dict[int, TeamExperimentsConfig] = {}
    scanned = to_rewrite = metrics_to_rewrite = failed = 0
    last_id = 0
    while True:
        experiments = Experiment.objects.filter(deleted=False, id__gt=last_id)
        if team_ids:
            experiments = experiments.filter(team_id__in=team_ids)
        batch = list(experiments.select_related("team", "feature_flag").order_by("id")[:batch_size])
        if not batch:
            break
        last_id = batch[-1].id
        team_configs.update(
            team_experiments_configs({experiment.team_id for experiment in batch} - team_configs.keys())
        )
        for experiment in batch:
            scanned += 1
            team_config = team_configs[experiment.team_id]
            try:
                fields, changed_metrics = _rewritten_fields(experiment, team_config)
                if not fields:
                    continue
                if apply:
                    _write(experiment.id, experiment.team_id, team_config)
            except Exception:
                failed += 1
                logger.exception("experiment_fingerprint_rewrite_failed", experiment_id=experiment.id)
                continue
            to_rewrite += 1
            metrics_to_rewrite += changed_metrics
        if on_batch is not None:
            on_batch(_report(scanned, to_rewrite, metrics_to_rewrite, failed))
    return _report(scanned, to_rewrite, metrics_to_rewrite, failed)


def _report(scanned: int, to_rewrite: int, metrics_to_rewrite: int, failed: int) -> FingerprintRewriteReport:
    return FingerprintRewriteReport(
        experiments_scanned=scanned,
        experiments_to_rewrite=to_rewrite,
        metrics_to_rewrite=metrics_to_rewrite,
        experiments_failed=failed,
    )
