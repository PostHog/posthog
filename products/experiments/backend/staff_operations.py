"""Staff repairs and recalculation controls behind the PostHog Admin experiments tools.

Staff work across teams, outside any request or team scope, so reads go through `unscoped()` and writes
through `for_team()` of the row's own team.
"""

import copy
from datetime import datetime
from typing import Any

from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.utils import timezone

from posthog.models.user import User

from products.experiments.backend.facade.contracts import (
    RecalculationStart,
    StaffExperiment,
    StaffMigration,
    StaffRecalculation,
    StaffRecalculationFailure,
    StaffSavedMetric,
    StaffSharedMetric,
    StaffTeamExperimentCounts,
)
from products.experiments.backend.facade.enums import RecalculationStartOutcome, TerminalMarkOutcome
from products.experiments.backend.legacy_migration import migrate_experiment, migrate_saved_metric
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.metric_events import _default_metric_title
from products.experiments.backend.metric_resolution import build_metric, scheduled_metric_definitions
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
    ExperimentSavedMetric,
)
from products.experiments.backend.recalculation import (
    _derive_counters,
    cancel_recalculation_workflow,
    get_latest_recalculation,
    metrics_recalculation_workflow_id,
    request_recalculation_without_age_limit,
    start_metrics_recalculation_workflow,
)

LEGACY_METRIC_KINDS = ("ExperimentFunnelsQuery", "ExperimentTrendsQuery")
TERMINAL_RECALCULATION_STATUSES = {
    ExperimentMetricsRecalculation.Status.COMPLETED,
    ExperimentMetricsRecalculation.Status.FAILED,
}


def has_legacy_metric(metrics: list[dict] | None) -> bool:
    if not metrics:
        return False
    for metric in metrics:
        if metric.get("kind") in LEGACY_METRIC_KINDS:
            return True
    return False


def _is_malformed_properties(properties: Any) -> bool:
    """Check if properties are in old-style dict format instead of list format."""
    if properties is None or isinstance(properties, list):
        return False
    if isinstance(properties, dict):
        if "AND" in properties or "OR" in properties or "type" in properties:
            return False
        if len(properties) > 0:
            return True
    return False


def has_malformed_properties(metrics: list[dict] | None) -> bool:
    """Check if any metric has dict-style properties instead of list format."""
    if not metrics:
        return False
    for metric in metrics:
        for step in metric.get("series", []):
            if _is_malformed_properties(step.get("properties")):
                return True
        source = metric.get("source")
        if isinstance(source, dict) and _is_malformed_properties(source.get("properties")):
            return True
        for field in ["numerator", "denominator", "start_event", "completion_event"]:
            node = metric.get(field)
            if isinstance(node, dict) and _is_malformed_properties(node.get("properties")):
                return True
    return False


def transform_old_style_properties(properties: Any) -> Any:
    """Convert old-style dict properties to list format."""
    if properties is None or isinstance(properties, list):
        return properties
    if isinstance(properties, dict):
        if "AND" in properties or "OR" in properties or "type" in properties:
            return properties
        if len(properties) > 0:
            result = []
            for key, value in properties.items():
                key_parts = key.rsplit("__", 1)
                result.append(
                    {
                        "key": key_parts[0],
                        "value": value,
                        "operator": key_parts[1] if len(key_parts) > 1 else "exact",
                        "type": "event",
                    }
                )
            return result
    return properties


def fix_metric_properties(metric: dict) -> dict:
    """Transform old-style properties in all metric fields."""
    if not metric:
        return metric
    for step in metric.get("series", []):
        if "properties" in step:
            step["properties"] = transform_old_style_properties(step.get("properties"))
    if "source" in metric and isinstance(metric.get("source"), dict):
        if "properties" in metric["source"]:
            metric["source"]["properties"] = transform_old_style_properties(metric["source"]["properties"])
    for field in ["numerator", "denominator", "start_event", "completion_event"]:
        if field in metric and isinstance(metric.get(field), dict):
            if "properties" in metric[field]:
                metric[field]["properties"] = transform_old_style_properties(metric[field]["properties"])
    return metric


def experiment_has_malformed_properties(experiment: Experiment) -> bool:
    return has_malformed_properties((experiment.metrics or []) + (experiment.metrics_secondary or []))


def experiment_has_legacy_metric(experiment: Experiment) -> bool:
    return has_legacy_metric((experiment.metrics or []) + (experiment.metrics_secondary or []))


