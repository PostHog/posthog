"""Staff page for the SES events dead-letter queues: what is waiting, and replay runs with their results."""

import json
from datetime import UTC, datetime
from typing import Any, cast

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

import structlog
from botocore.exceptions import BotoCoreError, ClientError

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.workflows.backend.services.ses_events_dlq import (
    DlqQueue,
    QueueSnapshot,
    ReplayOptions,
    configured_queues,
    find_queue,
    inspect_queue,
    sqs_client,
)
from products.workflows.backend.services.ses_events_dlq_runs import ACTIVE_STATUSES, finish_run, recent_runs, start_run
from products.workflows.backend.tasks.ses_events_dlq import replay_ses_events_dlq_task

logger = structlog.get_logger(__name__)

PAGE_URL_NAME = "workflows_ses_events_dlq"
REPLAY_URL_NAME = "workflows_ses_events_dlq_replay"


class ReplayForm(forms.Form):
    queue = forms.CharField()
    dry_run = forms.BooleanField(required=False)
    limit = forms.IntegerField(min_value=1, max_value=10_000, initial=500)
    max_per_second = forms.FloatField(min_value=0.1, max_value=100, initial=20)


@frozen
class _QueueView:
    name: str
    snapshot: QueueSnapshot | None
    oldest_age: str | None
    error: str | None


def _age(since: datetime | None) -> str | None:
    if since is None:
        return None
    minutes = int((datetime.now(UTC) - since).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


def _queue_view(queue: DlqQueue) -> _QueueView:
    name = queue.name
    try:
        snapshot = inspect_queue(queue, sqs_client(queue))
    except (BotoCoreError, ClientError) as error:
        logger.warning("ses_events_dlq.inspect_failed", queue=name, error=str(error))
        return _QueueView(name=name, snapshot=None, oldest_age=None, error=str(error))
    return _QueueView(name=name, snapshot=snapshot, oldest_age=_age(snapshot.oldest_sampled_at), error=None)


def ses_events_dlq_view(request: HttpRequest) -> HttpResponse:
    if not request.user.is_staff:
        raise PermissionDenied
    runs = [
        {
            **run,
            "started_at": datetime.fromisoformat(run["started_at"]),
            "report_json": json.dumps(run["report"], indent=2) if run["report"] else "",
        }
        for run in recent_runs()
    ]
    context: dict[str, Any] = {
        **admin.site.each_context(request),
        "title": "SES events dead-letter queues",
        "queues": [_queue_view(queue) for queue in configured_queues()],
        "runs": runs,
        "has_active_run": any(run["status"] in ACTIVE_STATUSES for run in runs),
        "replay_url": reverse(f"admin:{REPLAY_URL_NAME}"),
        "default_limit": ReplayForm.base_fields["limit"].initial,
        "default_max_per_second": ReplayForm.base_fields["max_per_second"].initial,
    }
    return render(request, "admin/workflows/ses_events_dlq.html", context)


def ses_events_dlq_replay_view(request: HttpRequest) -> HttpResponse:
    if not request.user.is_staff:
        raise PermissionDenied
    if request.method != "POST":
        return HttpResponseNotAllowed(permitted_methods=["POST"])
    page_url = reverse(f"admin:{PAGE_URL_NAME}")

    form = ReplayForm(request.POST)
    queue = find_queue(form.data.get("queue", "")) if form.is_valid() else None
    if queue is None:
        messages.error(request, f"Could not start the replay: {form.errors.as_text() or 'unknown queue'}")
        return HttpResponseRedirect(page_url)

    options = ReplayOptions(
        dry_run=form.cleaned_data["dry_run"],
        limit=form.cleaned_data["limit"],
        max_per_second=form.cleaned_data["max_per_second"],
    )
    # admin_view lets only staff through, so the user is a real User.
    triggered_by = cast(User, request.user).email
    run_id = start_run(queue, options, triggered_by)
    if run_id is None:
        messages.warning(request, f"A replay of {queue.name} is already running. Wait for it to finish.")
        return HttpResponseRedirect(page_url)

    try:
        replay_ses_events_dlq_task.delay(
            run_id=run_id,
            queue_name=queue.name,
            dry_run=options.dry_run,
            limit=options.limit,
            max_per_second=options.max_per_second,
            triggered_by=triggered_by,
        )
    except Exception as error:
        logger.exception("ses_events_dlq.replay_not_queued", run_id=run_id, queue=queue.name)
        finish_run(run_id, queue.name, status="failed", error=f"Could not queue the task: {type(error).__name__}")
        messages.error(request, f"Could not start the replay of {queue.name}. Try again in a minute.")
        return HttpResponseRedirect(page_url)
    logger.info("ses_events_dlq.replay_requested", run_id=run_id, queue=queue.name, triggered_by=triggered_by)
    kind = "Dry run" if options.dry_run else "Replay"
    messages.success(request, f"{kind} of {queue.name} started. Its progress shows below.")
    return HttpResponseRedirect(page_url)
