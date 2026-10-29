import uuid

from django.db import IntegrityError

import structlog
from pydantic import TypeAdapter, ValidationError

from posthog.models.team import Team
from posthog.ph_client import ph_scoped_capture

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskDetailDTO

from ..facade.contracts import AdapterVerdict, IntakeOutcome, InvalidAdapterVerdict
from ..feature_flags import is_agent_launch_enabled
from ..settings import writer_settings
from .caps import (
    OPEN_PULL_REQUEST_CAP,
    WriterSectionBusy,
    alert_cap_reached,
    daily_run_cap_reached,
    in_flight_writer_runs,
)
from .launch import start_writer
from .pull_requests import open_writer_pull_requests, source_repository_github
from .records import WriterPullRequest
from .routing import route_request

logger = structlog.get_logger(__name__)

VERDICT_EVENT = "knowledge_writer verdict"

_verdict_validator = TypeAdapter(AdapterVerdict)


def parse_verdict(payload: object) -> AdapterVerdict:
    try:
        return _verdict_validator.validate_python(payload)
    except (ValidationError, ValueError) as error:
        raise InvalidAdapterVerdict(str(error)) from error


def submit(payload: object, *, team_id: int) -> IntakeOutcome:
    verdict = parse_verdict(payload)
    capture_verdict(verdict, team_id=team_id)
    request = verdict.request
    if request is None:
        return IntakeOutcome(status="no_docs")
    writer = writer_settings()
    if writer is None or writer.team_id != team_id:
        return IntakeOutcome(status="unconfigured")
    existing_task = tasks_facade.get_task_by_origin_key(team_id, request.dedupe_id)
    if existing_task is not None and not latest_run_failed(existing_task):
        return IntakeOutcome(status="duplicate", task_id=existing_task.id)
    team = Team.objects.get(id=team_id)
    if not is_agent_launch_enabled(team):
        return IntakeOutcome(status="shadow")
    if daily_run_cap_reached(writer):
        alert_cap_reached("daily_run", team_id=team_id, dedupe_id=request.dedupe_id)
        return IntakeOutcome(status="capped")
    routing = route_request(request, team_id=team_id, github=source_repository_github(team_id))
    in_flight = in_flight_writer_runs(writer)
    if routing.section and routing.section in in_flight.busy_sections:
        return IntakeOutcome(status="section_busy")
    open_pull_requests = open_writer_pull_requests(writer)
    if open_pull_requests is None:
        alert_cap_reached("open_pull_request_lookup", team_id=team_id, dedupe_id=request.dedupe_id)
        return IntakeOutcome(status="capped")
    joining = pull_request_to_join(open_pull_requests, routing.section)
    if joining is None and len(open_pull_requests) + in_flight.unpublished_runs >= OPEN_PULL_REQUEST_CAP:
        alert_cap_reached("open_pull_request", team_id=team_id, dedupe_id=request.dedupe_id)
        return IntakeOutcome(status="capped")
    try:
        task_id = start_writer(
            request,
            routing,
            team=team,
            writer=writer,
            joining=joining,
            rerun_task_id=existing_task.id if existing_task is not None else None,
        )
    except IntegrityError:
        return IntakeOutcome(status="duplicate")
    except WriterSectionBusy:
        return IntakeOutcome(status="section_busy")
    if joining is not None:
        return IntakeOutcome(status="joined", task_id=task_id, pull_request_url=joining.url)
    return IntakeOutcome(status="started", task_id=task_id)


def pull_request_to_join(open_pull_requests: list[WriterPullRequest], section: str | None) -> WriterPullRequest | None:
    if not section:
        return None
    return next((pull_request for pull_request in open_pull_requests if pull_request.section == section), None)


def latest_run_failed(task: TaskDetailDTO) -> bool:
    return task.latest_run is not None and task.latest_run.status == tasks_facade.TaskRunStatus.FAILED


def capture_verdict(verdict: AdapterVerdict, *, team_id: int) -> None:
    request = verdict.request
    try:
        with ph_scoped_capture() as capture:
            capture(
                VERDICT_EVENT,
                distinct_id=f"knowledge_writer:{team_id}",
                uuid=uuid.uuid5(uuid.NAMESPACE_URL, f"knowledge_writer:{verdict.source}:{verdict.subject_id}"),
                properties={
                    "source": verdict.source,
                    "subject_id": verdict.subject_id,
                    "needs_docs": verdict.needs_docs,
                    "reason": verdict.reason,
                    "change_kind": request.change_kind if request else None,
                    "dedupe_id": request.dedupe_id if request else None,
                    "requested_by": verdict.requested_by,
                    "requested_by_user_id": verdict.requested_by_user_id,
                    "team_id": team_id,
                },
            )
    except Exception:
        logger.warning("knowledge_writer_verdict_capture_failed", team_id=team_id, exc_info=True)
