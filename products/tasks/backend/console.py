import uuid
from functools import partial
from typing import cast

from django import forms
from django.conf import settings
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.template.defaultfilters import filesizeformat

import structlog

from posthog.admin.console.panels import Fact, Gate, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Live, Notice, Page, Row, Table, ToolOperation
from posthog.models.user import User

from products.tasks.backend.facade.api import get_desktop_beta_terms_acceptance, revoke_desktop_beta_terms
from products.tasks.backend.facade.orphaned_objects import (
    KIND_LABELS,
    KIND_NAMES,
    OrphanedObjectsRun,
    recent_orphaned_objects_runs,
    start_orphaned_objects_run,
)
from products.tasks.backend.facade.run_logs import staff_task_run_log_link
from products.tasks.backend.presentation.views.infrastructure_admin import infrastructure_admin

logger = structlog.get_logger(__name__)

AGENT_INFRASTRUCTURE = Owner(
    name="Agent infrastructure", crest="agent-infrastructure", staff_group="Agent Infrastructure Team"
)

RUN_LOGS_TOOL_KEY = "task-run-logs"
RELEASE_PIPELINE_TOOL_KEY = "agent-release-pipeline"
ORPHANED_OBJECTS_TOOL_KEY = "orphaned-task-objects"
ALL_KINDS = "all"
MAX_PREFIXES_LIMIT = 100_000
REFRESH_SECONDS = 30
RUNNING_STATUSES = ("RUNNING", "CONTINUED_AS_NEW")
STATUS_TONES = {
    "RUNNING": Tone.INFO,
    "CONTINUED_AS_NEW": Tone.INFO,
    "COMPLETED": Tone.SUCCESS,
    "FAILED": Tone.DESTRUCTIVE,
    "TERMINATED": Tone.DESTRUCTIVE,
    "TIMED_OUT": Tone.DESTRUCTIVE,
    "CANCELED": Tone.WARNING,
}


class TaskRunForm(forms.Form):
    run = forms.UUIDField(label="Task run ID")