def fix_malformed_properties(experiment: Experiment) -> bool:
    """Rewrite old-style dict properties in the experiment's metrics. False when there was nothing to fix."""
    if not experiment_has_malformed_properties(experiment):
        return False
    if experiment.metrics:
        experiment.metrics = [fix_metric_properties(copy.deepcopy(m)) for m in experiment.metrics]
    if experiment.metrics_secondary:
        experiment.metrics_secondary = [fix_metric_properties(copy.deepcopy(m)) for m in experiment.metrics_secondary]
    experiment.save(update_fields=["metrics", "metrics_secondary"])
    return True


def format_duration(started_at: datetime | None, completed_at: datetime | None) -> str | None:
    """Human-friendly run duration, e.g. "4m 10s" or "45s". None when either bound is missing."""
    if started_at is None or completed_at is None:
        return None
    total_seconds = int((completed_at - started_at).total_seconds())
    if total_seconds < 0:
        return None
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    # Always show seconds so a sub-minute run reads as "45s" rather than an empty string.
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def temporal_workflow_url(recalculation_id: str) -> str:
    """Link to the recalc's Temporal Cloud workflow. Uses the runtime namespace (e.g. posthog-prod-us.usz2o),
    so it resolves per region without hardcoding a slug."""
    return (
        f"https://cloud.temporal.io/namespaces/{settings.TEMPORAL_NAMESPACE}"
        f"/workflows/{metrics_recalculation_workflow_id(recalculation_id)}"
    )


def _metric_name(definitions: dict[str, dict[str, Any]], metric_uuid: str) -> str:
    """Resolve a metric_uuid to the title a user sees, falling back to the uuid for a metric that no
    longer resolves on the experiment (removed after the run)."""
    metric_dict = definitions.get(metric_uuid)
    if metric_dict is None:
        return metric_uuid
    if metric_dict.get("name"):
        return metric_dict["name"]
    try:
        return _default_metric_title(build_metric(metric_dict)) or metric_uuid
    except Exception:
        return metric_uuid


def _resolve_failures(recalc: ExperimentMetricsRecalculation, results: list[dict]) -> list[StaffRecalculationFailure]:
    """Per-metric failures, matching the frontend resolver in experimentMetricsLogic.ts: metric_errors wins
    (it covers discovery-step failures absent from results), then a FAILED result row's error_message.
    """
    metric_errors = recalc.metric_errors or {}
    failed_row_message = {
        row["metric_uuid"]: row["error_message"]
        for row in results
        if row["status"] == ExperimentMetricResult.Status.FAILED and row["error_message"]
    }

    # Union of every uuid that failed either way, so a discovery-step failure with no result row still shows.
    failed_uuids = set(metric_errors.keys()) | set(failed_row_message.keys())
    definitions = scheduled_metric_definitions(recalc.experiment) if failed_uuids else {}
    failures = []
    for metric_uuid in failed_uuids:
        error = None
        entry = metric_errors.get(metric_uuid)
        if isinstance(entry, dict):
            error = entry.get("message")
        error = error or failed_row_message.get(metric_uuid)
        if not error:
            continue
        failures.append(
            StaffRecalculationFailure(
                metric_uuid=metric_uuid, metric_name=_metric_name(definitions, metric_uuid), error=error
            )
        )
    failures.sort(key=lambda failure: failure.metric_name.lower())
    return failures


def _run_result_statuses(recalc: ExperimentMetricsRecalculation) -> list[dict]:
    """The run's result rows in the shape of get_run_results, without `result`. The staff views show only
    counts and errors, and `result` holds the sessions of each step for a funnel, so the run page that
    refreshes while the run goes would load it again on every refresh."""
    rows = MetricResultStore(experiment_id=recalc.experiment_id).for_run(recalc, with_result=False)
    return [{"metric_uuid": row.metric_uuid, "status": row.status, "error_message": row.error_message} for row in rows]


def _to_staff_recalculation(recalc: ExperimentMetricsRecalculation, *, with_results: bool) -> StaffRecalculation:
    completed_metrics = failed_metrics = None
    failures: list[StaffRecalculationFailure] = []
    if with_results:
        results = _run_result_statuses(recalc)
        completed_metrics, failed_metrics = _derive_counters(recalc, results=results)
        failures = _resolve_failures(recalc, results)
    return StaffRecalculation(
        id=str(recalc.id),
        experiment_id=recalc.experiment_id,
        team_id=recalc.team_id,
        status=recalc.get_status_display(),
        trigger=recalc.get_trigger_display(),
        total_metrics=recalc.total_metrics,
        completed_metrics=completed_metrics,
        failed_metrics=failed_metrics,
        created_at=recalc.created_at,
        started_at=recalc.started_at,
        completed_at=recalc.completed_at,
        duration=format_duration(recalc.started_at, recalc.completed_at),
        is_terminal=recalc.status in TERMINAL_RECALCULATION_STATUSES,
        temporal_url=temporal_workflow_url(str(recalc.id)),
        failures=tuple(failures),
    )


