import dataclasses
from uuid import UUID

from django.db import IntegrityError

import structlog
from pydantic import TypeAdapter, ValidationError

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskDetailDTO

from ..facade.contracts import AdapterVerdict, DocsRequest, IntakeOutcome, InvalidAdapterVerdict
from ..feature_flags import is_agent_launch_enabled, open_pull_requests_flag_state
from ..settings import WriterSettings, writer_settings
from .caps import (
    OPEN_PULL_REQUEST_CAP,
    WriterRerunTaken,
    WriterSectionBusy,
    alert_cap_reached,
    daily_run_cap_reached,
    in_flight_writer_runs,
)
from .launch import start_writer
from .pull_requests import capture_writer_event, open_writer_pull_requests, source_repository_github
from .records import HELD_REQUESTS_STATE_KEY, WriterPullRequest, request_json, stored_request
from .routing import route_request

logger = structlog.get_logger(__name__)

VERDICT_EVENT = "knowledge_writer verdict"
RETRIED_HELD_STATUSES = frozenset({"capped"})

_verdict_validator = TypeAdapter(AdapterVerdict)


def parse_verdict(payload: object) -> AdapterVerdict:
    try:
        return _verdict_validator.validate_python(payload)
    except (ValidationError, ValueError) as error:
        raise InvalidAdapterVerdict(str(error)) from error


def submit(payload: object, *, team_id: int) -> IntakeOutcome:
    verdict = parse_verdict(payload)
    outcome = intake_outcome(verdict, team_id=team_id)
    logger.info(
        "knowledge_writer_intake_outcome",
        source=verdict.source,
        subject_id=verdict.subject_id,
        team_id=team_id,
        failure_reason=verdict.failure_reason,
        dedupe_id=verdict.request.dedupe_id if verdict.request else None,
        status=outcome.status,
        task_id=str(outcome.task_id) if outcome.task_id else None,
    )
    return outcome


def intake_outcome(verdict: AdapterVerdict, *, team_id: int) -> IntakeOutcome:
    writer = writer_settings()
    if writer is None or writer.team_id != team_id:
        return IntakeOutcome(status="unconfigured")
    capture_verdict(verdict, team_id=team_id)
    if verdict.request is None:
        return IntakeOutcome(status="no_docs")
    return launch_request(verdict.request, writer=writer)


def launch_request(request: DocsRequest, *, writer: WriterSettings) -> IntakeOutcome:
    team_id = writer.team_id
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
    if routing.is_every_page_in_source_repository:
        return IntakeOutcome(status="docs_in_source_repo")
    in_flight = in_flight_writer_runs(writer)
    busy_task_id = in_flight.busy_task_id_by_section.get(routing.section) if routing.section else None
    if busy_task_id is not None:
        hold_request(busy_task_id, request, team_id)
        return IntakeOutcome(status="section_busy")
    open_pull_requests = open_writer_pull_requests(writer)
    if open_pull_requests is None:
        alert_cap_reached("open_pull_request_lookup", team_id=team_id, dedupe_id=request.dedupe_id)
        return IntakeOutcome(status="capped")
    joinable = pull_request_to_join(open_pull_requests, routing.section)
    is_opening_pull_requests = open_pull_requests_flag_state(team)
    if joinable is not None and is_opening_pull_requests is None:
        return IntakeOutcome(status="section_busy")
    joining = joinable if is_opening_pull_requests else None
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
    except WriterSectionBusy as busy:
        hold_request(busy.busy_task_id, request, team_id)
        return IntakeOutcome(status="section_busy")
    except (WriterRerunTaken, tasks_facade.TaskDoneError):
        return IntakeOutcome(status="duplicate", task_id=existing_task.id if existing_task is not None else None)
    if joining is not None:
        return IntakeOutcome(status="joined", task_id=task_id, pull_request_url=joining.url)
    return IntakeOutcome(status="started", task_id=task_id)


