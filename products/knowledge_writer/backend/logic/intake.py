import dataclasses
from uuid import UUID

from django.db import IntegrityError, connection

import structlog
from pydantic import TypeAdapter, ValidationError

from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.tasks.backend.facade import api as tasks_facade

from ..facade.contracts import AdapterVerdict, IntakeOutcome, InvalidAdapterVerdict
from ..feature_flags import is_agent_launch_enabled
from ..settings import WriterSettings, writer_settings
from .caps import (
    OPEN_PULL_REQUEST_CAP,
    WriterCapReached,
    alert_cap_reached,
    daily_run_cap_reached,
    in_flight_writer_run_count,
)
from .grounding import read_source_diff
from .launch import rules_file_paths, start_writer
from .pull_requests import (
    GITHUB_READ_ERRORS,
    OpenPullRequestsUnavailable,
    capture_writer_event,
    docs_github,
    open_writer_pull_requests,
    source_github,
    source_repository_github,
)
from .records import (
    BASE_SHA_STATE_KEY,
    LEGACY_HELD_REQUESTS_STATE_KEY,
    PULL_REQUEST_STATE_KEY,
    DocsRequest,
    source_change_of,
    stored_request,
    task_request,
)
from .routing import route_request
from .server_commit import DocsCommitFailed, base_tree, docs_branch_head

logger = structlog.get_logger(__name__)

VERDICT_EVENT = "knowledge_writer verdict"
MAX_RULES_FILE_BYTES = 256 * 1024
MAX_RULES_TOTAL_BYTES = 1024 * 1024

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


class WriterLaunchDeferred(Exception):
    pass


def intake_outcome(verdict: AdapterVerdict, *, team_id: int) -> IntakeOutcome:
    writer = writer_settings()
    if writer is None or writer.team_id != team_id:
        return IntakeOutcome(status="unconfigured")
    outcome = launch_outcome(verdict, writer, team_id=team_id)
    capture_verdict(verdict, team_id=team_id)
    return outcome


def launch_outcome(verdict: AdapterVerdict, writer: WriterSettings, *, team_id: int) -> IntakeOutcome:
    if verdict.request is None:
        return IntakeOutcome(status="no_docs")
    return launch_request(verdict.request, writer, team_id=team_id)


def launch_request(
    request: DocsRequest, writer: WriterSettings, *, team_id: int, replacing_task_id: UUID | None = None
) -> IntakeOutcome:
    existing_task = tasks_facade.get_task_by_origin_key(team_id, request.dedupe_id)
    if existing_task is not None and existing_task.id != replacing_task_id:
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
    try:
        base_sha = docs_base_sha(writer)
        open_pull_requests = open_writer_pull_requests(writer)
        rules_text_by_path = (
            {} if base_sha is None else docs_rules_texts(writer, base_sha, rules_file_paths(request, routing, writer))
        )
    except (*GITHUB_READ_ERRORS, OpenPullRequestsUnavailable, DocsCommitFailed) as error:
        raise WriterLaunchDeferred("the docs repository could not be read") from error
    if base_sha is None:
        return IntakeOutcome(status="unconfigured")
    if open_pull_requests is None:
        alert_cap_reached("open_pull_request_lookup", team_id=team_id, dedupe_id=request.dedupe_id)
        return IntakeOutcome(status="capped")
    listed_open_count = len(open_pull_requests)
    source_change = source_change_of(request)
    try:
        task_id = start_writer(
            request,
            routing,
            team=team,
            writer=writer,
            base_sha=base_sha,
            source_diff=read_source_diff(source_github(team_id, source_change, writer.docs_repository), source_change),
            rules_text_by_path=rules_text_by_path,
            before_task_create=lambda: admit_launch(writer, listed_open_count, request, replacing_task_id),
        )
    except WriterCapReached:
        alert_cap_reached("open_pull_request", team_id=team_id, dedupe_id=request.dedupe_id)
        return IntakeOutcome(status="capped")
    except IntegrityError:
        return IntakeOutcome(status="duplicate")
    return IntakeOutcome(status="started", task_id=task_id)


