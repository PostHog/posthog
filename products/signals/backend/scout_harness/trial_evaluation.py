from __future__ import annotations

import json
import asyncio
import hashlib
from dataclasses import field
from typing import Literal, TypeVar
from uuid import UUID

from django.utils import timezone

from pydantic import BaseModel, JsonValue, ValidationError

from posthog.clickhouse.query_tagging import private_capture_context
from posthog.dataclasses import frozen
from posthog.models import User
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.trial_evaluation_report import build_trial_comparison_report
from products.signals.backend.scout_harness.trial_evaluation_types import (
    TrialComparisonReport,
    TrialEvaluationCriterion,
    TrialEvaluationRequest,
    TrialEvaluationSnapshot,
    TrialEvidenceSource,
    TrialRunEvidence,
    TrialRunJudgment,
)
from products.signals.backend.scout_harness.trial_inspection import ScoutTrialInspection
from products.signals.backend.scout_harness.trial_launch import (
    ScoutTrialLaunchError,
    TrialContext,
    TrialLaunch,
    assert_trial_environment_ready,
    load_trial_context,
    read_trial_launch,
)
from products.signals.backend.scout_harness.trial_result import (
    export_trial_result,
    get_trial_workflow_status,
    read_trial_result,
)
from products.signals.backend.scout_harness.trial_rubrics import MockScoutRubricReader
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore
from products.tasks.backend.facade.api import get_task_run_log_size, get_task_run_log_urls, read_task_run_log_content

MAX_EVALUATION_RUNS = 20
MAX_EVALUATION_BYTES = 8 * 1024 * 1024
MAX_TRACE_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_CHARS = 80_000
MAX_SOURCE_CHARS = 12_000
MAX_EVIDENCE_SOURCES = 200
JUDGE_MODEL = "gpt-5.5"
JUDGE_PROMPT_VERSION = "1"
_Document = TypeVar("_Document", bound=BaseModel)


class TrialEvaluationError(ScoutTrialLaunchError):
    pass


@frozen
class _VariantSettings:
    model: str
    runtime_adapter: str
    reasoning_effort: str
    service_tier: str | None
    skill_body_sha256: str
    note: str = field(repr=False)


class _EvidenceBuilder:
    def __init__(self) -> None:
        self.sources: list[TrialEvidenceSource] = []
        self.limitations: list[str] = []
        self.remaining = MAX_EVIDENCE_CHARS

    def add(
        self,
        identifier: str,
        kind: Literal["instructions", "context", "summary", "report", "memory", "trace"],
        text: str,
    ) -> None:
        if not text:
            return
        limit = min(self.remaining, MAX_SOURCE_CHARS)
        marker = "\n[Evidence truncated]"
        if limit <= len(marker) or len(self.sources) >= MAX_EVIDENCE_SOURCES:
            limitation = "Some evidence sources were omitted because the evidence limit was reached."
            if limitation not in self.limitations:
                self.limitations.append(limitation)
            return
        if len(text) > limit:
            self.limitations.append(f"Evidence source {identifier} was truncated at {limit} characters.")
            bounded = text[: limit - len(marker)] + marker
        else:
            bounded = text
        self.sources.append(TrialEvidenceSource(id=identifier, kind=kind, text=bounded))
        self.remaining -= len(bounded)


def _key(team_id: int, evaluation_id: UUID, filename: str) -> str:
    return f"signals/scout-trials/{team_id}/evaluations/{evaluation_id}/{filename}.json"


def _read_document(key: str, document_type: type[_Document]) -> _Document | None:
    content = object_storage.read(key, missing_ok=True)
    if content is None:
        return None
    if len(content.encode()) > MAX_EVALUATION_BYTES:
        raise TrialEvaluationError("The saved evaluation exceeds its storage limit.")
    try:
        return document_type.model_validate_json(content)
    except ValidationError:
        raise TrialEvaluationError("The saved evaluation document is invalid.") from None


def _write_once(key: str, document: _Document) -> _Document:
    content = document.model_dump_json()
    if len(content.encode()) > MAX_EVALUATION_BYTES:
        raise TrialEvaluationError("The evaluation evidence is too large to save.")
    existing = _read_document(key, type(document))
    if existing is not None:
        return existing
    try:
        object_storage.write(key, content, extras={"ContentType": "application/json", "IfNoneMatch": "*"})
    except object_storage.ObjectStorageError:
        existing = _read_document(key, type(document))
        if existing is None:
            raise
        return existing
    return document


