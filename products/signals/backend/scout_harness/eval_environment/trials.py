from __future__ import annotations

import os
import json
import hashlib
import ipaddress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, JsonValue, model_validator

from products.posthog_ai.eval_harness.environment.schema import EnvironmentModel
from products.posthog_ai.eval_harness.environment.storage import file_sha256, require_private_path, workspace_lock

if TYPE_CHECKING:
    from products.signals.backend.scout_harness.eval_environment.schema import (
        ScoutEnvironmentCase,
        ScoutEnvironmentSeed,
    )
    from products.signals.backend.scout_harness.trial_comparison import ScoutTrialComparisons
    from products.signals.backend.scout_harness.trial_comparison_types import TrialComparisonRequest


MAX_CAMPAIGN_USD = Decimal("300")
_SCORING_AI_STAGES = ("scout_suggestions", "scout:trial_judge")


def write_private_json(path: Path, value: BaseModel | dict[str, object]) -> None:
    path = require_private_path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w") as output:
            content = (
                value.model_dump_json(indent=2)
                if isinstance(value, BaseModel)
                else json.dumps(value, indent=2, allow_nan=False)
            )
            output.write(content + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def assert_local_url(value: str | None, name: str) -> None:
    if not value:
        raise ValueError(f"{name} must explicitly target the local evaluation environment.")
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host in {"localhost", "host.docker.internal", "backend", "mcp", "ai-gateway", "objectstorage"}
    if parsed.scheme not in {"http", "https"} or not local or parsed.username or parsed.password:
        raise ValueError(f"{name} must use an explicit local service URL without embedded credentials.")


class FrozenEnvironment(EnvironmentModel):
    version: Literal[1] = 1
    created_at: datetime
    inputs: dict[str, str]
    team_id: int
    config_id: UUID
    prompt_mode: Literal["recorded", "native"] = "recorded"
    case_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    runtime_prompt_path: str
    runtime_prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @classmethod
    def create(
        cls, paths: list[Path], seed: ScoutEnvironmentSeed, *, runtime_prompt: Path, case: ScoutEnvironmentCase
    ) -> FrozenEnvironment:
        runtime_prompt = require_private_path(runtime_prompt)
        return cls(
            created_at=datetime.now(UTC),
            inputs={str(require_private_path(path)): file_sha256(path) for path in paths},
            team_id=seed.team_id,
            config_id=seed.config_id,
            prompt_mode=case.prompt_mode,
            case_sha256=case.fingerprint(),
            runtime_prompt_path=str(runtime_prompt),
            runtime_prompt_sha256=file_sha256(runtime_prompt),
        )

    @model_validator(mode="after")
    def validate_native_case(self) -> Self:
        if self.prompt_mode == "native" and not self.case_sha256:
            raise ValueError("Native scout environments must bind the complete starting case.")
        return self

    def verify_case(self, case: ScoutEnvironmentCase) -> None:
        if self.prompt_mode != case.prompt_mode or (
            self.case_sha256 is not None and self.case_sha256 != case.fingerprint()
        ):
            raise ValueError("The scout case does not match this frozen environment.")

    def verify(self) -> None:
        for name, expected in {**self.inputs, self.runtime_prompt_path: self.runtime_prompt_sha256}.items():
            path = require_private_path(Path(name))
            if not path.is_file() or file_sha256(path) != expected:
                raise ValueError("The frozen reconstruction changed. Create a new environment and freeze it again.")


class BudgetReservation(EnvironmentModel):
    reserved_usd: Decimal = Field(gt=0, allow_inf_nan=False)
    plan_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    status: Literal["reserved", "settled"] = "reserved"
    actual_usd: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)


class CampaignBudget(EnvironmentModel):
    version: Literal[1] = 1
    limit_usd: Decimal = Field(default=MAX_CAMPAIGN_USD, gt=0, le=MAX_CAMPAIGN_USD, allow_inf_nan=False)
    reservations: dict[str, BudgetReservation] = Field(default_factory=dict)

    @property
    def committed_usd(self) -> Decimal:
        return sum(
            (
                entry.actual_usd if entry.status == "settled" and entry.actual_usd is not None else entry.reserved_usd
                for entry in self.reservations.values()
            ),
            Decimal("0"),
        )


