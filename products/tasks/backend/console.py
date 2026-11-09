from typing import cast

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from posthog.admin.console.panels import Owner
from posthog.admin.console.registry import console
from posthog.admin.console.tools import ConsoleTool, Notice, Page, ToolOperation
from posthog.models.user import User

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
