from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from pydantic import ValidationError

from posthog.clickhouse.query_tagging import private_capture_context
from posthog.models import User
from posthog.storage import object_storage
from posthog.temporal.common.client import sync_connect

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.run_gates import check_fleet_gates, check_spend_gates
from products.signals.backend.scout_harness.trial_comparison_types import (
    TrialComparisonEvaluation,
    TrialComparisonHistory,
    TrialComparisonHistoryEntry,
    TrialComparisonPlan,
    TrialComparisonProgress,
    TrialComparisonRequest,
    TrialComparisonResult,
    TrialComparisonVariantResult,
    TrialEvaluationReservation,
)
from products.signals.backend.scout_harness.trial_evaluation import (
    JUDGE_MODEL,
    JUDGE_PROMPT_VERSION,
    TrialEvaluationError,
    TrialEvaluationNotReady,
    _assert_context_access,
    _read_document,
    _validate_groups,
    _write_once,
    prepare_trial_evaluation,
    read_trial_evaluation,
    read_trial_evaluation_report,
    reserve_trial_evaluation,
    trial_evaluation_criteria,
)
from products.signals.backend.scout_harness.trial_evaluation_types import (
    TrialEvaluationRequest,
    TrialEvaluationSnapshot,
)
from products.signals.backend.scout_harness.trial_inspection import ScoutTrialInspection
from products.signals.backend.scout_harness.trial_launch import (
    assert_trial_environment_ready,
    assert_trial_work_enabled,
    create_trial_context,
    create_trial_launch,
    read_trial_launch,
)
from products.signals.backend.scout_harness.trial_result import get_trial_workflow_status
from products.signals.backend.scout_harness.trial_rubrics import SavedScoutRubricReader, ScoutRubricReadError
from products.signals.backend.trial_execution import TrialCoordinator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from temporalio.client import Client


def comparison_plan_key(team_id: int, comparison_id: UUID) -> str:
    return f"signals/scout-trials/{team_id}/comparisons/{comparison_id}/plan.json"


def comparison_progress_key(team_id: int, comparison_id: UUID) -> str:
    return f"signals/scout-trials/{team_id}/comparisons/{comparison_id}/progress.json"


@private_capture_context()
def save_comparison_progress(team_id: int, comparison_id: UUID, progress: TrialComparisonProgress) -> None:
    object_storage.write(
        comparison_progress_key(team_id, comparison_id),
        progress.model_dump_json(),
        extras={"ContentType": "application/json"},
    )


def comparison_evaluation_request(request: TrialComparisonRequest) -> TrialEvaluationRequest:
    return request.evaluation_request()


def list_comparison_history_keys(prefix: str, limit: int) -> list[str]:
    client = object_storage.object_storage_client()
    if not isinstance(client, object_storage.ObjectStorage):
        raise object_storage.ObjectStorageError("Comparison history storage is unavailable.")
    try:
        response: dict[str, object] = client.aws_client.list_objects_v2(
            Bucket=settings.OBJECT_STORAGE_BUCKET, Prefix=prefix, MaxKeys=limit + 1
        )
        contents = response.get("Contents", [])
        if not isinstance(contents, list):
            raise ValueError("Invalid object listing")
        keys: list[str] = []
        for item in contents:
            key = item.get("Key") if isinstance(item, dict) else None
            if not isinstance(key, str) or not key.startswith(prefix):
                raise ValueError("Invalid object key")
            keys.append(key)
        return keys
    except Exception:
        raise object_storage.ObjectStorageError(
            "Comparison history could not be loaded. Refresh to try again."
        ) from None


