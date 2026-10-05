from __future__ import annotations

import json
import asyncio
import hashlib
from dataclasses import field
from typing import TypeVar, cast
from uuid import UUID

from django.utils import timezone

from pydantic import BaseModel, JsonValue, ValidationError

from posthog.clickhouse.query_tagging import private_capture_context
from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.facade.rubrics import ScoutRubricReferenceContext
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.limits import MAX_TRIAL_RUNS
from products.signals.backend.scout_harness.trial_comparison_types import (
    TrialComparisonHistoryEntry,
    TrialComparisonPlan,
    TrialEvaluationReservation,
)
from products.signals.backend.scout_harness.trial_evaluation_report import build_trial_comparison_report
from products.signals.backend.scout_harness.trial_evaluation_types import (
    TrialComparisonReport,
    TrialEvaluationCriterion,
    TrialEvaluationRequest,
    TrialEvaluationSnapshot,
    TrialEvidenceFile,
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
    assert_trial_work_enabled,
    load_trial_context,
    read_trial_launch,
)
from products.signals.backend.scout_harness.trial_result import (
    get_trial_workflow_status,
    read_trial_result,
    recover_trial_result,
)
from products.signals.backend.scout_harness.trial_rubrics import SavedScoutRubricReader, ScoutRubricReadError
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore
from products.signals.backend.trial_judging import JUDGE_PROMPT_VERSION as JUDGE_PROMPT_VERSION
from products.tasks.backend.facade.api import get_task_run_log_size, get_task_run_log_urls, read_task_run_log_content

MAX_EVALUATION_BYTES = MAX_TRIAL_RUNS * 512 * 1024
MAX_EVIDENCE_BYTES = 128 * 1024 * 1024
JUDGE_MODEL = "gpt-6-astra"
_Document = TypeVar("_Document", bound=BaseModel)


class TrialEvaluationError(ScoutTrialLaunchError):
    pass


class TrialEvaluationNotReady(TrialEvaluationError):
    pass


@frozen
class _VariantSettings:
    model: str
    runtime_adapter: str
    reasoning_effort: str
    service_tier: str | None
    skill_body_sha256: str
    note: str = field(repr=False)


def _evidence_key(team_id: int, evaluation_id: UUID, launch_id: UUID, file: TrialEvidenceFile) -> str:
    return f"signals/scout-trials/{team_id}/evaluations/{evaluation_id}/evidence/{launch_id}/{file.filename}"


class _EvidenceBuilder:
    def __init__(self) -> None:
        self.sources: list[TrialEvidenceSource] = []
        self.limitations: list[str] = []

    def freeze(self, *, team_id: int, evaluation_id: UUID, launch_id: UUID) -> list[TrialEvidenceFile]:
        if sum(len(source.text.encode()) for source in self.sources) > MAX_EVIDENCE_BYTES:
            raise TrialEvaluationError("The trial evidence exceeds the 128 MiB sandbox attachment limit.")
        files: list[TrialEvidenceFile] = []
        for source in self.sources:
            if not source.text:
                continue
            file = TrialEvidenceFile(
                id=source.id,
                kind=source.kind,
                filename="run-log.jsonl" if source.kind == "trace" else f"{source.id.replace(':', '-')}.txt",
                sha256=hashlib.sha256(source.text.encode()).hexdigest(),
                size_bytes=len(source.text.encode()),
            )
            key = _evidence_key(team_id, evaluation_id, launch_id, file)
            existing = object_storage.read(key, missing_ok=True)
            if existing is None:
                try:
                    object_storage.write(key, source.text, extras={"ContentType": "text/plain", "IfNoneMatch": "*"})
                except object_storage.ObjectStorageError:
                    existing = object_storage.read(key, missing_ok=True)
                    if existing is None:
                        raise
            if existing is not None and existing != source.text:
                raise TrialEvaluationError("The saved evidence file no longer matches this trial.")
            files.append(file)
        return files


def trial_evidence_storage_key(
    snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence, file: TrialEvidenceFile
) -> str:
    if (
        evidence not in snapshot.runs
        or file not in evidence.files
        or not any(
            variant.id == evidence.variant_id and evidence.launch_id in variant.launch_ids
            for variant in snapshot.request.variants
        )
    ):
        raise TrialEvaluationError("The saved evidence file does not belong to this trial.")
    return _evidence_key(snapshot.team_id, snapshot.evaluation_id, evidence.launch_id, file)