@private_capture_context()
def read_trial_evaluation(team_id: int, evaluation_id: UUID) -> TrialEvaluationSnapshot | None:
    snapshot = _read_document(_key(team_id, evaluation_id, "snapshot"), TrialEvaluationSnapshot)
    if snapshot is not None and (snapshot.team_id != team_id or snapshot.evaluation_id != evaluation_id):
        raise TrialEvaluationError("The saved evaluation does not match this project.")
    return snapshot


def _assert_context_access(context: TrialContext, *, config: SignalScoutConfig, user: User) -> None:
    if (
        config.team_id != 2
        or not user.is_staff
        or not user.is_active
        or context.team_id != config.team_id
        or context.config_id != config.id
        or context.user_id != user.id
        or context.skill_name != config.skill_name
    ):
        raise TrialEvaluationError("The evaluation is not available to this operator.")
    if not user.organization_memberships.filter(organization_id=config.team.organization_id).exists():
        raise TrialEvaluationError("The operator no longer has access to this project.")
    if not UserAccessControl(user=user, team=config.team).has_project_access:
        raise TrialEvaluationError("The operator no longer has access to this project.")
    inspection = ScoutTrialInspection(config, user)
    inspection._check_skill_access()
    inspection._check_skill_access(context.skill_version)


@private_capture_context()
def assert_evaluation_access(snapshot: TrialEvaluationSnapshot, *, config: SignalScoutConfig, user: User) -> None:
    if snapshot.team_id != config.team_id or snapshot.config_id != config.id or snapshot.user_id != user.id:
        raise TrialEvaluationError("The evaluation is not available to this operator.")
    _assert_context_access(load_trial_context(snapshot.team_id, snapshot.context_id), config=config, user=user)


def _assert_worker_access(snapshot: TrialEvaluationSnapshot) -> None:
    assert_trial_environment_ready()
    config = (
        SignalScoutConfig.objects.for_team(snapshot.team_id)
        .select_related("team")
        .filter(id=snapshot.config_id)
        .first()
    )
    user = User.objects.filter(id=snapshot.user_id, is_active=True).first()
    if config is None or user is None:
        raise TrialEvaluationError("The evaluation is no longer available to this operator.")
    assert_evaluation_access(snapshot, config=config, user=user)