def _to_staff_experiment(experiment: Experiment) -> StaffExperiment:
    stats_config = experiment.stats_config or {}
    return StaffExperiment(
        id=experiment.pk,
        name=experiment.name,
        team_id=experiment.team_id,
        team_name=experiment.team.name,
        status=Experiment.Status(experiment.computed_status).label,
        is_launched=experiment.is_launched,
        is_legacy=experiment_has_legacy_metric(experiment),
        has_malformed_properties=experiment_has_malformed_properties(experiment),
        migrated_from_id=stats_config.get("migrated_from"),
        migrated_to_id=stats_config.get("migrated_to"),
        created_at=experiment.created_at,
    )


def _to_staff_saved_metric(saved_metric: ExperimentSavedMetric) -> StaffSavedMetric:
    metadata = saved_metric.metadata or {}
    kind = saved_metric.query.get("kind") if saved_metric.query else None
    return StaffSavedMetric(
        id=saved_metric.pk,
        name=saved_metric.name,
        team_id=saved_metric.team_id,
        team_name=saved_metric.team.name,
        is_legacy=kind in LEGACY_METRIC_KINDS,
        migrated_from_id=metadata.get("migrated_from"),
        migrated_to_id=metadata.get("migrated_to"),
    )


def _get_experiment(experiment_id: int) -> Experiment | None:
    # nosemgrep: idor-lookup-without-team (staff console, outside any team scope)
    return Experiment.objects.select_related("team").filter(pk=experiment_id).first()


def team_experiment_counts(team_id: int) -> StaffTeamExperimentCounts:
    experiments = Experiment.objects.filter(team_id=team_id).exclude(deleted=True)
    return StaffTeamExperimentCounts(
        total=experiments.count(),
        running=experiments.filter(start_date__isnull=False, end_date__isnull=True).count(),
    )


def list_team_experiments(team_id: int, limit: int) -> list[StaffExperiment]:
    experiments = (
        Experiment.objects.select_related("team")
        .filter(team_id=team_id)
        .exclude(deleted=True)
        .order_by("-created_at")[:limit]
    )
    return [_to_staff_experiment(experiment) for experiment in experiments]


def get_experiment(experiment_id: int) -> StaffExperiment | None:
    experiment = _get_experiment(experiment_id)
    return _to_staff_experiment(experiment) if experiment is not None else None


def list_shared_metrics(experiment_id: int) -> list[StaffSharedMetric]:
    experiment = _get_experiment(experiment_id)
    if experiment is None:
        return []
    shared_metrics = []
    for metric in experiment.saved_metrics.all():
        kind = metric.query.get("kind") if metric.query else None
        shared_metrics.append(
            StaffSharedMetric(
                id=metric.pk,
                name=metric.name,
                is_legacy=kind in LEGACY_METRIC_KINDS,
                migrated_to_id=(metric.metadata or {}).get("migrated_to"),
            )
        )
    return shared_metrics


def get_saved_metric(saved_metric_id: int) -> StaffSavedMetric | None:
    # nosemgrep: idor-lookup-without-team (staff console, outside any team scope)
    saved_metric = ExperimentSavedMetric.objects.select_related("team").filter(pk=saved_metric_id).first()
    return _to_staff_saved_metric(saved_metric) if saved_metric is not None else None


def migrate_experiment_by_id(experiment_id: int) -> StaffMigration:
    # nosemgrep: idor-lookup-without-team (staff console, outside any team scope)
    team_id = Experiment.objects.values_list("team_id", flat=True).get(pk=experiment_id)
    migration = migrate_experiment(experiment_id, team_id)
    return StaffMigration(copy_id=migration.experiment.pk, already_migrated=migration.already_migrated)


def migrate_saved_metric_by_id(saved_metric_id: int) -> StaffMigration:
    # nosemgrep: idor-lookup-without-team (staff console, outside any team scope)
    original = ExperimentSavedMetric.objects.only("metadata", "team_id").get(pk=saved_metric_id)
    already_migrated = bool((original.metadata or {}).get("migrated_to"))
    new_metric = migrate_saved_metric(saved_metric_id, original.team_id)
    return StaffMigration(copy_id=new_metric.pk, already_migrated=already_migrated)


def fix_malformed_properties_by_id(experiment_id: int) -> bool:
    experiment = _get_experiment(experiment_id)
    return experiment is not None and fix_malformed_properties(experiment)