def hold_request(task_id: UUID, request: DocsRequest, team_id: int) -> None:
    def append(current: object) -> tuple[object, None]:
        held = current if isinstance(current, list) else []
        if any(isinstance(entry, dict) and entry.get("dedupe_id") == request.dedupe_id for entry in held):
            return held, None
        return [*held, request_json.dump_python(request, mode="json")], None

    tasks_facade.update_task_state_entry(task_id, team_id, HELD_REQUESTS_STATE_KEY, append)
    logger.info("knowledge_writer_request_held", task_id=str(task_id), team_id=team_id, dedupe_id=request.dedupe_id)


def start_held_requests(team_id: int) -> None:
    writer = writer_settings()
    if writer is None or writer.team_id != team_id:
        return
    held_task_ids = tasks_facade.owner_origin_task_ids_with_state_entry(
        team_id=team_id,
        created_by_id=writer.user_id,
        origin_product=tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER,
        key=HELD_REQUESTS_STATE_KEY,
    )
    busy_task_ids = set(in_flight_writer_runs(writer).busy_task_id_by_section.values())
    for task_id in held_task_ids - busy_task_ids:
        start_requests_held_on(task_id, writer)


def start_requests_held_on(task_id: UUID, writer: WriterSettings) -> None:
    team_id = writer.team_id
    held = tasks_facade.update_task_state_entry(
        task_id, team_id, HELD_REQUESTS_STATE_KEY, lambda current: (None, current)
    )
    pending = [stored_request(entry) for entry in held] if isinstance(held, list) else []
    for index, request in enumerate(pending):
        outcome = launch_held_request(task_id, request, writer)
        if outcome is None or outcome.status in RETRIED_HELD_STATUSES:
            hold_request(task_id, request, team_id)
            continue
        if outcome.status in ("started", "joined") and outcome.task_id is not None:
            for later_request in pending[index + 1 :]:
                hold_request(outcome.task_id, later_request, team_id)
            return


def launch_held_request(held_on_task_id: UUID, request: DocsRequest, writer: WriterSettings) -> IntakeOutcome | None:
    log = logger.bind(held_on_task_id=str(held_on_task_id), team_id=writer.team_id, dedupe_id=request.dedupe_id)
    try:
        outcome = launch_request(request, writer=writer)
    except Exception as error:
        log.warning("knowledge_writer_held_request_failed", error_type=type(error).__name__)
        capture_exception(error, {"team_id": writer.team_id, "dedupe_id": request.dedupe_id})
        return None
    log.info(
        "knowledge_writer_held_request_launched",
        status=outcome.status,
        task_id=str(outcome.task_id) if outcome.task_id else None,
    )
    return outcome


def pull_request_to_join(open_pull_requests: list[WriterPullRequest], section: str | None) -> WriterPullRequest | None:
    if not section:
        return None
    return next((pull_request for pull_request in open_pull_requests if pull_request.section == section), None)


def latest_run_failed(task: TaskDetailDTO) -> bool:
    return task.latest_run is not None and task.latest_run.status == tasks_facade.TaskRunStatus.FAILED


def capture_verdict(verdict: AdapterVerdict, *, team_id: int) -> None:
    request = verdict.request
    trace = verdict.trace
    capture_writer_event(
        VERDICT_EVENT,
        team_id=team_id,
        event_key=f"{verdict.source}:{verdict.subject_id}:{verdict.check_id}",
        failure_log="knowledge_writer_verdict_capture_failed",
        properties={
            "source": verdict.source,
            "subject_id": verdict.subject_id,
            "needs_docs": verdict.needs_docs,
            "reason": verdict.reason,
            "failure_reason": verdict.failure_reason,
            "change_kind": request.change_kind if request else None,
            "repository": trace.repository if trace else None,
            "pull_request_number": trace.pull_request_number if trace else None,
            "low_confidence": trace.low_confidence if trace else False,
            "criteria": [dataclasses.asdict(row) for row in trace.criteria] if trace else [],
            "dedupe_id": request.dedupe_id if request else None,
            "requested_by": request.requested_by if request else None,
            "requested_by_user_id": request.requested_by_user_id if request else None,
            "team_id": team_id,
        },
    )
