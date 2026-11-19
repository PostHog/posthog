from datetime import datetime
from typing import cast
from urllib.parse import urlencode
from uuid import UUID

from django import forms
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from posthog.admin.console.panels import Fact, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Live, Notice, Page, Row, Table, ToolOperation
from posthog.models.team.team import Team
from posthog.models.user import User

from products.experiments.backend.facade import staff
from products.experiments.backend.facade.contracts import StaffExperiment, StaffRecalculation
from products.experiments.backend.facade.enums import RecalculationStartOutcome, TerminalMarkOutcome

EXPERIMENTS = Owner(name="Experiments", crest="experiments")

EXPERIMENTS_TOOL_URL = "/admin/console/tools/experiments/"
RECALCULATIONS_TOOL_URL = "/admin/console/tools/experiment-recalculations/"
TEAM_EXPERIMENTS_LIMIT = 100
RECENT_RUNS = 25
EXPERIMENT_RUNS = 10
REFRESH_SECONDS_WHILE_RUNNING = 10


def _experiments_url(**params: object) -> str:
    return f"{EXPERIMENTS_TOOL_URL}?{urlencode(params)}"


def _recalculations_url(**params: object) -> str:
    return f"{RECALCULATIONS_TOOL_URL}?{urlencode(params)}"


def _int_param(request: HttpRequest, name: str) -> int | None:
    value = request.GET.get(name, "").strip()
    return int(value) if value.isascii() and value.isdigit() else None


def _uuid_param(request: HttpRequest, name: str) -> str | None:
    try:
        return str(UUID(request.GET.get(name, "").strip()))
    except ValueError:
        return None


def _when(value: datetime | None) -> Cell:
    if value is None:
        return Cell(text="-", muted=True)
    return Cell(text=value.strftime("%Y-%m-%d %H:%M:%S"))


@console.register_panel
class ExperimentsPanel(Panel):
    record = "team"
    key = "experiments"
    title = "Experiments"
    owner = EXPERIMENTS

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Team)
        counts = staff.team_experiment_counts(obj.pk)
        return [
            Fact(label="Experiments", value=str(counts.total), href=_experiments_url(team=obj.pk)),
            Fact(label="Running", value=str(counts.running)),
        ]