def _request_hash(config: SignalScoutConfig, user: User, request: TrialEvaluationRequest) -> str:
    document = {
        "team_id": config.team_id,
        "config_id": str(config.id),
        "user_id": user.id,
        "request": request.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validate_groups(request: TrialEvaluationRequest) -> None:
    variants = [variant.id for variant in request.variants]
    launches = [identifier for variant in request.variants for identifier in variant.launch_ids]
    if len(set(variants)) != len(variants):
        raise TrialEvaluationError("Each variant must have a unique ID.")
    if request.baseline_variant_id not in variants:
        raise TrialEvaluationError("The baseline must be one of the selected variants.")
    if len(launches) > MAX_EVALUATION_RUNS or len(set(launches)) != len(launches):
        raise TrialEvaluationError("Choose at most 20 unique trial runs, each in exactly one variant.")


def _settings(launch: TrialLaunch) -> _VariantSettings:
    return _VariantSettings(
        model=launch.model,
        runtime_adapter=launch.runtime_adapter,
        reasoning_effort=launch.reasoning_effort,
        service_tier=launch.service_tier,
        skill_body_sha256=hashlib.sha256(launch.skill_body.encode()).hexdigest(),
        note=launch.note,
    )


def _bound_run(launch: TrialLaunch) -> SignalScoutRun | None:
    runs = list(
        SignalScoutRun.objects.for_team(launch.team_id)
        .select_related("task_run__task")
        .filter(
            scout_config_id=launch.config_id,
            metadata__scout_trial__launch_id=str(launch.id),
        )[:2]
    )
    if not runs:
        return None
    if len(runs) != 1:
        raise TrialEvaluationError("The trial launch does not identify exactly one run.")
    run = runs[0]
    task_run = run.task_run
    task = task_run.task
    marker = (run.metadata or {}).get("scout_trial")
    if (
        task_run.team_id != launch.team_id
        or task.team_id != launch.team_id
        or task.created_by_id != launch.user_id
        or task.deleted
        or task.origin_product != "signals_scout"
        or task.origin_key != f"scout-trial:{launch.id}"
        or not isinstance(marker, dict)
        or marker.get("version") != 1
        or marker.get("context_id") != str(launch.context_id)
        or (task_run.state or {}).get("scout_trial") != marker
    ):
        raise TrialEvaluationError("The trial does not match its private task and operator.")
    return run


def _add_trace(builder: _EvidenceBuilder, run: SignalScoutRun) -> None:
    from products.signals.backend.scout_harness.trial_judge import (  # noqa: PLC0415 -- keep judge dependencies off API startup
        evidence_sources_from_logs,
    )

    try:
        urls = get_task_run_log_urls(run.task_run_id, run.task_run.task_id, run.team_id)
        if not urls or urls != [run.task_run.log_url]:
            builder.limitations.append(
                "The exact trial trace was unavailable; inherited resume-chain logs were not read."
            )
            return
        size = get_task_run_log_size(urls)
        if size <= 0:
            builder.limitations.append("The trial trace was unavailable.")
            return
        if size > MAX_TRACE_BYTES:
            builder.limitations.append("The trial trace exceeded the 2 MiB read limit and was omitted.")
            return
        content = read_task_run_log_content(urls)
        if len(content.encode()) > MAX_TRACE_BYTES:
            builder.limitations.append("The trial trace exceeded the 2 MiB read limit and was omitted.")
            return
        trace = evidence_sources_from_logs(content)
        builder.limitations.extend(trace.limitations)
        for source in trace.sources:
            builder.add(source.id, source.kind, source.text)
    except Exception:
        builder.limitations.append("The trial trace could not be read; tool-use evidence is incomplete.")


def _usage(value: JsonValue, field: str) -> int | None:
    item = value.get(field) if isinstance(value, dict) else None
    return item if isinstance(item, int) and not isinstance(item, bool) and item >= 0 else None


def _run_evidence(launch: TrialLaunch, context: TrialContext, variant_id: UUID) -> TrialRunEvidence:
    run = _bound_run(launch)
    status = (
        run.task_run.status
        if run is not None
        else get_trial_workflow_status(team_id=launch.team_id, launch_id=launch.id).status
    )
    if status not in {"completed", "failed", "cancelled", "skipped"} or (run is None and status == "completed"):
        raise TrialEvaluationError("Every selected trial must have a known terminal state before scoring.")
    evidence = TrialRunEvidence(
        launch_id=launch.id,
        variant_id=variant_id,
        run_id=run.id if run else None,
        task_id=run.task_run.task_id if run else None,
        task_run_id=run.task_run_id if run else None,
        execution_status=status,
        exclusion_reason=None if status == "completed" else "The trial did not complete successfully.",
        model=launch.model,
        runtime_adapter=launch.runtime_adapter,
        reasoning_effort=launch.reasoning_effort,
        service_tier=launch.service_tier,
        skill_body_sha256=hashlib.sha256(launch.skill_body.encode()).hexdigest(),
    )
    if run is None or evidence.exclusion_reason:
        return evidence
    result = read_trial_result(run)
    if result is None:
        export_trial_result(run)
        result = read_trial_result(run)
    if result is None or result.get("launch_id") != str(launch.id) or result.get("context_id") != str(context.id):
        raise TrialEvaluationError("A selected trial result could not be frozen safely.")
    if (
        ScoutTrialStore(run).invalid_reason() is not None
        or result.get("valid_comparison") is not True
        or result.get("status") != "completed"
        or result.get("skill_body_sha256") != evidence.skill_body_sha256
        or result.get("runtime")
        != {field: getattr(launch, field) for field in ("model", "runtime_adapter", "reasoning_effort", "service_tier")}
        or any(
            (run.task_run.state or {}).get(field) != getattr(launch, field)
            for field in ("model", "runtime_adapter", "reasoning_effort", "service_tier")
        )
    ):
        return evidence.model_copy(
            update={"exclusion_reason": "The trial was invalidated or its execution settings changed."}
        )
    builder = _EvidenceBuilder()
    builder.add("instructions", "instructions", launch.skill_body)
    builder.add(
        "context",
        "context",
        json.dumps(
            {"note": launch.note, "memory": context.memory, "notes": context.notes, "recent_runs": context.recent_runs},
            ensure_ascii=False,
        ),
    )
    summary = result.get("summary")
    if isinstance(summary, str) and summary:
        builder.add("summary", "summary", summary)
    else:
        builder.limitations.append("The completed trial has no final summary.")
    private = result.get("private_state")
    if isinstance(private, dict):
        reports = private.get("reports")
        if isinstance(reports, dict):
            for index, (identifier, report) in enumerate(sorted(reports.items())):
                builder.add(
                    f"report:{index}",
                    "report",
                    json.dumps({"report_id": identifier, "report": report}, ensure_ascii=False),
                )
        builder.add("memory", "memory", json.dumps(private.get("memory", {}), ensure_ascii=False))
    else:
        builder.limitations.append("The trial's private report and memory state was unavailable.")
    _add_trace(builder, run)
    return evidence.model_copy(
        update={
            "sources": builder.sources,
            "limitations": list(dict.fromkeys(builder.limitations)),
            "input_tokens": _usage(result.get("token_usage"), "input_tokens"),
            "output_tokens": _usage(result.get("token_usage"), "output_tokens"),
        }
    )


@private_capture_context()
def prepare_trial_evaluation(
    *, config: SignalScoutConfig, user: User, request: TrialEvaluationRequest
) -> TrialEvaluationSnapshot:
    assert_trial_environment_ready()
    _validate_groups(request)
    request_hash = _request_hash(config, user, request)
    existing = read_trial_evaluation(config.team_id, request.evaluation_id)
    if existing is not None:
        assert_evaluation_access(existing, config=config, user=user)
        if existing.request_hash != request_hash:
            raise TrialEvaluationError("This evaluation ID was already used for a different request.")
        return existing
    launches: dict[UUID, TrialLaunch] = {}
    context: TrialContext | None = None
    for variant in request.variants:
        expected_settings: _VariantSettings | None = None
        for identifier in variant.launch_ids:
            launch = read_trial_launch(config.team_id, identifier)
            if launch.config_id != config.id or launch.user_id != user.id:
                raise TrialEvaluationError("Every selected launch must belong to this scout and operator.")
            if context is None:
                context = load_trial_context(config.team_id, launch.context_id)
                _assert_context_access(context, config=config, user=user)
            elif launch.context_id != context.id:
                raise TrialEvaluationError("Every selected launch must use the same saved starting context.")
            actual_settings = _settings(launch)
            if expected_settings is not None and actual_settings != expected_settings:
                raise TrialEvaluationError(
                    "All runs within a variant must use identical instructions and runtime settings."
                )
            expected_settings = actual_settings
            launches[identifier] = launch
    if context is None:
        raise TrialEvaluationError("Choose at least one trial to score.")
    rubric = MockScoutRubricReader().read(config_id=config.id, skill_name=config.skill_name)
    raw_criteria = rubric.get("criteria")
    if not isinstance(raw_criteria, list):
        raise TrialEvaluationError("The scoring rubric has no criteria.")
    criteria = [
        TrialEvaluationCriterion.model_validate(
            {field: criterion.get(field) for field in TrialEvaluationCriterion.model_fields}
        )
        for criterion in raw_criteria
        if isinstance(criterion, dict) and criterion.get("enabled") is True
    ]
    if not 1 <= len(criteria) <= 30 or len({criterion.id for criterion in criteria}) != len(criteria):
        raise TrialEvaluationError("The scoring rubric must have 1 to 30 uniquely named enabled criteria.")
    snapshot = TrialEvaluationSnapshot(
        evaluation_id=request.evaluation_id,
        team_id=config.team_id,
        config_id=config.id,
        user_id=user.id,
        context_id=context.id,
        created_at=timezone.now(),
        request=request,
        request_hash=request_hash,
        rubric_document=rubric,
        criteria=criteria,
        judge_model=JUDGE_MODEL,
        judge_prompt_version=JUDGE_PROMPT_VERSION,
        runs=[
            _run_evidence(launches[identifier], context, variant.id)
            for variant in request.variants
            for identifier in variant.launch_ids
        ],
    )
    stored = _write_once(_key(config.team_id, request.evaluation_id, "snapshot"), snapshot)
    if stored.request_hash != request_hash:
        raise TrialEvaluationError("This evaluation ID was already used for a different request.")
    return stored


def _read_judgment(snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence) -> TrialRunJudgment | None:
    judgment = _read_document(
        _key(snapshot.team_id, snapshot.evaluation_id, f"runs/{evidence.launch_id}"), TrialRunJudgment
    )
    if judgment is not None and (
        judgment.launch_id != evidence.launch_id or judgment.variant_id != evidence.variant_id
    ):
        raise TrialEvaluationError("The saved judgment does not match this trial.")
    return judgment


def _error_judgment(evidence: TrialRunEvidence) -> TrialRunJudgment:
    if evidence.exclusion_reason:
        return TrialRunJudgment(
            launch_id=evidence.launch_id,
            variant_id=evidence.variant_id,
            status="excluded",
            summary=evidence.exclusion_reason,
        )
    return TrialRunJudgment(
        launch_id=evidence.launch_id,
        variant_id=evidence.variant_id,
        status="judge_error",
        summary="This trial could not be scored.",
        error="Scoring did not finish. Start a new evaluation to score this trial again.",
    )


def _claim_judgment(snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence) -> bool:
    key = _key(snapshot.team_id, snapshot.evaluation_id, f"attempts/{evidence.launch_id}")
    try:
        object_storage.write(
            key,
            _error_judgment(evidence).model_dump_json(),
            extras={"ContentType": "application/json", "IfNoneMatch": "*"},
        )
    except object_storage.ObjectStorageError:
        if _read_document(key, TrialRunJudgment) is None:
            raise
        return False
    return True


async def run_evaluation_run(team_id: int, evaluation_id: UUID, launch_id: UUID) -> None:
    from products.signals.backend.scout_harness.trial_judge import (  # noqa: PLC0415 -- keep judge dependencies off API startup
        judge_trial_run,
    )

    with private_capture_context():
        snapshot = await asyncio.to_thread(read_trial_evaluation, team_id, evaluation_id)
        if snapshot is None:
            raise TrialEvaluationError("The saved evaluation was not found.")
        evidence = next((run for run in snapshot.runs if run.launch_id == launch_id), None)
        if evidence is None:
            raise TrialEvaluationError("The trial is not part of this evaluation.")
        if await asyncio.to_thread(_read_judgment, snapshot, evidence) is not None:
            return
        if evidence.exclusion_reason:
            judgment = TrialRunJudgment(
                launch_id=launch_id,
                variant_id=evidence.variant_id,
                status="excluded",
                summary=evidence.exclusion_reason,
            )
        else:
            try:
                await database_sync_to_async(_assert_worker_access)(snapshot)
                if not await asyncio.to_thread(_claim_judgment, snapshot, evidence):
                    return
                judgment = await judge_trial_run(snapshot, evidence)
                if judgment.launch_id != launch_id or judgment.variant_id != evidence.variant_id:
                    judgment = _error_judgment(evidence)
            except Exception:
                judgment = _error_judgment(evidence)
        await asyncio.to_thread(_write_once, _key(team_id, evaluation_id, f"runs/{launch_id}"), judgment)


@private_capture_context()
def read_trial_evaluation_report(snapshot: TrialEvaluationSnapshot) -> TrialComparisonReport | None:
    report = _read_document(_key(snapshot.team_id, snapshot.evaluation_id, "report"), TrialComparisonReport)
    if report is not None and (
        report.evaluation_id != snapshot.evaluation_id or report.context_id != snapshot.context_id
    ):
        raise TrialEvaluationError("The saved report does not match this evaluation.")
    return report


@private_capture_context()
def finish_trial_evaluation(team_id: int, evaluation_id: UUID) -> TrialComparisonReport:
    snapshot = read_trial_evaluation(team_id, evaluation_id)
    if snapshot is None:
        raise TrialEvaluationError("The saved evaluation was not found.")
    _assert_worker_access(snapshot)
    existing = read_trial_evaluation_report(snapshot)
    if existing is not None:
        return existing
    judgments = []
    for evidence in snapshot.runs:
        judgment = _read_judgment(snapshot, evidence)
        if judgment is None:
            judgment = _write_once(
                _key(team_id, evaluation_id, f"runs/{evidence.launch_id}"), _error_judgment(evidence)
            )
        judgments.append(judgment)
    report = build_trial_comparison_report(snapshot, judgments)
    return _write_once(_key(team_id, evaluation_id, "report"), report)