def get_recalculation(recalculation_id: str) -> StaffRecalculation | None:
    # nosemgrep: idor-lookup-without-team -- staff-only console lookup by run id behind admin_view
    recalc = ExperimentMetricsRecalculation.objects.unscoped().filter(id=recalculation_id).first()
    return _to_staff_recalculation(recalc, with_results=True) if recalc is not None else None


def get_latest_finished_recalculation(experiment_id: int) -> StaffRecalculation | None:
    experiment = _get_experiment(experiment_id)
    if experiment is None:
        return None
    latest = get_latest_recalculation(experiment)
    return _to_staff_recalculation(latest, with_results=True) if latest is not None else None


def list_recalculations(experiment_id: int | None, limit: int) -> list[StaffRecalculation]:
    """The newest runs, of one experiment or of every team, without their metric counts and failures."""
    runs = ExperimentMetricsRecalculation.objects.unscoped().order_by("-created_at")
    if experiment_id is not None:
        runs = runs.filter(experiment_id=experiment_id)
    return [_to_staff_recalculation(recalc, with_results=False) for recalc in runs[:limit]]


def start_recalculation(experiment_id: int, user: User, *, retry_failures: bool) -> RecalculationStart:
    """Create a recalculation and dispatch its workflow, like the API's create and start path.

    An active run that already exists is reused. A workflow that fails to start rolls the fresh row back to
    FAILED, so it is never left pending forever.
    """
    # A full recalculation advances the window to now. A metric-scoped change reuses the latest terminal run's
    # window, so metrics that already succeeded hit the (experiment, metric, query_to, fingerprint) cache and
    # only the failed ones recompute.
    trigger = (
        ExperimentMetricsRecalculation.Trigger.METRIC_CONFIG_CHANGE
        if retry_failures
        else ExperimentMetricsRecalculation.Trigger.MANUAL
    )
    experiment = _get_experiment(experiment_id)
    if experiment is None:
        return RecalculationStart(outcome=RecalculationStartOutcome.NOT_CREATED, detail="Experiment not found")
    try:
        result = request_recalculation_without_age_limit(experiment, user, trigger=trigger)
    except Exception as e:
        return RecalculationStart(outcome=RecalculationStartOutcome.NOT_CREATED, detail=str(e))

    recalculation_id = str(result["id"])
    if result.get("is_existing"):
        return RecalculationStart(outcome=RecalculationStartOutcome.REUSED, recalculation_id=recalculation_id)

    try:
        start_metrics_recalculation_workflow(
            recalculation_id,
            team_id=experiment.team_id,
            organization_id=str(experiment.team.organization_id),
        )
    except Exception as e:
        return RecalculationStart(
            outcome=RecalculationStartOutcome.WORKFLOW_NOT_STARTED, recalculation_id=recalculation_id, detail=str(e)
        )
    return RecalculationStart(outcome=RecalculationStartOutcome.STARTED, recalculation_id=recalculation_id)


def mark_recalculation_terminal(recalculation_id: str, *, failed: bool, user: User) -> TerminalMarkOutcome:
    """Stamp a terminal status on a run that has not finished, and cancel its workflow."""
    # nosemgrep: idor-lookup-without-team -- staff-only console lookup by run id behind admin_view
    recalc = ExperimentMetricsRecalculation.objects.unscoped().filter(id=recalculation_id).first()
    if recalc is None:
        return TerminalMarkOutcome.NOT_FOUND
    status = ExperimentMetricsRecalculation.Status.FAILED if failed else ExperimentMetricsRecalculation.Status.COMPLETED

    # A run with no query_to never started, so "completed" would be a lie the API then serves: the
    # latest-run endpoint would return it with zero results and stop falling back to timeseries data.
    if status == ExperimentMetricsRecalculation.Status.COMPLETED and recalc.query_to is None:
        return TerminalMarkOutcome.NEVER_STARTED

    # First-write-wins guard: only stamp a terminal status on a run that hasn't already finalized, so this
    # never clobbers a run the workflow completed a moment earlier. Mirrors the activity's completed_at guard.
    updated = (
        ExperimentMetricsRecalculation.objects.for_team(recalc.team_id)
        .filter(id=recalc.pk, completed_at__isnull=True)
        .update(status=status, completed_at=timezone.now())
    )
    if not updated:
        return TerminalMarkOutcome.ALREADY_TERMINAL

    cancel_recalculation_workflow(str(recalc.pk))

    # Keeps the run's Django admin history, where staff look for who changed a run.
    LogEntry.objects.log_actions(
        user_id=user.pk,
        queryset=[recalc],
        action_flag=CHANGE,
        change_message=f"Manually marked {status} from PostHog Admin.",
        single_object=True,
    )
    return TerminalMarkOutcome.MARKED
