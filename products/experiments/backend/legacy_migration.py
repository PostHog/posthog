import copy
from uuid import uuid4

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models.utils import convert_legacy_metric, convert_legacy_metrics

from products.experiments.backend.experiment_saved_metric_service import ExperimentSavedMetricService
from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
    saved_metric_has_legacy_query,
)

# The copy carries everything except identity and creation time, so the new experiment keeps the
# original's feature flag, name, dates and results window. The rules v2 link and its snapshot
# belong to the source flag's rule, and the rule id is globally unique, so a copy starts unlinked.
_NOT_COPIED_FIELDS = ("id", "created_at", "key", "feature_flag_rule_id", "feature_flag_rule_snapshot")


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

        if existing := _migrated_target(original, team_id):
            return existing

        new_metric = ExperimentSavedMetric.objects.create(
            name=original.name,
            team=original.team,
            created_by=original.created_by,
            # Through the service, so the new query gets the uuid every new-engine metric needs.
            query=ExperimentSavedMetricService.normalize_query_for_write(convert_legacy_metric(original.query)),
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
        existing = Experiment.objects.filter(pk=migrated_to, team_id=team_id).first() if migrated_to else None
        if existing:
            return ExperimentMigration(
                experiment=existing,
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

        new_experiment.stats_config = {**(new_experiment.stats_config or {}), "migrated_from": original.id}
        new_experiment.metrics = _prepare_metrics(convert_legacy_metrics(original.metrics), new_experiment)
        new_experiment.metrics_secondary = _prepare_metrics(
            convert_legacy_metrics(original.metrics_secondary), new_experiment
        )
        _set_metric_ordering(new_experiment, saved_metric_targets)
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
    # Ordered, because the links are what puts the shared metrics in order on the experiment.
    links = list(
        ExperimentToSavedMetric.objects.filter(experiment=original).select_related("saved_metric").order_by("id")
    )
    already_migrated: dict[int, ExperimentSavedMetric] = {}
    blocked_by_id: dict[int, ExperimentSavedMetric] = {}
    for link in links:
        metric = link.saved_metric
        if not saved_metric_has_legacy_query(metric):
            continue
        if target := _migrated_target(metric, team_id):
            already_migrated[metric.id] = target
        else:
            blocked_by_id[metric.id] = metric
    blocked = list(blocked_by_id.values())

    if blocked and not migrate_shared_metrics:
        names = ", ".join(f'"{metric.name}" (id {metric.id})' for metric in blocked)
        raise LegacyMigrationError(f"Migrate these shared metrics first, then migrate the experiment: {names}")

    # In id order, so two experiments sharing these metrics can't migrate into a deadlock.
    replacements = {
        metric.id: migrate_saved_metric(metric.id, team_id) for metric in sorted(blocked, key=lambda metric: metric.id)
    }
    migrated_ids = [metric.id for metric in replacements.values()]

    targets = [(link, _target_metric(link.saved_metric, {**already_migrated, **replacements})) for link in links]
    return targets, migrated_ids


def _target_metric(metric: ExperimentSavedMetric, targets: dict[int, ExperimentSavedMetric]) -> ExperimentSavedMetric:
    if not saved_metric_has_legacy_query(metric):
        return metric
    return targets[metric.id]


def _migrated_target(metric: ExperimentSavedMetric, team_id: int) -> ExperimentSavedMetric | None:
    """The new-engine copy this legacy shared metric already has, if it still exists.

    The pointer outlives a hard delete of its target, so a stale one counts as unmigrated and the
    metric is migrated again. Reading it as a live id instead blocks every later migration.
    """
    migrated_to = (metric.metadata or {}).get("migrated_to")
    if not migrated_to:
        return None
    return ExperimentSavedMetric.objects.filter(pk=migrated_to, team_id=team_id).first()


def _prepare_metrics(metrics: list[dict], experiment: Experiment) -> list[dict]:
    """Give each converted metric the uuid and fingerprint the new engine writes on create.

    The conversion drops the legacy uuid and never had a fingerprint. Without a uuid the metric
    cannot enter the ordering arrays, and the UI renders only what those arrays list, so an
    experiment migrated without one shows no metrics at all.
    """
    stats_method = (experiment.stats_config or {}).get("method", "bayesian")
    for metric in metrics:
        metric["uuid"] = str(uuid4())
        metric["fingerprint"] = compute_metric_fingerprint(
            metric,
            experiment.start_date,
            stats_method,
            experiment.exposure_criteria,
            only_count_matured_users=experiment.only_count_matured_users,
            excluded_variants=experiment.excluded_variants,
        )
    return metrics


def _set_metric_ordering(
    experiment: Experiment, saved_metric_targets: list[tuple[ExperimentToSavedMetric, ExperimentSavedMetric]]
) -> None:
    """Fill the ordering arrays the new engine reads metrics through, inline metrics first."""
    ordering: dict[str, list[str]] = {
        "primary": [metric["uuid"] for metric in experiment.metrics or []],
        "secondary": [metric["uuid"] for metric in experiment.metrics_secondary or []],
    }
    for link, target in saved_metric_targets:
        if uuid := (target.query or {}).get("uuid"):
            metric_type = (link.metadata or {}).get("type", "primary")
            ordering["primary" if metric_type == "primary" else "secondary"].append(uuid)

    experiment.primary_metrics_ordered_uuids = ordering["primary"]
    experiment.secondary_metrics_ordered_uuids = ordering["secondary"]