class BudgetLedger:
    def __init__(self, path: Path) -> None:
        self.path = require_private_path(path)

    def read(self) -> CampaignBudget:
        return CampaignBudget.model_validate_json(self.path.read_bytes()) if self.path.exists() else CampaignBudget()

    def reserve(self, identifier: UUID, amount: Decimal, *, plan_sha256: str) -> CampaignBudget:
        reservation = BudgetReservation(reserved_usd=amount, plan_sha256=plan_sha256)
        with workspace_lock(self.path.parent):
            budget = self.read()
            key = str(identifier)
            previous = budget.reservations.get(key)
            if previous is not None:
                if previous.status == "settled":
                    raise ValueError("This comparison is already settled. Export its results or create a new plan.")
                if previous.plan_sha256 is None or previous.plan_sha256 != reservation.plan_sha256:
                    raise ValueError(
                        "The pending reservation is not bound to this exact plan. Reconcile the existing reservation "
                        "before creating a new plan."
                    )
                if previous.reserved_usd != amount:
                    raise ValueError("This comparison already has a different budget reservation.")
                return budget
            if any(entry.status == "reserved" for entry in budget.reservations.values()):
                raise ValueError("Reconcile the previous comparison before reserving another paid batch.")
            if budget.committed_usd + amount > budget.limit_usd:
                raise ValueError("The comparison would exceed the campaign budget.")
            updated = budget.model_copy(update={"reservations": {**budget.reservations, key: reservation}})
            write_private_json(self.path, updated)
            return updated

    def settle(self, identifier: UUID, actual_usd: Decimal) -> CampaignBudget:
        with workspace_lock(self.path.parent):
            budget = self.read()
            previous = budget.reservations.get(str(identifier))
            if previous is None:
                raise ValueError("The comparison has no budget reservation.")
            settled = BudgetReservation(
                reserved_usd=previous.reserved_usd,
                plan_sha256=previous.plan_sha256,
                status="settled",
                actual_usd=actual_usd,
            )
            updated = budget.model_copy(update={"reservations": {**budget.reservations, str(identifier): settled}})
            write_private_json(self.path, updated)
            return updated


class TrialVariant(EnvironmentModel):
    id: UUID = Field(default_factory=uuid4)
    label: str = Field(min_length=1, max_length=100)
    model: str
    reasoning_effort: str
    repeats: int = Field(default=1, ge=1, le=20)
    skill_body: str | None = None


class EvaluationPlan(EnvironmentModel):
    mode: Literal["trial", "comparison"]
    comparison_id: UUID = Field(default_factory=uuid4)
    freeze_sha256: str
    config_id: UUID
    team_id: int
    user_id: int
    request: dict[str, object]
    reserved_usd: Decimal = Field(gt=0, allow_inf_nan=False)
    scout_cap_usd: Decimal = Field(gt=0, allow_inf_nan=False)
    judge_cap_usd: Decimal = Field(gt=0, allow_inf_nan=False)
    report_checks_per_run: int = Field(ge=1)

    def fingerprint(self) -> str:
        content = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(content.encode()).hexdigest()

    def validate_budget(self, request: TrialComparisonRequest, *, scout_cap: Decimal, judge_cap: Decimal) -> None:
        count = sum(len(variant.launch_ids) for variant in request.variants)
        required = count * (scout_cap * (1 + self.report_checks_per_run) + (judge_cap if count > 1 else 0))
        if required != self.reserved_usd or scout_cap != self.scout_cap_usd or judge_cap != self.judge_cap_usd:
            raise ValueError("The trial request and gateway caps no longer match the saved budget reservation.")


class TrialExport(EnvironmentModel):
    status: str
    result: dict[str, JsonValue] | None = None
    log: str = ""
    launch_id: UUID | None = None
    run_id: UUID | None = None
    task_run_id: UUID | None = None
    errors: list[str] = Field(default_factory=list)