@private_capture_context()
def read_trial_evidence_sources(
    snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence
) -> list[TrialEvidenceSource]:
    if (
        len({file.id for file in evidence.files}) != len(evidence.files)
        or len({file.filename for file in evidence.files}) != len(evidence.files)
        or sum(file.size_bytes for file in evidence.files) > MAX_EVIDENCE_BYTES
    ):
        raise TrialEvaluationError("The saved evidence manifest is invalid.")
    sources: list[TrialEvidenceSource] = []
    for file in evidence.files:
        content = object_storage.read(trial_evidence_storage_key(snapshot, evidence, file), missing_ok=True)
        if content is None:
            raise TrialEvaluationError("A saved evidence file is unavailable.")
        encoded = content.encode()
        if len(encoded) != file.size_bytes or hashlib.sha256(encoded).hexdigest() != file.sha256:
            raise TrialEvaluationError("A saved evidence file failed its integrity check.")
        sources.append(TrialEvidenceSource(id=file.id, kind=file.kind, text=content))
    return sources


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


def _save_trial_judge_inputs(snapshot: TrialEvaluationSnapshot) -> None:
    # Project only from the committed snapshot so concurrent preparation cannot freeze different evidence.
    for evidence in snapshot.runs:
        judge_input = snapshot.model_copy(update={"runs": [evidence]})
        saved = _write_once(
            _key(snapshot.team_id, snapshot.evaluation_id, f"judge-inputs/{evidence.launch_id}"), judge_input
        )
        if saved != judge_input:
            raise TrialEvaluationError("The saved judge input does not match this evaluation.")


def _read_trial_judge_input(team_id: int, evaluation_id: UUID, launch_id: UUID) -> TrialEvaluationSnapshot | None:
    snapshot = _read_document(_key(team_id, evaluation_id, f"judge-inputs/{launch_id}"), TrialEvaluationSnapshot)
    if snapshot is None:
        return None
    if snapshot.judge_prompt_version != JUDGE_PROMPT_VERSION:
        raise TrialEvaluationError("This evaluation uses an obsolete judge. Start a new trial to assess it.")
    if (
        snapshot.team_id != team_id
        or snapshot.evaluation_id != evaluation_id
        or snapshot.request.evaluation_id != evaluation_id
        or len(snapshot.runs) != 1
        or snapshot.runs[0].launch_id != launch_id
        or not any(
            variant.id == snapshot.runs[0].variant_id and launch_id in variant.launch_ids
            for variant in snapshot.request.variants
        )
    ):
        raise TrialEvaluationError("The saved judge input does not match this trial.")
    return snapshot


def _assert_context_access(
    context: TrialContext | TrialComparisonHistoryEntry | TrialComparisonPlan, *, config: SignalScoutConfig, user: User
) -> None:
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
    if len(set(launches)) != len(launches):
        raise TrialEvaluationError("Choose unique trial runs, each in exactly one variant.")


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
    try:
        urls = get_task_run_log_urls(run.task_run_id, run.task_run.task_id, run.team_id)
        if not urls or urls != [run.task_run.log_url]:
            builder.limitations.append(
                "The exact trial trace was unavailable; inherited resume-chain logs were not read."
            )
            return
        size = get_task_run_log_size(urls, strict=True)
        if size <= 0:
            builder.limitations.append("The trial trace was unavailable.")
            return
        if size > MAX_EVIDENCE_BYTES:
            raise TrialEvaluationError("The trial trace exceeds the 128 MiB sandbox attachment limit.")
        content = read_task_run_log_content(urls)
        if not content:
            raise TrialEvaluationNotReady(
                "The trial trace could not be read. Retry this evaluation after storage is available."
            )
        if len(content.encode()) > MAX_EVIDENCE_BYTES:
            raise TrialEvaluationError("The trial trace exceeds the 128 MiB sandbox attachment limit.")
        builder.sources.append(TrialEvidenceSource(id="trace", kind="trace", text=content))
    except TrialEvaluationError:
        raise
    except Exception:
        raise TrialEvaluationNotReady(
            "The trial trace could not be read. Retry this evaluation after storage is available."
        ) from None


def _usage(value: JsonValue, field: str) -> int | None:
    item = value.get(field) if isinstance(value, dict) else None
    return item if isinstance(item, int) and not isinstance(item, bool) and item >= 0 else None


