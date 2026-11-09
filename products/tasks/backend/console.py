from typing import cast

from django import forms
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from posthog.admin.console.panels import Fact, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import ConsoleTool, Notice, Page, ToolOperation
from posthog.models.user import User

from products.tasks.backend.facade.api import get_desktop_beta_terms_acceptance, revoke_desktop_beta_terms
from products.tasks.backend.facade.run_logs import staff_task_run_log_link

AGENT_INFRASTRUCTURE = Owner(name="Agent infrastructure", crest="agent-infrastructure")

RUN_LOGS_TOOL_KEY = "task-run-logs"


class TaskRunForm(forms.Form):
    run = forms.UUIDField(label="Task run ID")


def download_logs(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    link = staff_task_run_log_link(form.cleaned_data["run"], cast(User, request.user))
    if link is None:
        form.add_error("run", "No task run with this ID in your organizations.")
        return HttpResponse(status=404)
    if link.url is None:
        messages.warning(request, link.unavailable_reason or "This run's logs are unavailable.")
        return HttpResponse(status=404)
    return HttpResponseRedirect(link.url)


@console.register_tool
class TaskRunLogsTool(ConsoleTool):
    key = RUN_LOGS_TOOL_KEY
    title = "Task run logs"
    owner = AGENT_INFRASTRUCTURE
    group = "Data"
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
