import copy

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models.utils import convert_legacy_metric, convert_legacy_metrics

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
    saved_metric_has_legacy_query,
)

# The copy carries everything except identity and creation time, so the new experiment keeps the
# original's feature flag, name, dates and results window.
_NOT_COPIED_FIELDS = ("id", "created_at", "key")


class LegacyMigrationError(Exception):
    """Raised with a message meant for the person who asked for the migration."""


@frozen
class ExperimentMigration:
    experiment: Experiment
    already_migrated: bool
    migrated_saved_metric_ids: list[int]


def migrate_saved_metric(saved_metric_id: int, team_id: int) -> ExperimentSavedMetric:
    """Create a new-engine copy of a legacy shared metric, or return the copy made earlier."""
    with transaction.atomic():
        original = ExperimentSavedMetric.objects.select_for_update().get(pk=saved_metric_id, team_id=team_id)

        migrated_to = (original.metadata or {}).get("migrated_to")
        if migrated_to:
            return ExperimentSavedMetric.objects.get(pk=migrated_to, team_id=team_id)

        new_metric = ExperimentSavedMetric.objects.create(
            name=original.name,
            team=original.team,
            created_by=original.created_by,
            query=convert_legacy_metric(original.query),
            metadata={"migrated_from": original.id},
        )

        original.metadata = {**(original.metadata or {}), "migrated_to": new_metric.id}
        original.save(update_fields=["metadata"])

        return new_metric


def migrate_experiment(
    experiment_id: int, team_id: int, *, migrate_shared_metrics: bool = False
) -> ExperimentMigration:
    """Create a new-engine copy of a legacy experiment, or return the copy made earlier.

    The original is left untouched and keeps its results. Both experiments point at the same
    feature flag, so the copy needs no new rollout.

    Legacy shared metrics have to be migrated too. With migrate_shared_metrics they are migrated
    as part of this call; without it, an unmigrated one raises LegacyMigrationError.
    """
    with transaction.atomic():
        original = Experiment.objects.select_for_update().get(pk=experiment_id, team_id=team_id)

        migrated_to = (original.stats_config or {}).get("migrated_to")
        if migrated_to:
            return ExperimentMigration(
                experiment=Experiment.objects.get(pk=migrated_to, team_id=team_id),
                already_migrated=True,
                migrated_saved_metric_ids=[],
            )

        saved_metric_targets, migrated_saved_metric_ids = _resolve_saved_metrics(
            original, team_id, migrate_shared_metrics=migrate_shared_metrics
        )

        new_experiment = Experiment()
        for field in original._meta.fields:
            if field.name in _NOT_COPIED_FIELDS:
                continue
            value = getattr(original, field.name)
            # Deep copy dicts to avoid shared references
            if isinstance(value, dict):
                value = copy.deepcopy(value)
            setattr(new_experiment, field.name, value)

        new_experiment.metrics = convert_legacy_metrics(original.metrics)
        new_experiment.metrics_secondary = convert_legacy_metrics(original.metrics_secondary)
        new_experiment.stats_config = {**(new_experiment.stats_config or {}), "migrated_from": original.id}
        new_experiment.save()

        for link, target in saved_metric_targets:
            # The through row carries metadata, so the link is created by hand rather than
            # through experiment.saved_metrics.add.
            ExperimentToSavedMetric.objects.create(
                experiment=new_experiment,
                saved_metric=target,
                metadata=copy.deepcopy(link.metadata),
            )

        original.stats_config = {**(original.stats_config or {}), "migrated_to": new_experiment.id}
        original.save(update_fields=["stats_config"])

        return ExperimentMigration(
            experiment=new_experiment,
            already_migrated=False,
            migrated_saved_metric_ids=migrated_saved_metric_ids,
        )


def _resolve_saved_metrics(
    original: Experiment, team_id: int, *, migrate_shared_metrics: bool
) -> tuple[list[tuple[ExperimentToSavedMetric, ExperimentSavedMetric]], list[int]]:
    """Pick the shared metric each link should point at, migrating legacy ones when allowed."""
    targets: list[tuple[ExperimentToSavedMetric, ExperimentSavedMetric]] = []
    migrated_ids: list[int] = []
    blocked: list[ExperimentSavedMetric] = []

    for link in ExperimentToSavedMetric.objects.filter(experiment=original).select_related("saved_metric"):
        metric = link.saved_metric
        if not saved_metric_has_legacy_query(metric):
            targets.append((link, metric))
            continue

        migrated_to = (metric.metadata or {}).get("migrated_to")
        if migrated_to:
            targets.append((link, ExperimentSavedMetric.objects.get(pk=migrated_to, team_id=team_id)))
        elif migrate_shared_metrics:
            new_metric = migrate_saved_metric(metric.id, team_id)
            migrated_ids.append(new_metric.id)
            targets.append((link, new_metric))
        else:
            blocked.append(metric)

    if blocked:
        names = ", ".join(f'"{metric.name}" (id {metric.id})' for metric in blocked)
        raise LegacyMigrationError(f"Migrate these shared metrics first, then migrate the experiment: {names}")

    return targets, migrated_ids