def _report_evidence(report_id: str, report: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(report, dict):
        return {"report_id": report_id, "report": report}
    document, payload = report.get("document"), report.get("payload")
    if not isinstance(document, dict) or not isinstance(payload, dict):
        return {"report_id": report_id, "report": report}
    matching: list[JsonValue] = [
        key for key, value in payload.items() if isinstance(value, str) and value == document.get(key)
    ]
    metadata: dict[str, JsonValue] = {
        key: value
        for key, value in payload.items()
        if key not in matching
        and (value is None or isinstance(value, (bool, int, float)) or isinstance(value, str) and len(value) <= 256)
    }
    return {
        "report_id": report_id,
        "report": {
            "captured_submission_metadata": metadata,
            "document": document,
            "submission_fields_matching_document": matching,
            "captured_submission_details": {
                key: value for key, value in payload.items() if key not in metadata and key not in matching
            },
            **{key: value for key, value in report.items() if key not in {"document", "payload"}},
        },
    }


def _run_evidence(
    launch: TrialLaunch, context: TrialContext, variant_id: UUID, *, evaluation_id: UUID
) -> TrialRunEvidence:
    run = _bound_run(launch)
    result = read_trial_result(run) if run is not None else None
    workflow = None
    status: str
    if result is None:
        workflow = get_trial_workflow_status(team_id=launch.team_id, launch_id=launch.id)
        status = workflow.status
    else:
        status = cast(str, result["status"])
    if status not in {"completed", "failed", "cancelled", "skipped"} or (run is None and status == "completed"):
        raise TrialEvaluationNotReady("Every selected trial must have a known terminal state before scoring.")
    if run is not None:
        run.task_run.refresh_from_db(fields=["status", "state"])
        if run.task_run.status not in {"completed", "failed", "cancelled"}:
            raise TrialEvaluationNotReady("Every selected trial task must finish before scoring.")
        if status == "completed":
            status = run.task_run.status
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
    if result is None and workflow is not None:
        result = recover_trial_result(run, workflow=workflow)
    if result is None or result.get("launch_id") != str(launch.id) or result.get("context_id") != str(context.id):
        raise TrialEvaluationError("A selected trial result could not be frozen safely.")
    if (
        ScoutTrialStore(run).invalid_reason() is not None
        or result.get("valid_comparison") is not True
        or run.task_run.status != "completed"
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
    authored = [
        TrialEvidenceSource(id="instructions", kind="instructions", text=launch.skill_body),
        TrialEvidenceSource(id="launch-note", kind="instructions", text=launch.note),
        TrialEvidenceSource(
            id="context",
            kind="context",
            text=json.dumps(
                {"memory": context.memory, "notes": context.notes, "recent_runs": context.recent_runs},
                ensure_ascii=False,
            ),
        ),
    ]
    summary = result.get("summary")
    if isinstance(summary, str) and summary:
        authored.append(TrialEvidenceSource(id="summary", kind="summary", text=summary))
    else:
        builder.limitations.append("The completed trial has no final summary.")
    private = result.get("private_state")
    if isinstance(private, dict):
        reports = private.get("reports")
        if isinstance(reports, dict):
            for index, (identifier, report) in enumerate(sorted(reports.items())):
                authored.append(
                    TrialEvidenceSource(
                        id=f"report:{index}",
                        kind="report",
                        text=json.dumps(_report_evidence(identifier, report), ensure_ascii=False),
                    )
                )
        authored.append(
            TrialEvidenceSource(
                id="memory", kind="memory", text=json.dumps(private.get("memory", {}), ensure_ascii=False)
            )
        )
    else:
        builder.limitations.append("The trial's private report and memory state was unavailable.")
    builder.sources.extend(authored)
    _add_trace(builder, run)
    return evidence.model_copy(
        update={
            "files": builder.freeze(team_id=launch.team_id, evaluation_id=evaluation_id, launch_id=launch.id),
            "limitations": list(dict.fromkeys(builder.limitations)),
            "input_tokens": _usage(result.get("token_usage"), "input_tokens"),
            "output_tokens": _usage(result.get("token_usage"), "output_tokens"),
        }
    )


@private_capture_context()
def trial_evaluation_criteria(rubric: dict[str, JsonValue]) -> list[TrialEvaluationCriterion]:
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
    return criteria


def reserve_trial_evaluation(reservation: TrialEvaluationReservation) -> None:
    saved = _write_once(_key(reservation.team_id, reservation.evaluation_id, "reservation"), reservation)
    if saved != reservation:
        raise TrialEvaluationError("This evaluation ID is already reserved for another request.")


@private_capture_context()
def prepare_trial_evaluation(
    *,
    config: SignalScoutConfig,
    user: User,
    request: TrialEvaluationRequest,
    rubric_document: dict[str, JsonValue] | None = None,
    judge_model: str = JUDGE_MODEL,
    judge_prompt_version: str = JUDGE_PROMPT_VERSION,
) -> TrialEvaluationSnapshot:
    assert_trial_environment_ready()
    _validate_groups(request)
    assert_trial_work_enabled(config.team)
    request_hash = _request_hash(config, user, request)
    existing = read_trial_evaluation(config.team_id, request.evaluation_id)
    if existing is not None:
        assert_evaluation_access(existing, config=config, user=user)
        if existing.request_hash != request_hash:
            raise TrialEvaluationError("This evaluation ID was already used for a different request.")
        if existing.judge_prompt_version != JUDGE_PROMPT_VERSION:
            raise TrialEvaluationError("This evaluation uses an obsolete judge. Start a new trial to assess it.")
        _save_trial_judge_inputs(existing)
        return existing
    reserved_plan = _read_document(
        f"signals/scout-trials/{config.team_id}/comparisons/{request.evaluation_id}/plan.json", TrialComparisonPlan
    )
    if reserved_plan is not None:
        if (
            reserved_plan.team_id != config.team_id
            or reserved_plan.config_id != config.id
            or reserved_plan.user_id != user.id
            or request != reserved_plan.request.evaluation_request()
        ):
            raise TrialEvaluationError("This evaluation ID belongs to a different saved comparison.")
        rubric_document = reserved_plan.rubric_document
        judge_model = reserved_plan.judge_model
        judge_prompt_version = reserved_plan.judge_prompt_version
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
    try:
        rubric = (
            rubric_document
            if rubric_document is not None
            else SavedScoutRubricReader(team_id=config.team_id).read(config_id=config.id, skill_name=config.skill_name)
        )
    except ScoutRubricReadError as error:
        raise TrialEvaluationError(str(error)) from error
    criteria = trial_evaluation_criteria(rubric)
    if judge_prompt_version != JUDGE_PROMPT_VERSION:
        raise TrialEvaluationError("This evaluation uses an obsolete judge. Start a new trial to assess it.")
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
        rubric_reference_context=ScoutRubricReferenceContext.model_validate(rubric["reference_context"]),
        rubric_reference_generation_id=cast(str, rubric["reference_generation_id"]),
        criteria=criteria,
        judge_model=judge_model,
        judge_prompt_version=judge_prompt_version,
        runs=[
            _run_evidence(launches[identifier], context, variant.id, evaluation_id=request.evaluation_id)
            for variant in request.variants
            for identifier in variant.launch_ids
        ],
    )
    reserve_trial_evaluation(
        TrialEvaluationReservation(
            team_id=config.team_id,
            evaluation_id=request.evaluation_id,
            config_id=config.id,
            user_id=user.id,
            kind="comparison" if reserved_plan else "evaluation",
            request_hash=reserved_plan.request_hash if reserved_plan else request_hash,
        )
    )
    stored = _write_once(_key(config.team_id, request.evaluation_id, "snapshot"), snapshot)
    if stored.request_hash != request_hash:
        raise TrialEvaluationError("This evaluation ID was already used for a different request.")
    _save_trial_judge_inputs(stored)
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


def _error_judgment(evidence: TrialRunEvidence, error: str | None = None) -> TrialRunJudgment:
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
        error=error or "Scoring did not finish. Start a new evaluation to score this trial again.",
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
        TrialJudgeExecutionError,
        judge_trial_run,
        safe_judge_failure,
    )

    with private_capture_context():
        snapshot = await asyncio.to_thread(_read_trial_judge_input, team_id, evaluation_id, launch_id)
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
            await database_sync_to_async(assert_trial_work_enabled)(
                await database_sync_to_async(Team.objects.get)(pk=team_id)
            )
            step = "access_check"
            try:
                await database_sync_to_async(_assert_worker_access)(snapshot)
                step = "judgment_claim"
                if not await asyncio.to_thread(_claim_judgment, snapshot, evidence):
                    return
                step = "judge_execution"
                judgment = await judge_trial_run(snapshot, evidence)
                if judgment.launch_id != launch_id or judgment.variant_id != evidence.variant_id:
                    judgment = _error_judgment(evidence)
            except TrialJudgeExecutionError as error:
                judgment = _error_judgment(evidence, str(error))
            except Exception as error:
                judgment = _error_judgment(evidence, safe_judge_failure(step, error))
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
