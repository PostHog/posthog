import uuid

from django.db import IntegrityError

import structlog
import posthoganalytics
from pydantic import TypeAdapter, ValidationError

from posthog.models.team import Team

from products.tasks.backend.facade import api as tasks_facade

from ..facade.contracts import AdapterVerdict, IntakeOutcome, InvalidAdapterVerdict
from ..feature_flags import is_agent_launch_enabled
from ..settings import writer_settings
from .launch import start_writer

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
    if existing_task is not None:
        return IntakeOutcome(status="duplicate", task_id=existing_task.id)
    team = Team.objects.get(id=team_id)
    if not is_agent_launch_enabled(team):
        return IntakeOutcome(status="shadow")
    try:
        task_id = start_writer(request, team=team, writer=writer)
    except IntegrityError:
        return IntakeOutcome(status="duplicate")
    return IntakeOutcome(status="started", task_id=task_id)


def capture_verdict(verdict: AdapterVerdict, *, team_id: int) -> None:
    request = verdict.request
    try:
        posthoganalytics.capture(
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
                "team_id": team_id,
            },
        )
    except Exception:
        logger.warning("knowledge_writer_verdict_capture_failed", team_id=team_id, exc_info=True)
