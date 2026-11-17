import dataclasses

from django.db import IntegrityError

import structlog
from pydantic import TypeAdapter, ValidationError

from posthog.egress.limiter.policies import Priority
from posthog.models.team import Team

from products.tasks.backend.facade import api as tasks_facade

from ..facade.contracts import AdapterVerdict, IntakeOutcome, InvalidAdapterVerdict
from ..feature_flags import is_agent_launch_enabled
from ..settings import WriterSettings, writer_settings
from .caps import OPEN_PULL_REQUEST_CAP, alert_cap_reached, daily_run_cap_reached, in_flight_writer_run_count
from .launch import start_writer
from .pull_requests import capture_writer_event, docs_github, open_writer_pull_requests, source_repository_github
from .routing import route_request
from .server_commit import docs_branch_head

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
    request = verdict.request
    if request is None:
        return IntakeOutcome(status="no_docs")
    existing_task = tasks_facade.get_task_by_origin_key(team_id, request.dedupe_id)
    if existing_task is not None:
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
    base_sha = docs_base_sha(writer)
    if base_sha is None:
        return IntakeOutcome(status="unconfigured")
    open_pull_requests = open_writer_pull_requests(writer)
    if open_pull_requests is None:
        alert_cap_reached("open_pull_request_lookup", team_id=team_id, dedupe_id=request.dedupe_id)
        return IntakeOutcome(status="capped")
    if len(open_pull_requests) + in_flight_writer_run_count(writer) >= OPEN_PULL_REQUEST_CAP:
        alert_cap_reached("open_pull_request", team_id=team_id, dedupe_id=request.dedupe_id)
        return IntakeOutcome(status="capped")
    try:
        task_id = start_writer(request, routing, team=team, writer=writer, base_sha=base_sha)
    except IntegrityError:
        return IntakeOutcome(status="duplicate")
    return IntakeOutcome(status="started", task_id=task_id)


def docs_base_sha(writer: WriterSettings) -> str | None:
    github = docs_github(writer.team_id, writer.docs_repository.split("/", 1)[0], priority=Priority.NORMAL)
    if github is None:
        return None
    return docs_branch_head(github, writer.docs_repository)


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