class ScoutTrialComparisons:
    def __init__(self, config: SignalScoutConfig, user: User) -> None:
        self.config = config
        self.user = user

    def _assert_access(self, plan: TrialComparisonPlan) -> None:
        if plan.team_id != self.config.team_id or plan.config_id != self.config.id or plan.user_id != self.user.id:
            raise TrialEvaluationError("This comparison is not available to this operator.")
        _assert_context_access(plan, config=self.config, user=self.user)

    def evaluation(self, plan: TrialComparisonPlan) -> TrialEvaluationSnapshot | None:
        snapshot = read_trial_evaluation(plan.team_id, plan.comparison_id)
        if snapshot is not None and (
            snapshot.team_id != plan.team_id
            or snapshot.config_id != plan.config_id
            or snapshot.user_id != plan.user_id
            or snapshot.context_id != plan.context_id
            or snapshot.request != plan.request.evaluation_request()
            or snapshot.rubric_document != plan.rubric_document
            or snapshot.judge_model != plan.judge_model
            or snapshot.judge_prompt_version != plan.judge_prompt_version
        ):
            raise TrialEvaluationError("The saved evaluation does not belong to this comparison.")
        return snapshot

    @private_capture_context()
    def read(self, comparison_id: UUID) -> TrialComparisonPlan:
        plan = _read_document(comparison_plan_key(self.config.team_id, comparison_id), TrialComparisonPlan)
        if plan is None or plan.comparison_id != comparison_id:
            raise TrialEvaluationError("The saved comparison was not found.")
        self._assert_access(plan)
        return plan

    @classmethod
    def for_worker(cls, team_id: int, comparison_id: UUID) -> ScoutTrialComparisons:
        assert_trial_environment_ready()
        plan = _read_document(comparison_plan_key(team_id, comparison_id), TrialComparisonPlan)
        if plan is None or plan.team_id != team_id or plan.comparison_id != comparison_id:
            raise TrialEvaluationError("The saved comparison was not found.")
        config = SignalScoutConfig.objects.for_team(team_id).select_related("team").filter(id=plan.config_id).first()
        user = User.objects.filter(id=plan.user_id, is_active=True).first()
        if config is None or user is None:
            raise TrialEvaluationError("This comparison is no longer available to its operator.")
        service = cls(config, user)
        service._assert_access(plan)
        return service

    def assert_can_start(self, *, launch_ids: Sequence[UUID] = ()) -> None:
        assert_trial_environment_ready()
        assert_trial_work_enabled(self.config.team)
        # TODO: Before widening access beyond team 2, add limits across concurrent trials and
        # a separate trial budget to protect scheduled scouts from overlapping trial workloads.
        requested_ids = {str(launch_id) for launch_id in launch_ids}
        if requested_ids:
            # A resume must not charge runs that already started against the budget twice.
            started_ids = (
                SignalScoutRun.objects.for_team(self.config.team_id)
                .filter(metadata__scout_trial__launch_id__in=requested_ids)
                .values_list("metadata__scout_trial__launch_id", flat=True)
            )
            requested_ids.difference_update(started_ids)
        for rejection in (
            check_fleet_gates(self.config.team_id, requested_runs=len(requested_ids)),
            check_spend_gates(self.config.team, capture_analytics=False),
        ):
            if rejection is not None:
                raise TrialEvaluationError(rejection.detail)

    def _history_prefix(self) -> str:
        return f"signals/scout-trials/{self.config.team_id}/comparison-history/{self.user.id}/{self.config.id}/"

    def _index(self, plan: TrialComparisonPlan) -> None:
        # Newest first even when the object-store listing stops at its first page.
        reverse_time = 9_999_999_999_999_999_999 - int(plan.created_at.timestamp() * 1_000_000)
        key = f"{self._history_prefix()}{reverse_time:019d}-{plan.comparison_id}.json"
        _write_once(
            key,
            TrialComparisonHistoryEntry(
                team_id=plan.team_id,
                config_id=plan.config_id,
                user_id=plan.user_id,
                skill_name=plan.skill_name,
                skill_version=plan.skill_version,
                summary=self.result(plan, history=True),
            ),
        )

    @private_capture_context()
    def create(self, request: TrialComparisonRequest) -> TrialComparisonPlan:
        evaluation_request = comparison_evaluation_request(request)
        _validate_groups(evaluation_request)
        self.assert_can_start(
            launch_ids=[launch_id for variant in request.variants for launch_id in variant.launch_ids]
        )
        labels = [variant.label.strip() for variant in request.variants]
        if any(not label for label in labels) or len(set(labels)) != len(labels):
            raise TrialEvaluationError("Give every variant a different, nonempty name.")
        # Keep exact retries compatible with plans saved before the optional version check.
        request_hash = hashlib.sha256(
            request.model_dump_json(
                exclude={"expected_skill_version"} if request.expected_skill_version is None else None
            ).encode()
        ).hexdigest()
        existing = _read_document(comparison_plan_key(self.config.team_id, request.comparison_id), TrialComparisonPlan)
        if existing is not None:
            self._assert_access(existing)
            if existing.request_hash != request_hash:
                raise TrialEvaluationError("This comparison ID was already used for different settings.")
            self._index(existing)
            return existing
        if read_trial_evaluation(self.config.team_id, request.comparison_id) is not None:
            raise TrialEvaluationError("This comparison ID already belongs to another evaluation.")
        setup = ScoutTrialInspection(self.config, self.user).setup()
        if not setup.ready:
            raise TrialEvaluationError(setup.blocked_reason or "The scout cannot run a comparison.")
        choices = {option.model: option.reasoning_efforts for option in setup.models}
        if any(variant.reasoning_effort not in choices.get(variant.model, []) for variant in request.variants):
            raise TrialEvaluationError("Choose a supported model and effort for every variant.")
        try:
            rubric = SavedScoutRubricReader(team_id=self.config.team_id).read(
                config_id=self.config.id, skill_name=self.config.skill_name
            )
            trial_evaluation_criteria(rubric)
        except (ScoutRubricReadError, ValidationError) as error:
            raise TrialEvaluationError("Review and save a valid rubric before starting the comparison.") from error
        context = create_trial_context(
            config=self.config,
            user=self.user,
            identifier=request.comparison_id,
            note=request.note,
            expected_skill_version=request.expected_skill_version,
        )
        _assert_context_access(context, config=self.config, user=self.user)
        for variant in request.variants:
            for index, launch_id in enumerate(variant.launch_ids):
                create_trial_launch(
                    config=self.config,
                    user=self.user,
                    launch_id=launch_id,
                    context_id=context.id,
                    model=variant.model,
                    reasoning_effort=variant.reasoning_effort,
                    skill_body=variant.skill_body,
                    note=request.note,
                    variant=f"{variant.label[:90]} ({index + 1})",
                )
        plan = TrialComparisonPlan(
            comparison_id=request.comparison_id,
            team_id=self.config.team_id,
            config_id=self.config.id,
            user_id=self.user.id,
            context_id=context.id,
            skill_name=context.skill_name,
            skill_version=context.skill_version,
            variants=[
                TrialComparisonVariantResult(
                    id=variant.id,
                    label=variant.label,
                    launch_ids=variant.launch_ids,
                    model=variant.model,
                    reasoning_effort=variant.reasoning_effort,
                    skill_body_sha256=hashlib.sha256(
                        (variant.skill_body if variant.skill_body is not None else context.skill_body).encode()
                    ).hexdigest(),
                )
                for variant in request.variants
            ],
            created_at=timezone.now(),
            request=request,
            request_hash=request_hash,
            rubric_document=rubric,
            judge_model=JUDGE_MODEL,
            judge_prompt_version=JUDGE_PROMPT_VERSION,
        )
        reserve_trial_evaluation(
            TrialEvaluationReservation(
                team_id=plan.team_id,
                evaluation_id=plan.comparison_id,
                config_id=plan.config_id,
                user_id=plan.user_id,
                kind="comparison",
                request_hash=plan.request_hash,
            )
        )
        saved = _write_once(comparison_plan_key(plan.team_id, plan.comparison_id), plan)
        self._assert_access(saved)
        if saved.request_hash != request_hash:
            raise TrialEvaluationError("This comparison ID was already used for different settings.")
        self._index(saved)
        return saved

    @private_capture_context()
    def result(
        self, plan: TrialComparisonPlan, *, inspect_workflow: bool = True, starting: bool = False, history: bool = False
    ) -> TrialComparisonResult:
        from products.signals.backend.temporal.agentic.scout_trial_comparison import (  # noqa: PLC0415 -- avoid the workflow registry import cycle
            get_trial_comparison_status,
        )

        self._assert_access(plan)
        snapshot = self.evaluation(plan) if not history else None
        report = read_trial_evaluation_report(snapshot) if snapshot else None
        state: LiteralComparisonStatus = "completed" if report else "judging" if snapshot else "running"
        error = None
        if history:
            progress = _read_document(
                comparison_progress_key(plan.team_id, plan.comparison_id), TrialComparisonProgress
            )
            state = progress.status if progress else "not_started"
            error = progress.error if progress else None
        elif report is None and starting:
            state = "starting"
        elif report is None and inspect_workflow:
            workflow = get_trial_comparison_status(plan.team_id, plan.comparison_id)
            if workflow.status != "pending":
                state = "failed" if workflow.status == "completed" else cast(LiteralComparisonStatus, workflow.status)
                error = workflow.error or (
                    "The comparison ended before its report was saved." if state == "failed" else None
                )
        return TrialComparisonResult(
            comparison_id=plan.comparison_id,
            config_id=plan.config_id,
            context_id=plan.context_id,
            created_at=plan.created_at,
            baseline_variant_id=plan.request.baseline_variant_id,
            rubric_revision=cast(int, plan.rubric_document["revision"]),
            variants=plan.variants,
            status=state,
            error=error,
            evaluation=TrialComparisonEvaluation(
                request=snapshot.request,
                evaluation_id=snapshot.evaluation_id,
                context_id=snapshot.context_id,
                status="completed" if report else "failed" if state == "failed" else "pending",
                error=error,
                report=report,
            )
            if snapshot
            else None,
        )

    @private_capture_context()
    def history(self, limit: int) -> TrialComparisonHistory:
        ScoutTrialInspection(self.config, self.user)._check_skill_access()
        keys = sorted(list_comparison_history_keys(self._history_prefix(), limit))
        results: list[TrialComparisonResult] = []
        for key in keys[: limit + 1]:
            try:
                entry = _read_document(key, TrialComparisonHistoryEntry)
                if entry is None or entry.summary.config_id != entry.config_id:
                    raise TrialEvaluationError("The saved comparison history is unavailable.")
                _assert_context_access(entry, config=self.config, user=self.user)
                progress = _read_document(
                    comparison_progress_key(entry.team_id, entry.summary.comparison_id), TrialComparisonProgress
                )
                state = progress.status if progress else "not_started"
                error = progress.error if progress else None
                if state != "completed":
                    snapshot = self.evaluation(self.read(entry.summary.comparison_id))
                    if snapshot is not None and read_trial_evaluation_report(snapshot) is not None:
                        state, error = "completed", None
                results.append(
                    entry.summary.model_copy(
                        update={
                            "status": state,
                            "error": error,
                            "evaluation": None,
                        }
                    )
                )
            except (ValueError, TrialEvaluationError):
                continue
        return TrialComparisonHistory(results=results[:limit], has_more=len(keys) > limit)