class ScoutEvaluationTrials:
    def __init__(self, case: ScoutEnvironmentCase, seed: ScoutEnvironmentSeed, freeze_path: Path) -> None:
        self.case = case
        self.seed = seed
        self.freeze_path = require_private_path(freeze_path)
        self.freeze = FrozenEnvironment.model_validate_json(self.freeze_path.read_bytes())
        self.freeze.verify()
        self.freeze.verify_case(case)
        if self.freeze.team_id != seed.team_id or self.freeze.config_id != seed.config_id:
            raise ValueError("The frozen reconstruction belongs to another scout environment.")

    def check_prompt_configuration(self) -> None:
        from django.conf import settings  # noqa: PLC0415 -- Django is initialized by the CLI.

        from products.signals.backend.scout_harness.eval_environment.prompt import (  # noqa: PLC0415
            NativeScoutPrompt,
            RecordedScoutPrompt,
            read_native_prompt,
            read_recorded_prompt,
        )
        from products.signals.backend.scout_harness.prompt import HARNESS_PROMPT_VERSION  # noqa: PLC0415

        self.freeze.verify_case(self.case)
        configured_prompt = getattr(settings, "SCOUT_EVAL_ENVIRONMENT_FILE", "")
        prompt: NativeScoutPrompt | RecordedScoutPrompt
        if self.case.prompt_mode == "native":
            if configured_prompt:
                raise ValueError("Unset SCOUT_EVAL_ENVIRONMENT_FILE for native scout prompt generation.")
            prompt = read_native_prompt(Path(self.freeze.runtime_prompt_path))
            if prompt.harness_prompt_version != HARNESS_PROMPT_VERSION:
                raise ValueError("The native scout harness changed. Prepare and freeze a new environment.")
        else:
            if not self.case.recorded_prompt or not self.case.expected_harness_prompt_version:
                raise ValueError("The case must preserve its recorded prompt and harness prompt version.")
            if (
                not configured_prompt
                or str(require_private_path(Path(configured_prompt))) != self.freeze.runtime_prompt_path
            ):
                raise ValueError("Set SCOUT_EVAL_ENVIRONMENT_FILE to this environment's frozen runtime-prompt.json.")
            prompt = read_recorded_prompt(Path(configured_prompt))
            if prompt.harness_prompt_version != self.case.expected_harness_prompt_version:
                raise ValueError("The recorded scout harness version does not match the frozen case.")
        if (
            prompt.team_id != self.seed.team_id
            or prompt.config_id != self.seed.config_id
            or prompt.skill_name != self.case.skill.name
            or prompt.skill_version != self.case.skill.version
            or prompt.allowed_tools != self.case.skill.allowed_tools
        ):
            raise ValueError("The worker prompt configuration belongs to another evaluation environment.")

    def check(self, *, probe_gateway: bool = False) -> dict[str, object]:
        from django.conf import settings  # noqa: PLC0415 -- Django is initialized by the CLI.

        from products.posthog_ai.eval_harness.environment.dataset import EnvironmentDataset  # noqa: PLC0415
        from products.posthog_ai.eval_harness.environment.guard import assert_local_databases  # noqa: PLC0415
        from products.posthog_ai.eval_harness.environment.restore import PreparedEnvironment  # noqa: PLC0415
        from products.signals.backend.scout_harness.eval_environment.ingestion import (  # noqa: PLC0415
            ScoutEnvironmentIngestion,
        )
        from products.signals.backend.scout_harness.eval_environment.state import ScoutEnvironmentState  # noqa: PLC0415
        from products.signals.backend.scout_harness.skill_loader import load_skill_for_run  # noqa: PLC0415

        assert_local_databases()
        self.freeze.verify()
        receipt = PreparedEnvironment.read_receipt(self.freeze_path.parent)
        if receipt is None or receipt.phase != "complete":
            raise ValueError("The frozen scout environment requires a completed import receipt.")
        manifests = [Path(name) for name, digest in self.freeze.inputs.items() if digest == receipt.manifest_sha256]
        if len(manifests) != 1:
            raise ValueError("The completed receipt must identify exactly one frozen environment manifest.")
        restored = PreparedEnvironment.verify(EnvironmentDataset.load(manifests[0]), self.freeze_path.parent)
        if restored.team_id != self.seed.team_id or restored.user_id != self.seed.user_id:
            raise ValueError("The restored data belongs to another scout environment.")
        ScoutEnvironmentState.verify(self.case, receipt, self.seed)
        ScoutEnvironmentIngestion.verify(receipt)
        if not settings.DEBUG:
            raise ValueError("Scout evaluation commands require a local DEBUG environment.")
        self.check_local_routes()
        if not settings.SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE:
            raise ValueError("Private scout capture must be enabled before evaluating scout environments.")
        self.check_prompt_configuration()
        service = self._service()
        skill = load_skill_for_run(service.config.team, self.case.skill.name, version=self.case.skill.version)
        if skill.allowed_tools != self.case.skill.allowed_tools:
            raise ValueError("The reconstructed skill's tool permissions changed.")
        if service.config.structured_output_schema or service.config.mcp_gateway_server_ids:
            raise ValueError("This reconstruction requires capabilities unsupported by existing Scout trials.")
        if probe_gateway:
            self.probe_gateway()
        return {
            "team_id": self.seed.team_id,
            "config_id": str(self.seed.config_id),
            "frozen": True,
            "prompt_mode": self.case.prompt_mode,
            "paid_calls": 0,
            "restored_data": {
                "event_count": restored.event_count,
                "event_validation": "per-event counts and minimum/maximum timestamps",
                "metric_count": restored.metric_count,
                "metric_validation": "complete metric row fields",
            },
        }

    @staticmethod
    def check_local_routes() -> None:
        from django.conf import settings  # noqa: PLC0415 -- Django is initialized by the CLI.

        from products.tasks.backend.facade.gateway import (  # noqa: PLC0415
            resolve_sandbox_ai_product,
            sandbox_product_routed,
        )

        for name in (
            "SANDBOX_API_URL",
            "SANDBOX_MCP_URL",
            "SANDBOX_AI_GATEWAY_URL",
            "SANDBOX_LLM_GATEWAY_URL",
            "AI_GATEWAY_URL",
        ):
            assert_local_url(getattr(settings, name, None), name)
        assert_local_url(os.environ.get("POSTHOG_API_BASE_URL"), "POSTHOG_API_BASE_URL for the MCP service")
        if not settings.SANDBOX_AI_GATEWAY_MINT_KEY:
            raise ValueError("SANDBOX_AI_GATEWAY_MINT_KEY is required for rubric and judge gateway routing.")
        for stage in _SCORING_AI_STAGES:
            product = resolve_sandbox_ai_product("scout_suggestions", stage, internal=True)
            if not sandbox_product_routed(product, stage, settings.SANDBOX_AI_GATEWAY_PRODUCTS or ""):
                raise ValueError(f"SANDBOX_AI_GATEWAY_PRODUCTS must enable {product} for rubric and judge runs.")

    def probe_gateway(self) -> None:
        from products.tasks.backend.facade.gateway import (  # noqa: PLC0415 -- Django is initialized by the CLI.
            mint_private_gateway_token,
            mint_scoped_token,
            resolve_sandbox_ai_product,
            revoke_private_gateway_token,
            revoke_scoped_token,
        )

        service = self._service()
        token = mint_private_gateway_token(
            team_id=self.seed.team_id, user=service.user.distinct_id, expires_in_seconds=60
        )
        revoke_private_gateway_token(token)
        products = {
            resolve_sandbox_ai_product("scout_suggestions", stage, internal=True) for stage in _SCORING_AI_STAGES
        }
        for product in sorted(products):
            scoring_token = mint_scoped_token(
                ai_product=product, team_id=self.seed.team_id, user=service.user.distinct_id, expires_in_seconds=60
            )
            if not scoring_token:
                raise ValueError(
                    f"The {product} gateway credential could not be minted. Check SANDBOX_AI_GATEWAY_MINT_KEY "
                    "and gateway product permissions."
                )
            revoke_scoped_token(scoring_token)

    def _service(self) -> ScoutTrialComparisons:
        from posthog.models import User  # noqa: PLC0415 -- Django is initialized by the CLI.

        from products.signals.backend.models import SignalScoutConfig  # noqa: PLC0415
        from products.signals.backend.scout_harness.trial_access_policy import scout_trial_team_allowed  # noqa: PLC0415
        from products.signals.backend.scout_harness.trial_comparison import ScoutTrialComparisons  # noqa: PLC0415

        config = (
            SignalScoutConfig.objects.for_team(self.seed.team_id).select_related("team").get(id=self.seed.config_id)
        )
        user = User.objects.get(id=self.seed.user_id, is_active=True)
        if not scout_trial_team_allowed(self.seed.team_id) or not user.is_staff:
            raise ValueError("Configure SCOUT_TRIALS_LOCAL_TEAM_ID for the prepared project and use a staff operator.")
        return ScoutTrialComparisons(config, user)

    def _judge_cap_usd(self) -> Decimal:
        from products.tasks.backend.facade.gateway import resolve_sandbox_ai_product, token_cap_usd  # noqa: PLC0415

        product = resolve_sandbox_ai_product("scout_suggestions", "scout:trial_judge", internal=True)
        return Decimal(token_cap_usd(self.seed.team_id, product))

    def plan(self, variants: list[TrialVariant], *, report_checks_per_run: int = 2) -> EvaluationPlan:
        from products.signals.backend.scout_harness.trial_comparison_types import (  # noqa: PLC0415
            TrialComparisonRequest,
            TrialComparisonVariant,
        )
        from products.tasks.backend.facade.gateway import token_cap_usd  # noqa: PLC0415

        self.check()
        if not variants or len({variant.repeats for variant in variants}) != 1:
            raise ValueError("Provide variants with equal repeat counts.")
        scout_cap = Decimal(token_cap_usd(self.seed.team_id, "signals_scout"))
        judge_cap = self._judge_cap_usd()
        request = TrialComparisonRequest(
            comparison_id=uuid4(),
            baseline_variant_id=variants[0].id,
            variants=[
                TrialComparisonVariant(
                    id=variant.id,
                    label=variant.label,
                    launch_ids=[uuid4() for _ in range(variant.repeats)],
                    model=variant.model,
                    reasoning_effort=variant.reasoning_effort,
                    skill_body=variant.skill_body,
                )
                for variant in variants
            ],
            note=self.seed.steering,
            expected_skill_version=self.case.skill.version,
        )
        return EvaluationPlan(
            mode="trial" if sum(variant.repeats for variant in variants) == 1 else "comparison",
            comparison_id=request.comparison_id,
            freeze_sha256=file_sha256(self.freeze_path),
            config_id=self.seed.config_id,
            team_id=self.seed.team_id,
            user_id=self.seed.user_id,
            request=request.model_dump(mode="json"),
            reserved_usd=sum(variant.repeats for variant in variants)
            * (scout_cap * (1 + report_checks_per_run) + (judge_cap if sum(v.repeats for v in variants) > 1 else 0)),
            scout_cap_usd=scout_cap,
            judge_cap_usd=judge_cap,
            report_checks_per_run=report_checks_per_run,
        )

    def launch(self, plan: EvaluationPlan, ledger: BudgetLedger) -> str:
        from posthog.models.scoping import team_scope  # noqa: PLC0415 -- Django is initialized by the CLI.

        with team_scope(self.seed.team_id):
            return self._launch(plan, ledger)

    def _launch(self, plan: EvaluationPlan, ledger: BudgetLedger) -> str:
        from products.signals.backend.scout_harness.trial_comparison_types import (
            TrialComparisonRequest,  # noqa: PLC0415
        )
        from products.signals.backend.temporal.agentic.scout_trial_comparison import (
            start_trial_comparison,  # noqa: PLC0415
        )

        self.check()
        if (
            plan.freeze_sha256 != file_sha256(self.freeze_path)
            or plan.config_id != self.seed.config_id
            or plan.team_id != self.seed.team_id
            or plan.user_id != self.seed.user_id
        ):
            raise ValueError("The plan does not belong to this frozen environment.")
        from products.tasks.backend.facade.gateway import token_cap_usd  # noqa: PLC0415

        request = TrialComparisonRequest.model_validate(plan.request)
        count = sum(len(variant.launch_ids) for variant in request.variants)
        if (
            request.comparison_id != plan.comparison_id
            or request.expected_skill_version != self.case.skill.version
            or request.note != self.seed.steering
            or (plan.mode == "trial") != (count == 1)
        ):
            raise ValueError("The saved request no longer matches its frozen trial plan.")
        scout_cap = Decimal(token_cap_usd(self.seed.team_id, "signals_scout"))
        judge_cap = self._judge_cap_usd()
        plan.validate_budget(request, scout_cap=scout_cap, judge_cap=judge_cap)
        service = self._service()
        service.assert_can_start(launch_ids=[launch for variant in request.variants for launch in variant.launch_ids])
        self.probe_gateway()
        ledger.reserve(plan.comparison_id, plan.reserved_usd, plan_sha256=plan.fingerprint())
        if plan.mode == "trial":
            from products.signals.backend.scout_harness.trial_launch import create_trial_launch  # noqa: PLC0415
            from products.signals.backend.temporal.agentic.scout_scheduler import (  # noqa: PLC0415
                start_trial_signals_scout_run,
            )

            variant = request.variants[0]
            launch = create_trial_launch(
                config=service.config,
                user=service.user,
                launch_id=variant.launch_ids[0],
                model=variant.model,
                reasoning_effort=variant.reasoning_effort,
                skill_body=variant.skill_body,
                note=request.note,
                variant=variant.label,
            )
            from posthog.temporal.common.client import sync_connect  # noqa: PLC0415

            return start_trial_signals_scout_run(
                sync_connect(), team_id=self.seed.team_id, skill_name=self.case.skill.name, launch_id=str(launch.id)
            )
        service.create(request)
        return start_trial_comparison(self.seed.team_id, plan.comparison_id)

    def export(self, plan: EvaluationPlan, destination: Path) -> dict[str, object]:
        from posthog.models.scoping import team_scope  # noqa: PLC0415 -- Django is initialized by the CLI.

        with team_scope(self.seed.team_id):
            return self._export(plan, destination)

    def _export_launch(self, launch_id: UUID, *, context_id: UUID | None = None) -> TrialExport:
        from posthog.storage.object_storage import (
            ObjectStorageError,  # noqa: PLC0415 -- Django is initialized by the CLI.
        )

        from products.signals.backend.models import SignalScoutRun  # noqa: PLC0415
        from products.signals.backend.scout_harness.trial_launch import read_trial_launch  # noqa: PLC0415
        from products.signals.backend.scout_harness.trial_result import (  # noqa: PLC0415
            get_trial_workflow_status,
            read_trial_result,
        )
        from products.signals.backend.scout_harness.trial_state import ScoutTrialStore  # noqa: PLC0415
        from products.tasks.backend.facade.api import (  # noqa: PLC0415
            get_task_run_log_size,
            get_task_run_log_urls,
            read_task_run_log_content,
        )

        try:
            launch = read_trial_launch(self.seed.team_id, launch_id)
        except (ObjectStorageError, OSError, ValueError) as error:
            return TrialExport(
                status="unavailable",
                launch_id=launch_id,
                errors=[f"The saved launch could not be read ({type(error).__name__})."],
            )
        if (
            launch.config_id != self.seed.config_id
            or launch.user_id != self.seed.user_id
            or launch.skill_name != self.case.skill.name
            or launch.skill_version != self.case.skill.version
            or (context_id is not None and launch.context_id != context_id)
        ):
            return TrialExport(
                status="unavailable",
                launch_id=launch_id,
                errors=["The launch does not match this environment and comparison."],
            )
        try:
            run = (
                SignalScoutRun.objects.for_team(self.seed.team_id)
                .select_related("task_run__task")
                .get(
                    scout_config_id=self.seed.config_id,
                    skill_name=self.case.skill.name,
                    skill_version=self.case.skill.version,
                    metadata__scout_trial__version=1,
                    metadata__scout_trial__launch_id=str(launch_id),
                    metadata__scout_trial__context_id=str(launch.context_id),
                    task_run__team_id=self.seed.team_id,
                    task_run__task__team_id=self.seed.team_id,
                    task_run__task__created_by_id=self.seed.user_id,
                    task_run__task__origin_product="signals_scout",
                    task_run__task__origin_key=f"scout-trial:{launch_id}",
                )
            )
        except SignalScoutRun.DoesNotExist:
            workflow = get_trial_workflow_status(team_id=self.seed.team_id, launch_id=launch_id)
            return TrialExport(
                status="pending" if workflow.status == "completed" and workflow.run_id else workflow.status,
                launch_id=launch_id,
                errors=[workflow.error or "No bound scout run is available yet; inspect the comparison status."],
            )
        except SignalScoutRun.MultipleObjectsReturned:
            return TrialExport(
                status="unavailable", launch_id=launch_id, errors=["More than one scout run matches this launch."]
            )

        errors: list[str] = []
        try:
            saved = read_trial_result(run)
            if saved is not None and (
                saved.get("launch_id") != str(launch_id) or saved.get("context_id") != str(launch.context_id)
            ):
                raise ValueError("The stored result belongs to another launch.")
        except (ObjectStorageError, OSError, ValueError) as error:
            saved = None
            errors.append(
                f"The saved result could not be read ({type(error).__name__}); current database state is used."
            )
        if saved is None:
            if not errors:
                errors.append("The saved result is unavailable; current database state is used.")
            saved = {"summary": run.summary}
            try:
                saved["private_state"] = ScoutTrialStore(run).export()
            except (ObjectStorageError, OSError, ValueError) as error:
                errors.append(f"Private run state could not be read ({type(error).__name__}).")
        log = ""
        try:
            urls = get_task_run_log_urls(run.task_run_id, run.task_run.task_id, self.seed.team_id)
            if urls:
                for index, url in enumerate(urls):
                    try:
                        if get_task_run_log_size([url], strict=True) <= 0:
                            errors.append(f"Trace object {index + 1} is missing or empty; the trace may be incomplete.")
                    except (ObjectStorageError, OSError, ValueError) as error:
                        errors.append(
                            f"Trace object {index + 1} availability could not be confirmed ({type(error).__name__})."
                        )
                log = read_task_run_log_content(urls)
            if not log:
                errors.append("No trace content is currently available.")
        except (ObjectStorageError, OSError, ValueError) as error:
            errors.append(f"The trace could not be read ({type(error).__name__}).")
        return TrialExport(
            status=run.task_run.status,
            result=saved,
            log=log,
            launch_id=launch_id,
            run_id=run.id,
            task_run_id=run.task_run_id,
            errors=errors,
        )

    def _export(self, plan: EvaluationPlan, destination: Path) -> dict[str, object]:
        from products.signals.backend.scout_harness.trial_comparison_types import (
            TrialComparisonRequest,  # noqa: PLC0415
        )

        if (
            plan.team_id != self.seed.team_id
            or plan.config_id != self.seed.config_id
            or plan.user_id != self.seed.user_id
        ):
            raise ValueError("The export plan belongs to another environment or operator.")
        if plan.mode == "trial":
            request = TrialComparisonRequest.model_validate(plan.request)
            if len(request.variants) != 1 or len(request.variants[0].launch_ids) != 1:
                raise ValueError("A standalone trial export must identify exactly one launch.")
            exported = self._export_launch(request.variants[0].launch_ids[0])
            write_private_json(destination, exported)
            return {"status": exported.status, "export": str(destination)}
        service = self._service()
        saved_plan = service.read(plan.comparison_id)
        result = service.result(saved_plan)
        body = result.model_dump(mode="json")
        body["run_exports"] = {
            str(launch_id): self._export_launch(launch_id, context_id=saved_plan.context_id).model_dump(mode="json")
            for variant in saved_plan.request.variants
            for launch_id in variant.launch_ids
        }
        write_private_json(destination, body)
        return {"status": result.status, "comparison_id": str(plan.comparison_id), "export": str(destination)}