def relaunch_run_without_base(task_run_id: UUID, *, team_id: int) -> bool:
    writer = writer_settings()
    run = tasks_facade.get_task_run(task_run_id, team_id)
    if writer is None or writer.team_id != team_id or run is None:
        return False
    if run.task_origin_product != tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER:
        return False
    if tasks_facade.read_task_state_entry(run.task_id, team_id, BASE_SHA_STATE_KEY) is not None:
        return False
    if tasks_facade.read_task_state_entry(run.task_id, team_id, PULL_REQUEST_STATE_KEY) is not None:
        return False
    try:
        request = task_request(run.task_id, team_id)
    except ValidationError:
        return False
    outcome = launch_request(request, writer, team_id=team_id, replacing_task_id=run.task_id)
    logger.info(
        "knowledge_writer_run_relaunched",
        task_run_id=str(task_run_id),
        team_id=team_id,
        dedupe_id=request.dedupe_id,
        status=outcome.status,
        task_id=str(outcome.task_id) if outcome.task_id else None,
    )
    return outcome.status in ("started", "duplicate")


def drain_legacy_held_requests() -> None:
    writer = writer_settings()
    if writer is None:
        return
    held_task_ids = tasks_facade.owner_origin_task_ids_with_state_entry(
        team_id=writer.team_id,
        created_by_id=writer.user_id,
        origin_product=tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER,
        key=LEGACY_HELD_REQUESTS_STATE_KEY,
    )
    for task_id in held_task_ids:
        if not relaunch_requests_held_on(task_id, writer):
            return


def relaunch_requests_held_on(task_id: UUID, writer: WriterSettings) -> bool:
    held = tasks_facade.read_task_state_entry(task_id, writer.team_id, LEGACY_HELD_REQUESTS_STATE_KEY)
    for entry in held if isinstance(held, list) else []:
        if not is_held_entry_settled(task_id, entry, writer):
            return False
        remove_held_entry(task_id, entry, writer.team_id)
    return True


def is_held_entry_settled(task_id: UUID, entry: object, writer: WriterSettings) -> bool:
    log = logger.bind(held_on_task_id=str(task_id), team_id=writer.team_id)
    try:
        request = stored_request(entry)
    except ValidationError:
        log.warning("knowledge_writer_held_request_unreadable")
        return True
    try:
        outcome = launch_request(request, writer, team_id=writer.team_id)
    except Exception as error:
        log.warning("knowledge_writer_held_request_failed", error_type=type(error).__name__)
        capture_exception(error, {"team_id": writer.team_id, "dedupe_id": request.dedupe_id})
        return False
    log.info("knowledge_writer_held_request_launched", dedupe_id=request.dedupe_id, status=outcome.status)
    return outcome.status not in ("capped", "shadow")


def remove_held_entry(task_id: UUID, entry: object, team_id: int) -> None:
    def remove(current: object) -> tuple[object, None]:
        held = current if isinstance(current, list) else []
        return [kept for kept in held if kept != entry] or None, None

    tasks_facade.update_task_state_entry(task_id, team_id, LEGACY_HELD_REQUESTS_STATE_KEY, remove)


def admit_launch(
    writer: WriterSettings, open_pull_request_count: int, request: DocsRequest, replacing_task_id: UUID | None
) -> None:
    admit_under_open_pull_request_cap(writer, open_pull_request_count)
    if replacing_task_id is not None:
        tasks_facade.release_task_origin_key(writer.team_id, request.dedupe_id)


def admit_under_open_pull_request_cap(writer: WriterSettings, open_pull_request_count: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"knowledge-writer-open-pull-request-cap:{writer.team_id}:{writer.user_id}"],
        )
    if open_pull_request_count + in_flight_writer_run_count(writer) >= OPEN_PULL_REQUEST_CAP:
        raise WriterCapReached("open_pull_request")


def docs_base_sha(writer: WriterSettings) -> str | None:
    github = docs_github(writer.team_id, writer.docs_repository.split("/", 1)[0], priority=Priority.NORMAL)
    if github is None:
        return None
    return docs_branch_head(github, writer.docs_repository)


def docs_rules_texts(writer: WriterSettings, base_sha: str, rules_paths: frozenset[str]) -> dict[str, str]:
    github = docs_github(writer.team_id, writer.docs_repository.split("/", 1)[0], priority=Priority.NORMAL)
    if github is None:
        return {}
    texts = base_tree(github, writer.docs_repository, base_sha, rules_paths, max_text_bytes=MAX_RULES_FILE_BYTES).texts
    kept_texts: dict[str, str] = {}
    kept_bytes = 0
    for path in sorted(texts, key=lambda rules_path: (rules_path.count("/"), rules_path)):
        text = texts[path]
        if text is None or kept_bytes + len(text.encode()) > MAX_RULES_TOTAL_BYTES:
            continue
        kept_texts[path] = text
        kept_bytes += len(text.encode())
    return kept_texts


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