class MigrateExperiment:
    def __init__(self, experiment_id: int) -> None:
        self.experiment_id = experiment_id

    def __call__(self, request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
        try:
            migration = staff.migrate_experiment_by_id(self.experiment_id)
        except Exception as e:
            messages.error(request, f"Error migrating experiment: {e}")
            return HttpResponse(status=400)
        if migration.already_migrated:
            messages.warning(request, f"Experiment already migrated to {migration.copy_id}")
        else:
            messages.success(request, "Experiment migrated successfully")
        return HttpResponseRedirect(_experiments_url(experiment=migration.copy_id))


class MigrateSavedMetric:
    def __init__(self, saved_metric_id: int) -> None:
        self.saved_metric_id = saved_metric_id

    def __call__(self, request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
        try:
            migration = staff.migrate_saved_metric_by_id(self.saved_metric_id)
        except Exception as e:
            messages.error(request, f"Error migrating metric: {e}")
            return HttpResponse(status=400)
        if migration.already_migrated:
            messages.warning(request, f"Metric already migrated to {migration.copy_id}")
        else:
            messages.success(request, "Metric migrated successfully")
        return HttpResponseRedirect(_experiments_url(saved_metric=migration.copy_id))


class FixMalformedProperties:
    def __init__(self, experiment_id: int) -> None:
        self.experiment_id = experiment_id

    def __call__(self, request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
        if staff.fix_malformed_properties_by_id(self.experiment_id):
            messages.success(request, "Fixed malformed properties in experiment metrics")
        else:
            messages.info(request, "No malformed properties found")
        return None


class StartRecalculation:
    def __init__(self, experiment_id: int, *, retry_failures: bool) -> None:
        self.experiment_id = experiment_id
        self.retry_failures = retry_failures

    def __call__(self, request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
        start = staff.start_recalculation(
            self.experiment_id, cast(User, request.user), retry_failures=self.retry_failures
        )
        if start.outcome == RecalculationStartOutcome.NOT_CREATED:
            messages.error(request, f"Could not create recalculation: {start.detail}")
            return HttpResponse(status=400)
        if start.outcome == RecalculationStartOutcome.WORKFLOW_NOT_STARTED:
            messages.error(request, f"Created the row but failed to start the workflow (marked failed): {start.detail}")
            return HttpResponse(status=502)
        if start.outcome == RecalculationStartOutcome.REUSED:
            messages.info(request, "An active recalculation already exists for this experiment; reused it.")
            return None
        messages.success(request, f"Started new recalculation {start.recalculation_id}.")
        return HttpResponseRedirect(_recalculations_url(run=start.recalculation_id))


class MarkRecalculationTerminal:
    def __init__(self, recalculation_id: str, *, failed: bool) -> None:
        self.recalculation_id = recalculation_id
        self.failed = failed

    def __call__(self, request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
        outcome = staff.mark_recalculation_terminal(
            self.recalculation_id, failed=self.failed, user=cast(User, request.user)
        )
        if outcome == TerminalMarkOutcome.NOT_FOUND:
            messages.error(request, "This recalculation no longer exists.")
            return HttpResponse(status=404)
        if outcome == TerminalMarkOutcome.NEVER_STARTED:
            messages.error(request, "This recalculation never started, so it cannot be completed; mark it failed.")
            return HttpResponse(status=400)
        if outcome == TerminalMarkOutcome.ALREADY_TERMINAL:
            messages.error(request, "This recalculation is already terminal; nothing to change.")
            return HttpResponse(status=409)
        messages.success(request, f"Recalculation marked {'failed' if self.failed else 'completed'}.")
        return None


def _start_operations(experiment_id: int, latest: StaffRecalculation | None) -> list[ToolOperation]:
    operations = [
        ToolOperation(
            key="start-recalculation",
            label="Start new recalculation",
            handler=StartRecalculation(experiment_id, retry_failures=False),
            description="Recalculates every metric of the experiment up to now.",
        )
    ]
    if latest is not None and latest.failures:
        operations.append(
            ToolOperation(
                key="retry-failures",
                label="Retry latest failures",
                handler=StartRecalculation(experiment_id, retry_failures=True),
                description="Recalculates only the metrics that failed in the latest run. The others load from the cache.",
            )
        )
    return operations


def _recalculation_summary(run: StaffRecalculation) -> Table:
    return Table(
        columns=("Status", "Trigger", "Metrics", "Started", "Ended", "Execution time", "Workflow"),
        rows=(
            Row(
                cells=(
                    Cell(text=run.status, tone=_status_tone(run)),
                    Cell(text=run.trigger),
                    Cell(text=f"{run.completed_metrics} completed, {run.failed_metrics} failed of {run.total_metrics}"),
                    _when(run.started_at),
                    _when(run.completed_at),
                    Cell(text=run.duration or "-", muted=run.duration is None),
                    Cell(text="Open in Temporal", href=run.temporal_url),
                )
            ),
        ),
    )


def _failures_table(run: StaffRecalculation) -> Table:
    return Table(
        columns=("Metric", "Error"),
        rows=tuple(Row(cells=(Cell(text=f.metric_name), Cell(text=f.error))) for f in run.failures),
        empty_text="No metric failed in this run.",
    )


def _status_tone(run: StaffRecalculation) -> Tone | None:
    if run.status == "Failed":
        return Tone.DESTRUCTIVE
    if run.status == "Completed":
        return Tone.SUCCESS
    return Tone.INFO


def _runs_table(runs: list[StaffRecalculation], *, show_experiment: bool) -> Table:
    columns: tuple[str, ...] = (
        "Run",
        "Experiment",
        "Team",
        "Status",
        "Trigger",
        "Metrics",
        "Created",
        "Execution time",
    )
    if not show_experiment:
        columns = ("Run", "Status", "Trigger", "Metrics", "Created", "Execution time")
    rows = []
    for run in runs:
        context = (
            Cell(text=str(run.experiment_id), href=_experiments_url(experiment=run.experiment_id)),
            Cell(text=str(run.team_id), href=f"/admin/console/teams/{run.team_id}/"),
        )
        cells = (
            Cell(text=run.id, href=_recalculations_url(run=run.id), mono=True),
            *(context if show_experiment else ()),
            Cell(text=run.status, tone=_status_tone(run)),
            Cell(text=run.trigger),
            Cell(text=str(run.total_metrics)),
            _when(run.created_at),
            Cell(text=run.duration or "-", muted=run.duration is None),
        )
        rows.append(Row(cells=cells))
    return Table(columns=columns, rows=tuple(rows), empty_text="No recalculation has run yet.")


def _runs_live(runs: list[StaffRecalculation], *, show_experiment: bool) -> Live:
    running = any(not run.is_terminal for run in runs)
    return Live(
        key="runs",
        block=_runs_table(runs, show_experiment=show_experiment),
        refresh_seconds=REFRESH_SECONDS_WHILE_RUNNING if running else None,
    )


def _experiment_row(experiment: StaffExperiment) -> Row:
    return Row(
        cells=(
            Cell(text=experiment.name, href=_experiments_url(experiment=experiment.id)),
            Cell(text=str(experiment.id), mono=True),
            Cell(text=experiment.status),
            Cell(
                text="Legacy" if experiment.is_legacy else "Current",
                tone=Tone.WARNING if experiment.is_legacy else None,
                muted=not experiment.is_legacy,
            ),
            Cell(
                text="Malformed" if experiment.has_malformed_properties else "-",
                tone=Tone.DESTRUCTIVE if experiment.has_malformed_properties else None,
                muted=not experiment.has_malformed_properties,
            ),
            _when(experiment.created_at),
        )
    )


@console.register_tool
class ExperimentsTool(ConsoleTool):
    key = "experiments"
    title = "Experiments"
    owner = EXPERIMENTS
    group = "Data"
    description = "One team's experiments, with metric repairs, legacy engine migration and recalculations."

    def page(self, request: HttpRequest) -> Page:
        experiment_id = _int_param(request, "experiment")
        if experiment_id is not None:
            return self._experiment_page(experiment_id)
        saved_metric_id = _int_param(request, "saved_metric")
        if saved_metric_id is not None:
            return self._saved_metric_page(saved_metric_id)
        team_id = _int_param(request, "team")
        if team_id is not None:
            return self._team_page(team_id)
        return Page(
            blocks=(
                Notice(
                    text="Open this page from the Experiments panel on a team page.",
                    link_text="Find a team",
                    href="/admin/console/",
                ),
            )
        )

    def _team_page(self, team_id: int) -> Page:
        experiments = staff.list_team_experiments(team_id, TEAM_EXPERIMENTS_LIMIT)
        return Page(
            blocks=(
                Notice(
                    text=f"Experiments of team {team_id}, newest first. The page shows up to {TEAM_EXPERIMENTS_LIMIT}.",
                    link_text="Back to the team",
                    href=f"/admin/console/teams/{team_id}/",
                ),
                Table(
                    columns=("Experiment", "ID", "Status", "Engine", "Metric properties", "Created"),
                    rows=tuple(_experiment_row(experiment) for experiment in experiments),
                    empty_text="This team has no experiments.",
                ),
            )
        )

    def _experiment_page(self, experiment_id: int) -> Page:
        experiment = staff.get_experiment(experiment_id)
        if experiment is None:
            return Page(blocks=(Notice(text=f"No experiment has the ID {experiment_id}."),))
        blocks: list[Notice | Table | Live] = [
            Notice(
                text=f"Experiment '{experiment.name}' ({experiment.id}) of team '{experiment.team_name}'. "
                f"Status: {experiment.status}.",
                link_text="All experiments of this team",
                href=_experiments_url(team=experiment.team_id),
            )
        ]
        if experiment.migrated_from_id is not None:
            blocks.append(
                Notice(
                    text=f"Migrated from experiment {experiment.migrated_from_id}.",
                    link_text="Open it",
                    href=_experiments_url(experiment=experiment.migrated_from_id),
                )
            )
        if experiment.migrated_to_id is not None:
            blocks.append(
                Notice(
                    text=f"Migrated to experiment {experiment.migrated_to_id}.",
                    link_text="Open it",
                    href=_experiments_url(experiment=experiment.migrated_to_id),
                )
            )
        if experiment.has_malformed_properties:
            blocks.append(Notice(text="This experiment has malformed metric properties (dict instead of list format)."))

        shared_metrics = staff.list_shared_metrics(experiment_id)
        unmigrated = [metric for metric in shared_metrics if metric.is_legacy and metric.migrated_to_id is None]
        if experiment.is_legacy or any(metric.is_legacy for metric in shared_metrics):
            if unmigrated:
                blocks.append(
                    Notice(text="This experiment cannot be migrated yet. Migrate all legacy shared metrics first.")
                )
            else:
                blocks.append(Notice(text="This experiment uses the legacy engine and can be migrated."))
        if shared_metrics:
            blocks.append(
                Table(
                    columns=("Shared metric", "Engine", "Migrated to"),
                    rows=tuple(
                        Row(
                            cells=(
                                Cell(text=metric.name, href=_experiments_url(saved_metric=metric.id)),
                                Cell(
                                    text="Legacy" if metric.is_legacy else "Current",
                                    tone=Tone.WARNING if metric.is_legacy else None,
                                    muted=not metric.is_legacy,
                                ),
                                self._migrated_to_cell(metric.is_legacy, metric.migrated_to_id),
                            )
                        )
                        for metric in shared_metrics
                    ),
                )
            )

        latest = staff.get_latest_finished_recalculation(experiment_id)
        if latest is None:
            blocks.append(Notice(text="No recalculation has finished for this experiment yet."))
        else:
            blocks.append(
                Notice(
                    text="Latest finished recalculation.",
                    link_text="Open the run",
                    href=_recalculations_url(run=latest.id),
                )
            )
            blocks.append(_recalculation_summary(latest))
            if latest.failures:
                blocks.append(_failures_table(latest))
        blocks.append(
            Notice(
                text=f"The {EXPERIMENT_RUNS} newest recalculations of this experiment.",
                link_text="All recalculations",
                href=_recalculations_url(experiment=experiment_id),
            )
        )
        blocks.append(_runs_live(staff.list_recalculations(experiment_id, EXPERIMENT_RUNS), show_experiment=False))
        return Page(blocks=tuple(blocks))

    @staticmethod
    def _migrated_to_cell(is_legacy: bool, migrated_to_id: int | None) -> Cell:
        if not is_legacy:
            return Cell(text="-", muted=True)
        if migrated_to_id is None:
            return Cell(text="Not migrated", tone=Tone.DESTRUCTIVE)
        return Cell(text=f"#{migrated_to_id}", href=_experiments_url(saved_metric=migrated_to_id))

    def _saved_metric_page(self, saved_metric_id: int) -> Page:
        saved_metric = staff.get_saved_metric(saved_metric_id)
        if saved_metric is None:
            return Page(blocks=(Notice(text=f"No shared metric has the ID {saved_metric_id}."),))
        blocks = [
            Notice(
                text=f"Shared metric '{saved_metric.name}' ({saved_metric.id}) of team '{saved_metric.team_name}'.",
                link_text="All experiments of this team",
                href=_experiments_url(team=saved_metric.team_id),
            )
        ]
        if saved_metric.migrated_from_id is not None:
            blocks.append(
                Notice(
                    text=f"Migrated from shared metric {saved_metric.migrated_from_id}.",
                    link_text="Open it",
                    href=_experiments_url(saved_metric=saved_metric.migrated_from_id),
                )
            )
        if saved_metric.migrated_to_id is not None:
            blocks.append(
                Notice(
                    text=f"Migrated to shared metric {saved_metric.migrated_to_id}.",
                    link_text="Open it",
                    href=_experiments_url(saved_metric=saved_metric.migrated_to_id),
                )
            )
        if saved_metric.is_legacy:
            blocks.append(Notice(text="This metric uses the legacy engine and can be migrated."))
        return Page(blocks=tuple(blocks))

    def live(self, request: HttpRequest, key: str) -> Live | None:
        experiment_id = _int_param(request, "experiment")
        if key != "runs" or experiment_id is None:
            return None
        return _runs_live(staff.list_recalculations(experiment_id, EXPERIMENT_RUNS), show_experiment=False)

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        saved_metric_id = _int_param(request, "saved_metric")
        if saved_metric_id is not None and _int_param(request, "experiment") is None:
            saved_metric = staff.get_saved_metric(saved_metric_id)
            if saved_metric is None or not saved_metric.is_legacy:
                return []
            return [
                ToolOperation(
                    key="migrate-saved-metric",
                    label="Migrate shared metric",
                    handler=MigrateSavedMetric(saved_metric_id),
                    danger=True,
                    form_class=ReasonForm,
                    description=f"Creates a new-engine copy of shared metric '{saved_metric.name}' ({saved_metric.id}) "
                    f"of team '{saved_metric.team_name}'. The original stays as it is.",
                    undo_hint="To undo, delete the copy in the project.",
                )
            ]

        experiment_id = _int_param(request, "experiment")
        if experiment_id is None:
            return []
        experiment = staff.get_experiment(experiment_id)
        if experiment is None:
            return []
        operations = []
        if experiment.has_malformed_properties:
            operations.append(
                ToolOperation(
                    key="fix-properties",
                    label="Fix metric properties",
                    handler=FixMalformedProperties(experiment_id),
                    danger=True,
                    form_class=ReasonForm,
                    description=f"Rewrites the metric properties of experiment '{experiment.name}' ({experiment.id}) "
                    f"of team '{experiment.team_name}' from the old dict format to the list format.",
                    undo_hint="This cannot be undone. The old metric values are not kept.",
                )
            )
        shared_metrics = staff.list_shared_metrics(experiment_id)
        has_legacy = experiment.is_legacy or any(metric.is_legacy for metric in shared_metrics)
        can_migrate = not any(metric.is_legacy and metric.migrated_to_id is None for metric in shared_metrics)
        if has_legacy and can_migrate:
            operations.append(
                ToolOperation(
                    key="migrate",
                    label="Migrate experiment",
                    handler=MigrateExperiment(experiment_id),
                    danger=True,
                    form_class=ReasonForm,
                    description=f"Creates a new-engine copy of experiment '{experiment.name}' ({experiment.id}) "
                    f"of team '{experiment.team_name}'. The original stays as it is.",
                    undo_hint="To undo, delete the copy in the project.",
                )
            )
        # A recalculation needs a start date, so a draft gets none.
        if experiment.is_launched:
            operations.extend(_start_operations(experiment_id, staff.get_latest_finished_recalculation(experiment_id)))
        return operations


@console.register_tool
class ExperimentRecalculationsTool(ConsoleTool):
    key = "experiment-recalculations"
    title = "Experiment recalculations"
    owner = EXPERIMENTS
    group = "Data"
    description = "Metrics recalculation runs across teams, and controls for a stuck run."

    def page(self, request: HttpRequest) -> Page:
        run_id = _uuid_param(request, "run")
        if run_id is not None:
            return self._run_page(request, run_id)
        experiment_id = _int_param(request, "experiment")
        runs = self.live(request, "runs")
        assert runs is not None
        if experiment_id is None:
            heading = Notice(text=f"The {RECENT_RUNS} newest recalculations across all teams.")
        else:
            heading = Notice(
                text=f"The {RECENT_RUNS} newest recalculations of experiment {experiment_id}.",
                link_text="Open the experiment",
                href=_experiments_url(experiment=experiment_id),
            )
        return Page(blocks=(heading, runs))

    def _run_page(self, request: HttpRequest, run_id: str) -> Page:
        run = staff.get_recalculation(run_id)
        if run is None:
            return Page(blocks=(Notice(text=f"No recalculation has the ID {run_id}."),))
        summary = self.live(request, "run")
        failures = self.live(request, "run-failures")
        assert summary is not None and failures is not None
        return Page(
            blocks=(
                Notice(
                    text=f"Recalculation {run.id} of experiment {run.experiment_id}, team {run.team_id}.",
                    link_text="Open the experiment to retry its latest failures",
                    href=_experiments_url(experiment=run.experiment_id),
                ),
                summary,
                failures,
            )
        )

    def live(self, request: HttpRequest, key: str) -> Live | None:
        run_id = _uuid_param(request, "run")
        # A live block holds one table, so the failures refresh as their own block on the same schedule.
        if key in ("run", "run-failures") and run_id is not None:
            run = staff.get_recalculation(run_id)
            if run is None:
                return None
            return Live(
                key=key,
                block=_recalculation_summary(run) if key == "run" else _failures_table(run),
                refresh_seconds=None if run.is_terminal else REFRESH_SECONDS_WHILE_RUNNING,
            )
        if key == "runs" and run_id is None:
            experiment_id = _int_param(request, "experiment")
            return _runs_live(staff.list_recalculations(experiment_id, RECENT_RUNS), show_experiment=True)
        return None

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        run_id = _uuid_param(request, "run")
        if run_id is None:
            return []
        run = staff.get_recalculation(run_id)
        if run is None:
            return []
        operations = []
        if not run.is_terminal:
            operations += [
                ToolOperation(
                    key="mark-failed",
                    label="Mark as failed",
                    handler=MarkRecalculationTerminal(run.id, failed=True),
                    danger=True,
                    form_class=ReasonForm,
                    description=f"Stops the workflow of recalculation {run.id} of experiment {run.experiment_id}, "
                    f"team {run.team_id}, and marks the run failed.",
                    undo_hint="This cannot be undone. Start a new recalculation to compute the metrics again.",
                ),
                ToolOperation(
                    key="mark-completed",
                    label="Mark as completed",
                    handler=MarkRecalculationTerminal(run.id, failed=False),
                    danger=True,
                    form_class=ReasonForm,
                    description=f"Stops the workflow of recalculation {run.id} of experiment {run.experiment_id}, "
                    f"team {run.team_id}, and marks the run completed. "
                    "The experiment shows the results the run saved so far.",
                    undo_hint="This cannot be undone. Start a new recalculation to compute the metrics again.",
                ),
            ]
        # A recalculation needs a start date, so a run of a draft experiment offers no new run.
        experiment = staff.get_experiment(run.experiment_id)
        if experiment is None or not experiment.is_launched:
            return operations
        # Retrying failures reruns the latest finished run's failures, so it lives on the experiment page only.
        return operations + _start_operations(run.experiment_id, None)


for old in ("migrate", "fix-properties", "start-recalculation"):
    console.register_moved_page(
        old_path=f"admin/experiments/experiment/<int:object_id>/{old}/",
        title="This experiment action",
        url="/admin/console/tools/experiments/?experiment={object_id}",
    )
console.register_moved_page(
    old_path="admin/experiments/experimentsavedmetric/<int:object_id>/migrate/",
    title="Migrating a shared metric",
    url="/admin/console/tools/experiments/?saved_metric={object_id}",
)
for old in ("mark-failed", "mark-completed", "start", "retry-failures"):
    console.register_moved_page(
        old_path=f"admin/experiments/experimentmetricsrecalculation/<uuid:object_id>/{old}/",
        title="This recalculation action",
        url="/admin/console/tools/experiment-recalculations/?run={object_id}",
    )