type LiteralComparisonStatus = Literal[
    "not_started", "starting", "running", "judging", "completed", "failed", "unknown"
]


class _ScoutTrialRunner:
    def __init__(self, service: ScoutTrialComparisons, comparison_id: UUID) -> None:
        self.service = service
        self.comparison_id = comparison_id
        self.client: Client | None = None

    def prepare(self) -> Sequence[UUID]:
        plan = self.service.read(self.comparison_id)
        launch_ids = [launch_id for variant in plan.request.variants for launch_id in variant.launch_ids]
        self.service.assert_can_start(launch_ids=launch_ids)
        save_comparison_progress(plan.team_id, self.comparison_id, TrialComparisonProgress(status="running"))
        self.client = sync_connect()
        return launch_ids

    def start(self, execution_id: UUID) -> None:
        from products.signals.backend.temporal.agentic.scout_scheduler import (  # noqa: PLC0415 -- avoid the workflow registry import cycle
            start_trial_signals_scout_run,
        )

        if self.client is None:
            raise RuntimeError("Prepare trial executions before starting them.")
        team_id = self.service.config.team_id
        launch = read_trial_launch(team_id, execution_id)
        start_trial_signals_scout_run(
            self.client, team_id=team_id, skill_name=launch.skill_name, launch_id=str(execution_id)
        )

    def finished(self, execution_id: UUID) -> bool:
        state = get_trial_workflow_status(team_id=self.service.config.team_id, launch_id=execution_id)
        return state.status in {"completed", "failed", "cancelled", "skipped"}