def download_logs(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    run_id = form.cleaned_data["run"]
    link = staff_task_run_log_link(run_id, cast(User, request.user))
    if link is None:
        form.add_error("run", "No task run with this ID in your organizations.")
        return HttpResponse(status=404)
    if link.url is None:
        messages.warning(request, link.unavailable_reason or "This run's logs are unavailable.")
        return HttpResponse(status=404)
    # console.js disables the submit button on submit, and a redirect to an attachment never reloads the page,
    # so the link goes on a result page to keep the form usable. Reloading the result page only creates a new link.
    return Page(
        blocks=(
            Notice(text="The download link expires after five minutes. Run the download again for a new link."),
            Table(columns=("Log",), rows=(Row(cells=(Cell(text=f"run_{run_id}.jsonl", href=link.url),)),)),
        )
    )


@console.register_tool
class TaskRunLogsTool(ConsoleTool):
    key = RUN_LOGS_TOOL_KEY
    title = "Task run logs"
    owner = AGENT_INFRASTRUCTURE
    group = "AI"
    description = "Downloads the log of one task run."

    def page(self, request: HttpRequest) -> Page:
        return Page(
            blocks=(
                Notice(
                    text=(
                        "Download the JSONL log of a task run. You can open runs of your own organizations only, and "
                        "runs in someone else's private channel stay hidden. The download link expires after five "
                        "minutes."
                    )
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="download",
                label="Download logs",
                handler=download_logs,
                form_class=TaskRunForm,
                form_initial={"run": request.GET.get("run", "")},
            )
        ]


@console.register_tool
class AgentReleasePipelineTool(ConsoleTool):
    key = RELEASE_PIPELINE_TOOL_KEY
    title = "Agent release pipeline"
    owner = AGENT_INFRASTRUCTURE
    group = "AI"
    description = "Follows the published agent package into sandbox images and regional custom builds."

    def app_page(self, request: HttpRequest) -> HttpResponse:
        return infrastructure_admin(request)


def revoke_beta_terms(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    revoke_desktop_beta_terms(obj.pk, cast(User, request.user))
    messages.success(request, "Revoked the PostHog Desktop beta terms. An organization admin can accept them again.")
    return None


@console.register_panel
class PostHogDesktopPanel(Panel):
    record = "organization"
    key = "posthog-desktop"
    title = "PostHog Desktop"
    owner = AGENT_INFRASTRUCTURE

    def facts(self, obj: Model) -> list[Fact]:
        if get_desktop_beta_terms_acceptance(obj.pk).is_desktop_beta_terms_accepted:
            return [Fact(label="Beta terms", value="Accepted", tone=Tone.SUCCESS)]
        return [Fact(label="Beta terms", value="Not accepted")]

    def operations(self, obj: Model) -> list[Operation]:
        if not get_desktop_beta_terms_acceptance(obj.pk).is_desktop_beta_terms_accepted:
            return []
        return [
            Operation(
                key="revoke-beta-terms",
                label="Revoke beta terms",
                handler=revoke_beta_terms,
                danger=True,
                form_class=ReasonForm,
                description="Removes the organization's acceptance of the PostHog Desktop beta terms.",
                undo_hint="An organization admin can accept the terms again in organization settings.",
            )
        ]


console.register_moved_page(
    old_path="admin/tasks/taskrun/<uuid:pk>/download-logs/",
    title="Downloading task run logs",
    url="/admin/console/tools/task-run-logs/download/?run={pk}",
)

console.register_moved_page(
    old_path="admin/tasks/task/infrastructure/",
    title="Agent release pipeline",
    url=f"/admin/console/tools/{RELEASE_PIPELINE_TOOL_KEY}/",
)


class OrphanedObjectsScanForm(forms.Form):
    kind = forms.ChoiceField(
        choices=[(ALL_KINDS, "All kinds"), *KIND_LABELS.items()], initial=ALL_KINDS, label="Objects"
    )
    max_prefixes = forms.IntegerField(
        min_value=1,
        max_value=MAX_PREFIXES_LIMIT,
        initial=100,
        label="Max deleted teams and organizations",
        help_text="The run stops after this many. Start small and raise it once a run looks right.",
    )

    def kinds(self) -> list[str]:
        kind = self.cleaned_data["kind"]
        return list(KIND_NAMES) if kind == ALL_KINDS else [kind]


class OrphanedObjectsDeleteForm(OrphanedObjectsScanForm):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


def _form_nonce(request: HttpRequest) -> uuid.UUID:
    try:
        return uuid.UUID(request.POST.get("form_nonce", ""))
    except ValueError:
        return uuid.uuid4()


def start_run(request: HttpRequest, form: forms.Form | None, *, execute: bool) -> HttpResponse | Page | None:
    assert isinstance(form, OrphanedObjectsScanForm)
    try:
        workflow_id = start_orphaned_objects_run(
            _form_nonce(request),
            execute=execute,
            kinds=form.kinds(),
            max_prefixes=form.cleaned_data["max_prefixes"],
            requested_by=cast(User, request.user).email,
        )
    except Exception:
        logger.exception("admin_console_orphaned_task_objects_start_failed", execute=execute)
        messages.error(request, "Could not start the run. Check the server logs for details.")
        return HttpResponse(status=502)
    if workflow_id is None:
        messages.warning(request, "No new run started. This form already started this run, shown below.")
    else:
        messages.success(request, f"Started {workflow_id}.")
    return None


def _temporal_url(run: OrphanedObjectsRun) -> str:
    return (
        f"{settings.TEMPORAL_UI_HOST}/namespaces/{settings.TEMPORAL_NAMESPACE}/workflows/{run.workflow_id}/{run.run_id}"
    )


def _started_label(run: OrphanedObjectsRun) -> str:
    return run.started.strftime("%Y-%m-%d %H:%M") if run.started else run.workflow_id


def _kinds_label(kinds: tuple[str, ...]) -> str:
    if set(kinds) == set(KIND_NAMES):
        return "All kinds"
    return ", ".join(KIND_LABELS.get(kind, kind) for kind in kinds)


def _orphaned_objects_row(run: OrphanedObjectsRun) -> Row:
    mode = Cell(text="Delete", tone=Tone.DESTRUCTIVE) if run.execute else Cell(text="Scan")
    status = Cell(text=run.status.replace("_", " ").capitalize(), tone=STATUS_TONES.get(run.status))
    totals = run.totals
    if totals is None:
        counts = tuple(Cell(text="-", muted=True) for _ in range(4))
    else:
        counts = (
            Cell(text=f"{totals.prefixes:,} of {run.max_prefixes:,}"),
            Cell(text=f"{totals.objects:,}"),
            Cell(text=filesizeformat(totals.size_bytes)),
            Cell(text=f"{totals.failures():,}", tone=Tone.DESTRUCTIVE if totals.failures() else None),
        )
    return Row(
        cells=(
            Cell(text=_started_label(run), href=_temporal_url(run)),
            mode,
            Cell(text=_kinds_label(run.kinds)),
            status,
            *counts,
        )
    )


@console.register_tool
class OrphanedTaskObjectsTool(ConsoleTool):
    key = ORPHANED_OBJECTS_TOOL_KEY
    title = "Orphaned task objects"
    owner = AGENT_INFRASTRUCTURE
    group = "Data deletion"
    description = "Finds and deletes the task logs, artifacts, agent memory and sessions of deleted teams."

    def page(self, request: HttpRequest) -> Page:
        runs = self.live(request, "runs")
        assert runs is not None
        return Page(
            blocks=(
                Notice(
                    text=(
                        "Task logs, artifacts, agent memory and task sessions stay in object storage after their team "
                        "or organization is deleted. A scan counts them and deletes nothing. A deletion checks again "
                        "that the team or organization is still gone before it deletes each batch."
                    )
                ),
                runs,
            )
        )

    def live(self, request: HttpRequest, key: str) -> Live | None:
        if key != "runs":
            return None
        runs = recent_orphaned_objects_runs()
        if runs is None:
            return Live(
                key="runs",
                block=Notice(text="Temporal did not answer, so the runs cannot be shown. This retries on its own."),
                refresh_seconds=REFRESH_SECONDS,
            )
        running = any(run.status in RUNNING_STATUSES for run in runs)
        return Live(
            key="runs",
            block=Table(
                title="Recent runs",
                columns=(
                    "Started",
                    "Mode",
                    "Objects",
                    "Status",
                    "Teams and organizations",
                    "Files",
                    "Size",
                    "Failures",
                ),
                rows=tuple(_orphaned_objects_row(run) for run in runs),
                empty_text="No scans or deletions have run yet.",
                numeric_columns=(5, 6, 7),
            ),
            refresh_seconds=REFRESH_SECONDS if running else None,
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="scan",
                label="Scan for orphaned objects",
                handler=partial(start_run, execute=False),
                form_class=OrphanedObjectsScanForm,
                description="Counts the objects of deleted teams and organizations. Deletes nothing.",
            ),
            ToolOperation(
                key="delete",
                label="Delete orphaned objects",
                handler=partial(start_run, execute=True),
                danger=True,
                form_class=OrphanedObjectsDeleteForm,
                gate=Gate.owner(),
                description="Deletes the objects of deleted teams and organizations from object storage.",
                undo_hint="Deleted objects cannot be restored. Run a scan first to see what would be deleted.",
            ),
        ]