@private_capture_context()
def dispatch_trial_comparison(team_id: int, comparison_id: UUID) -> None:
    service = ScoutTrialComparisons.for_worker(team_id, comparison_id)
    TrialCoordinator(_ScoutTrialRunner(service, comparison_id)).start()


@private_capture_context()
def prepare_comparison_evaluation(team_id: int, comparison_id: UUID) -> bool:
    from products.signals.backend.temporal.agentic.scout_trial_evaluation import (  # noqa: PLC0415 -- avoid the workflow registry import cycle
        start_trial_evaluation,
    )

    service = ScoutTrialComparisons.for_worker(team_id, comparison_id)
    plan = service.read(comparison_id)
    snapshot = service.evaluation(plan)
    if snapshot is None:
        runner = TrialCoordinator(_ScoutTrialRunner(service, comparison_id))
        if not runner.finished(launch_id for variant in plan.request.variants for launch_id in variant.launch_ids):
            return False
        try:
            snapshot = prepare_trial_evaluation(
                config=service.config,
                user=service.user,
                request=comparison_evaluation_request(plan.request),
                rubric_document=plan.rubric_document,
                judge_model=plan.judge_model,
                judge_prompt_version=plan.judge_prompt_version,
            )
        except TrialEvaluationNotReady:
            return False
    if read_trial_evaluation_report(snapshot) is None:
        service.assert_can_start()
        start_trial_evaluation(team_id, comparison_id)
    save_comparison_progress(team_id, comparison_id, TrialComparisonProgress(status="judging"))
    return True


@private_capture_context()
def comparison_evaluation_finished(team_id: int, comparison_id: UUID) -> bool:
    from products.signals.backend.temporal.agentic.scout_trial_evaluation import (  # noqa: PLC0415 -- avoid the workflow registry import cycle
        get_trial_evaluation_status,
    )

    service = ScoutTrialComparisons.for_worker(team_id, comparison_id)
    snapshot = service.evaluation(service.read(comparison_id))
    if snapshot is not None and read_trial_evaluation_report(snapshot) is not None:
        save_comparison_progress(team_id, comparison_id, TrialComparisonProgress(status="completed"))
        return True
    state = get_trial_evaluation_status(team_id, comparison_id)
    if state.status in {"failed", "not_started", "completed"}:
        raise TrialEvaluationError("Judging did not finish. Resume the comparison to recover its saved work.")
    return False
