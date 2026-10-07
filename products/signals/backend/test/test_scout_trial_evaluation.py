from __future__ import annotations

import json
import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized
from pydantic import BaseModel
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.models import Team, User
from posthog.models.scoping import team_scope
from posthog.storage import object_storage

from products.signals.backend.facade.api import is_scout_trial_judge_context
from products.signals.backend.facade.rubrics import ScoutRubricReferenceContext, default_criteria
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.limits import MAX_TRIAL_RUNS
from products.signals.backend.scout_harness.run_gates import check_fleet_gates
from products.signals.backend.scout_harness.trial_comparison import (
    ScoutTrialComparisons,
    comparison_evaluation_finished,
    prepare_comparison_evaluation,
)
from products.signals.backend.scout_harness.trial_comparison_types import (
    TrialComparisonPlan,
    TrialComparisonRequest,
    TrialComparisonVariant,
    TrialComparisonVariantResult,
)
from products.signals.backend.scout_harness.trial_evaluation import (
    JUDGE_PROMPT_VERSION,
    MAX_EVIDENCE_BYTES,
    TrialEvaluationError,
    TrialEvaluationNotReady,
    _read_trial_judge_input,
    assert_evaluation_access,
    finish_trial_evaluation,
    prepare_trial_evaluation,
    read_trial_evaluation,
    read_trial_evaluation_report,
    read_trial_evidence_sources,
    run_evaluation_run,
    trial_evidence_storage_key,
)
from products.signals.backend.scout_harness.trial_evaluation_types import (
    TrialCriterionVerdict,
    TrialEvaluationRequest,
    TrialEvaluationSnapshot,
    TrialEvaluationVariant,
    TrialEvidenceSource,
    TrialRunEvidence,
    TrialRunJudgment,
)
from products.signals.backend.scout_harness.trial_judge import TrialJudgeExecutionError, parse_trial_judgment
from products.signals.backend.scout_harness.trial_launch import (
    ScoutTrialLaunchError,
    ScoutTrialsDisabled,
    TrialContext,
    TrialLaunch,
)
from products.signals.backend.scout_harness.trial_result import TrialWorkflowStatus, export_trial_result
from products.signals.backend.scout_harness.trial_rubrics import SavedScoutRubricReader
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore, TrialReport
from products.signals.backend.temporal.agentic.scout_trial_evaluation import (
    RunScoutTrialEvaluationWorkflow,
    TrialEvaluationInput,
    TrialEvaluationRunInput,
    finish_scout_trial_evaluation_activity,
    load_scout_trial_evaluation_activity,
    start_trial_evaluation,
)
from products.signals.backend.test.test_scout_harness_api import _make_run
from products.signals.backend.test.test_scout_trial_judge import _reference_context, _snapshot
from products.signals.backend.trial_judging import TrialJudgeInput, build_trial_judge_prompt
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.models import Task
from products.tasks.backend.temporal.oauth import create_oauth_access_token_for_run  # tach-ignore

if TYPE_CHECKING:
    pass

MODULE = "products.signals.backend.scout_harness.trial_evaluation"
JUDGE_MODULE = "products.signals.backend.scout_harness.trial_judge"
WORKFLOW_MODULE = "products.signals.backend.temporal.agentic.scout_trial_evaluation"


@override_settings(
    SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=True,
    AI_GATEWAY_URL="https://gateway.example/v1",
    AI_GATEWAY_API_KEY="phs_synthetic_api_key",
    SANDBOX_AI_GATEWAY_URL="https://gateway.example",
    SANDBOX_AI_GATEWAY_MINT_KEY="phs_synthetic_mint_key",
)
class TestScoutTrialEvaluationValidation(SimpleTestCase):
    @parameterized.expand(["duplicate_variant", "duplicate_launch", "missing_baseline"])
    def test_rejects_ambiguous_groups_before_loading_evidence(self, invalid: str) -> None:
        first = TrialEvaluationVariant(id=uuid4(), label="Baseline", launch_ids=[uuid4()])
        second = TrialEvaluationVariant(id=uuid4(), label="Candidate", launch_ids=[uuid4()])
        baseline = first.id
        if invalid == "duplicate_variant":
            second = second.model_copy(update={"id": first.id})
        elif invalid == "duplicate_launch":
            second = second.model_copy(update={"launch_ids": first.launch_ids})
        elif invalid == "missing_baseline":
            baseline = uuid4()
        request = TrialEvaluationRequest(
            evaluation_id=uuid4(), baseline_variant_id=baseline, variants=[first, second], rubric_source="saved"
        )
        with self.assertRaises(TrialEvaluationError):
            prepare_trial_evaluation(config=SignalScoutConfig(team_id=2), user=User(id=17), request=request)

    @parameterized.expand([False, True])
    def test_malformed_snapshot_error_does_not_expose_source_text(self, per_run: bool) -> None:
        with patch(f"{MODULE}.object_storage.read", return_value=json.dumps({"team_id": "private fixture value"})):
            with self.assertRaisesMessage(TrialEvaluationError, "The saved evaluation document is invalid.") as error:
                if per_run:
                    _read_trial_judge_input(2, uuid4(), uuid4())
                else:
                    read_trial_evaluation(2, uuid4())
        assert "private fixture value" not in str(error.exception)

    @parameterized.expand(["team", "evaluation", "request", "launch", "variant", "multiple_runs"])
    def test_rejects_judge_input_bound_to_another_trial(self, mismatch: str) -> None:
        snapshot = _snapshot()
        launch_id = snapshot.runs[0].launch_id
        evaluation_id = snapshot.evaluation_id
        if mismatch == "team":
            snapshot = snapshot.model_copy(update={"team_id": 3})
        elif mismatch == "evaluation":
            snapshot = snapshot.model_copy(update={"evaluation_id": uuid4()})
        elif mismatch == "request":
            snapshot = snapshot.model_copy(
                update={"request": snapshot.request.model_copy(update={"evaluation_id": uuid4()})}
            )
        elif mismatch in {"launch", "variant"}:
            snapshot = snapshot.model_copy(
                update={"runs": [snapshot.runs[0].model_copy(update={f"{mismatch}_id": uuid4()})]}
            )
        else:
            snapshot = snapshot.model_copy(update={"runs": snapshot.runs * 2})
        with patch(f"{MODULE}.object_storage.read", return_value=snapshot.model_dump_json()):
            with self.assertRaisesMessage(TrialEvaluationError, "The saved judge input does not match this trial."):
                _read_trial_judge_input(2, evaluation_id, launch_id)


@override_settings(
    SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=True,
    AI_GATEWAY_URL="https://gateway.example/v1",
    AI_GATEWAY_API_KEY="phs_synthetic_api_key",
    SANDBOX_AI_GATEWAY_URL="https://gateway.example",
    SANDBOX_AI_GATEWAY_MINT_KEY="phs_synthetic_mint_key",
)
class TestScoutTrialEvaluation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.trials_flag = self.enterContext(
            patch("products.signals.backend.scout_harness.trial_launch.feature_enabled", return_value=True)
        )
        if self.team.id != 2:
            self.team = Team.objects.create(id=2, organization=self.organization, name="Internal example")
        self.enterContext(team_scope(self.team.id, canonical=True))
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.skill = LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-example",
            version=1,
            body="Inspect the synthetic checkout result.",
            allowed_tools=["emit_report"],
        )
        self.config = SignalScoutConfig.objects.create(team=self.team, skill_name=self.skill.name, enabled=False)
        self.reference = _reference_context(
            skill_id=str(self.skill.id),
            skill_name=self.skill.name,
            instructions=self.skill.body,
        )
        self.config.rubrics = {
            "revision": 1,
            "criteria": [criterion.model_dump(mode="json") for criterion in default_criteria()],
            "reference_context": self.reference.model_dump(mode="json"),
            "reference_generation_id": str(uuid4()),
        }
        self.config.save(update_fields=["rubrics"])
        self.context = TrialContext(
            id=uuid4(),
            team_id=self.team.id,
            config_id=self.config.id,
            user_id=self.user.id,
            created_at=timezone.now(),
            skill_name=self.skill.name,
            skill_version=1,
            skill_body=self.skill.body,
            skill_origin="custom",
            allowed_tools=["emit_report"],
            capabilities={},
            runtime_adapter="codex",
            model="gpt-5.5",
            reasoning_effort="medium",
            note="Use only the example fixture.",
        )
        self.launch = TrialLaunch(
            id=uuid4(),
            team_id=self.team.id,
            config_id=self.config.id,
            user_id=self.user.id,
            context_id=self.context.id,
            created_at=timezone.now(),
            skill_name=self.skill.name,
            skill_version=1,
            skill_body=self.skill.body,
            runtime_adapter="codex",
            model="gpt-5.5",
            reasoning_effort="medium",
            note=self.context.note,
            request_hash="synthetic-launch",
        )
        self.documents: dict[str, str] = {}
        self._save("contexts", self.context.id, self.context)
        self._save("launches", self.launch.id, self.launch)
        self.enterContext(
            patch.object(object_storage, "read", side_effect=lambda key, **kwargs: self.documents.get(key))
        )
        self.enterContext(patch.object(object_storage, "write", side_effect=self._write))
        self.enterContext(patch(f"{MODULE}.get_task_run_log_urls", return_value=None))
        self.enterContext(
            patch(f"{MODULE}.get_trial_workflow_status", return_value=TrialWorkflowStatus(status="completed"))
        )
        marker = {"version": 1, "context_id": str(self.context.id), "launch_id": str(self.launch.id)}
        self.scout_run = _make_run(
            self.team,
            scout_config=self.config,
            skill_name=self.skill.name,
            task_run_status="completed",
            summary="The synthetic checkout total is correct.",
            metadata={"scout_trial": marker},
        )
        task = self.scout_run.task_run.task
        task.created_by = self.user
        task.origin_product = "signals_scout"
        task.origin_key = f"scout-trial:{self.launch.id}"
        task.save(update_fields=["created_by", "origin_product", "origin_key"])
        self.scout_run.task_run.state = {
            "scout_trial": marker,
            "runtime_adapter": "codex",
            "model": "gpt-5.5",
            "reasoning_effort": "medium",
            "service_tier": None,
            "token_usage": {"input_tokens": 120, "output_tokens": 30},
        }
        self.scout_run.task_run.save(update_fields=["state"])
        variant = TrialEvaluationVariant(id=uuid4(), label="Baseline", launch_ids=[self.launch.id])
        self.request = TrialEvaluationRequest(
            evaluation_id=uuid4(), baseline_variant_id=variant.id, variants=[variant], rubric_source="saved"
        )

    def _save(self, kind: str, identifier: UUID, document: BaseModel) -> None:
        self.documents[f"signals/scout-trials/{self.team.id}/{kind}/{identifier}.json"] = document.model_dump_json()

    def _write(self, key: str, content: str, **kwargs: object) -> None:
        if key in self.documents:
            raise object_storage.ObjectStorageError("Object already exists")
        self.documents[key] = content

    def _sources(self, snapshot: TrialEvaluationSnapshot) -> list[TrialEvidenceSource]:
        return read_trial_evidence_sources(snapshot, snapshot.runs[0])

    def test_saves_and_reads_frozen_evidence_for_more_than_twenty_runs(self) -> None:
        template = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request).runs[0]
        variants = [
            TrialEvaluationVariant(id=uuid4(), label=f"Version {index + 1}", launch_ids=[uuid4() for _ in range(6)])
            for index in range(20)
        ]
        request = TrialEvaluationRequest(
            evaluation_id=uuid4(), baseline_variant_id=variants[0].id, variants=variants, rubric_source="saved"
        )
        for variant in variants:
            for launch_id in variant.launch_ids:
                self._save("launches", launch_id, self.launch.model_copy(update={"id": launch_id}))

        def evidence(
            launch: TrialLaunch,
            context: TrialContext,
            variant_id: UUID,
            *,
            evaluation_id: UUID,
            rubric_reference_context: ScoutRubricReferenceContext,
        ) -> TrialRunEvidence:
            return template.model_copy(update={"launch_id": launch.id, "variant_id": variant_id})

        with patch(f"{MODULE}._run_evidence", side_effect=evidence):
            snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=request)

        assert len(snapshot.runs) == 120
        assert len(snapshot.model_dump_json().encode()) < 512 * 1024
        assert all(not run.sources for run in snapshot.runs)
        assert read_trial_evaluation(self.team.id, request.evaluation_id) == snapshot
        selected = snapshot.runs[0]
        judgment = TrialRunJudgment(
            launch_id=selected.launch_id,
            variant_id=selected.variant_id,
            status="judge_error",
            summary="Synthetic unavailable judgment.",
        )
        with (
            patch(f"{MODULE}.read_trial_evaluation", side_effect=AssertionError("Judge loaded the full comparison")),
            patch(f"{JUDGE_MODULE}.judge_trial_run", AsyncMock(return_value=judgment)) as judge,
        ):
            async_to_sync(run_evaluation_run)(self.team.id, snapshot.evaluation_id, selected.launch_id)
        judge.assert_awaited_once()
        assert judge.await_args is not None
        judge_snapshot, judge_evidence = judge.await_args.args
        assert judge_snapshot == snapshot.model_copy(update={"runs": [selected]})
        assert judge_evidence == selected

    def test_judge_input_preparation_recovers_without_changing_frozen_evidence(self) -> None:
        def interrupted_write(key: str, content: str, **kwargs: object) -> None:
            if "/judge-inputs/" in key:
                raise object_storage.ObjectStorageError("Synthetic interrupted preparation")
            self._write(key, content, **kwargs)

        with patch.object(object_storage, "write", side_effect=interrupted_write):
            with self.assertRaises(object_storage.ObjectStorageError):
                prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        saved = read_trial_evaluation(self.team.id, self.request.evaluation_id)
        assert saved is not None
        self.scout_run.summary = "This later edit must not change the frozen judge input."
        self.scout_run.save(update_fields=["summary"])
        changed_request = self.request.model_copy(
            update={"variants": [self.request.variants[0].model_copy(update={"label": "Different request"})]}
        )
        with patch.object(object_storage, "write") as write:
            with self.assertRaisesMessage(TrialEvaluationError, "different request"):
                prepare_trial_evaluation(config=self.config, user=self.user, request=changed_request)
            write.assert_not_called()
        assert prepare_trial_evaluation(config=self.config, user=self.user, request=self.request) == saved
        assert _read_trial_judge_input(self.team.id, saved.evaluation_id, self.launch.id) == saved

    def test_snapshot_is_frozen_and_reused_only_for_the_same_request(self) -> None:
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        assert snapshot.judge_prompt_version == JUDGE_PROMPT_VERSION
        assert snapshot.judge_model == "gpt-6-astra"
        self.scout_run.summary = "A later edit must not change the evidence."
        self.scout_run.save(update_fields=["summary"])
        self.skill.body = "The current skill changed after capture."
        self.skill.save(update_fields=["body"])
        self.config.rubrics = {}
        self.config.save(update_fields=["rubrics"])
        repeat = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        assert repeat == snapshot
        assert (
            next(source.text for source in self._sources(snapshot) if source.kind == "summary")
            == "The synthetic checkout total is correct."
        )
        assert snapshot.runs[0].input_tokens == 120
        assert snapshot.criteria
        assert snapshot.rubric_reference_context == self.reference
        changed = self.request.model_copy(
            update={"variants": [self.request.variants[0].model_copy(update={"label": "Changed"})]}
        )
        with self.assertRaisesMessage(TrialEvaluationError, "different request"):
            prepare_trial_evaluation(config=self.config, user=self.user, request=changed)

    def test_saved_report_remains_readable_when_launches_are_disabled(self) -> None:
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        report = finish_trial_evaluation(self.team.id, snapshot.evaluation_id)
        with override_settings(SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=False):
            assert_evaluation_access(snapshot, config=self.config, user=self.user)
            assert read_trial_evaluation_report(snapshot) == report
            with self.assertRaises(ScoutTrialLaunchError):
                prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)

    @parameterized.expand(
        [
            ("unsaved", "Review and save"),
            ("legacy", "no saved reference instructions"),
            ("disabled", "1 to 30 uniquely named enabled criteria"),
            ("instructions_truncated", "reference instructions are incomplete"),
            ("reference_files_truncated", "reference instructions are incomplete"),
            ("omitted_reference", "reference instructions are incomplete"),
            ("truncated_reference", "reference instructions are incomplete"),
            ("wrong_scout", "do not belong to this scout"),
            ("malformed", "saved rubric is invalid"),
        ]
    )
    def test_unreviewed_or_incomplete_rubric_cannot_create_an_evaluation(self, scenario: str, message: str) -> None:
        rubric = self.config.rubrics
        assert isinstance(rubric, dict)
        if scenario == "unsaved":
            rubric = {}
        elif scenario == "legacy":
            rubric.pop("reference_context")
        elif scenario == "disabled":
            for criterion in rubric["criteria"]:
                criterion["enabled"] = False
        elif scenario in {"instructions_truncated", "reference_files_truncated"}:
            rubric["reference_context"][scenario] = True
        elif scenario == "omitted_reference":
            rubric["reference_context"]["reference_limits"]["omitted_files"] = 1
        elif scenario == "truncated_reference":
            rubric["reference_context"]["reference_limits"]["truncated_files"] = ["rules.md"]
        elif scenario == "wrong_scout":
            rubric["reference_context"]["skill_name"] = "signals-scout-other-example"
        elif scenario == "malformed":
            rubric["reference_context"]["skill_version"] = "private malformed source text"
        self.config.rubrics = rubric
        self.config.save(update_fields=["rubrics"])
        with self.assertRaisesMessage(TrialEvaluationError, message) as raised:
            prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        assert "private malformed source text" not in str(raised.exception)
        assert not any("/evaluations/" in key for key in self.documents)

    def test_saved_requirements_ignore_source_edits_candidates_and_unaccepted_suggestions(self) -> None:
        rubric = self.config.rubrics
        assert isinstance(rubric, dict)
        reference_paths = [f"references/checkout-{index}.md" for index in range(3)]
        self.reference = ScoutRubricReferenceContext.model_validate(
            {
                **self.reference.model_dump(mode="json"),
                "reference_files": reference_paths,
                "reference_texts": [
                    {
                        "path": path,
                        "content_type": "text/markdown",
                        "content": "A synthetic checkout must include the terminal result.\n" * 14_000,
                    }
                    for path in reference_paths
                ],
            }
        )
        assert len(self.reference.model_dump_json().encode()) > 2 * 1024 * 1024
        rubric["reference_context"] = self.reference.model_dump(mode="json")
        self.skill.is_latest = False
        self.skill.save(update_fields=["is_latest"])
        LLMSkill.objects.create(
            team=self.team,
            name=self.skill.name,
            version=2,
            body="The current scout has a different job.",
            allowed_tools=["emit_report"],
        )
        self.launch = self.launch.model_copy(update={"skill_body": "Do no work."})
        self._save("launches", self.launch.id, self.launch)
        disabled = {
            **rubric["criteria"][0],
            "id": "custom-disabled",
            "source": "custom",
            "enabled": False,
        }
        rubric["criteria"].append(disabled)
        rubric["generation"] = {
            "id": str(uuid4()),
            "status": "completed",
            "requested_at": timezone.now().isoformat(),
            "suggestions": [{**disabled, "id": "custom-draft", "enabled": True}],
            "reference_context": self.reference.model_copy(
                update={"instructions": "Unaccepted new instructions."}
            ).model_dump(mode="json"),
        }
        self.config.save(update_fields=["rubrics"])
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        assert snapshot.rubric_reference_context == self.reference
        assert snapshot.rubric_reference_generation_id == rubric["reference_generation_id"]
        assert {criterion.id for criterion in snapshot.criteria} == {criterion.id for criterion in default_criteria()}
        sources = self._sources(snapshot)
        assert next(source.text for source in sources if source.id == "instructions") == "Do no work."
        reference = next(source for source in sources if source.id == "rubric-reference")
        assert reference.kind == "instructions"
        assert json.loads(reference.text) == self.reference.model_dump(mode="json")
        prompt = build_trial_judge_prompt(
            TrialJudgeInput(
                criteria=snapshot.criteria,
                rubric_reference_context=snapshot.rubric_reference_context.model_dump(mode="json"),
                judge_model=snapshot.judge_model,
                judge_prompt_version=snapshot.judge_prompt_version,
            ),
            snapshot.runs[0],
        )
        assert "rubric-reference.txt" in prompt
        assert self.reference.instructions not in prompt
        assert len(prompt.encode()) < 256 * 1024

    @parameterized.expand(["pass", "fail", "not_applicable"])
    def test_launch_note_alone_cannot_support_a_conclusive_verdict(self, verdict: str) -> None:
        claim = "I read the required skill successfully."
        self.launch = self.launch.model_copy(update={"note": claim})
        self.context = self.context.model_copy(update={"notes": [{"body": "A prior review is available."}]})
        self._save("launches", self.launch.id, self.launch)
        self._save("contexts", self.context.id, self.context)
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        sources = self._sources(snapshot)
        note = next(source for source in sources if source.text == claim)
        context = next(source for source in sources if source.kind == "context")
        assert claim not in context.text
        assert json.loads(context.text)["notes"] == self.context.notes
        judgment = parse_trial_judgment(
            json.dumps(
                {
                    "summary": claim,
                    "criteria": [
                        {
                            "criterion_id": criterion.id,
                            "verdict": verdict,
                            "reason": claim,
                            "confidence": "high",
                            "evidence": [{"source_id": note.id, "quote": claim}],
                        }
                        for criterion in snapshot.criteria
                    ],
                }
            ),
            criteria=snapshot.criteria,
            sources=sources,
        )
        assert all(criterion.verdict == "unknown" for criterion in judgment.criteria)
        assert claim not in judgment.summary

    @parameterized.expand([(None,), ("failed",), ("cancelled",)])
    def test_invalidation_after_export_excludes_the_trial(self, task_status: str | None) -> None:
        export_trial_result(self.scout_run, status="completed")
        if task_status is None:
            ScoutTrialStore(self.scout_run).invalidate("The runtime changed after export.", allow_terminal=True)
        else:
            self.scout_run.task_run.status = task_status
            self.scout_run.task_run.save(update_fields=["status"])
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        assert snapshot.runs[0].exclusion_reason is not None
        assert snapshot.runs[0].execution_status == (task_status or "completed")
        judge = AsyncMock()
        with patch(f"{JUDGE_MODULE}.judge_trial_run", judge):
            async_to_sync(run_evaluation_run)(self.team.id, snapshot.evaluation_id, self.launch.id)
        judge.assert_not_called()
        report = finish_trial_evaluation(self.team.id, snapshot.evaluation_id)
        assert report.runs[0].status == "excluded"

    @parameterized.expand(
        ["user_id", "context_id", "model", "runtime_adapter", "reasoning_effort", "service_tier", "skill_body"]
    )
    def test_rejects_mixed_launch_ownership_context_or_settings(self, field: str) -> None:
        changes: dict[str, object] = {"id": uuid4()}
        changes[field] = {
            "user_id": self.user.id + 1,
            "context_id": uuid4(),
            "model": "different-model",
            "runtime_adapter": "claude",
            "reasoning_effort": "high",
            "service_tier": "priority",
            "skill_body": "Different instructions.",
        }[field]
        other = self.launch.model_copy(update=changes)
        self._save("launches", other.id, other)
        variant = self.request.variants[0].model_copy(update={"launch_ids": [self.launch.id, other.id]})
        request = self.request.model_copy(update={"variants": [variant]})
        with self.assertRaises(TrialEvaluationError):
            prepare_trial_evaluation(config=self.config, user=self.user, request=request)

    def test_private_task_owner_must_match_the_saved_launch(self) -> None:
        task = self.scout_run.task_run.task
        task.created_by = None
        task.save(update_fields=["created_by"])
        with self.assertRaisesMessage(TrialEvaluationError, "private task and operator"):
            prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)

    @parameterized.expand(
        [
            "valid",
            "evaluation_id",
            "launch_id",
            "context_id",
            "source_task_id",
            "source_task_run_id",
            "source_scout_run_id",
            "user_id",
            "caller_user",
            "caller_team",
            "source_origin",
            "source_state",
            "source_status",
            "source_deleted",
            "source_invalidated",
            "operator_revoked",
        ]
    )
    def test_judge_credentials_require_the_exact_saved_evaluation_and_private_source(self, mismatch: str) -> None:
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        evidence = snapshot.runs[0]
        marker: dict[str, str | int] = {
            "version": 1,
            "evaluation_id": str(snapshot.evaluation_id),
            "launch_id": str(evidence.launch_id),
            "context_id": str(snapshot.context_id),
            "user_id": snapshot.user_id,
            "source_task_id": str(evidence.task_id),
            "source_task_run_id": str(evidence.task_run_id),
            "source_scout_run_id": str(evidence.run_id),
        }
        team_id, user_id = self.team.id, self.user.id
        if mismatch == "user_id":
            marker["user_id"] = user_id + 1
        elif mismatch in marker:
            marker[mismatch] = str(uuid4())
        elif mismatch == "caller_team":
            team_id += 1
        elif mismatch == "caller_user":
            user_id += 1
        elif mismatch == "source_origin":
            task = self.scout_run.task_run.task
            task.origin_key = "ordinary-task"
            task.save(update_fields=["origin_key"])
        elif mismatch == "source_state":
            self.scout_run.task_run.state["scout_trial"] = {}
            self.scout_run.task_run.save(update_fields=["state"])
        elif mismatch == "source_status":
            self.scout_run.task_run.status = "failed"
            self.scout_run.task_run.save(update_fields=["status"])
        elif mismatch == "source_deleted":
            task = self.scout_run.task_run.task
            task.deleted = True
            task.save(update_fields=["deleted"])
        elif mismatch == "source_invalidated":
            ScoutTrialStore(self.scout_run).invalidate("Synthetic invalidation", allow_terminal=True)
        elif mismatch == "operator_revoked":
            self.user.is_staff = False
            self.user.save(update_fields=["is_staff"])
            with self.assertRaises(TrialEvaluationError):
                is_scout_trial_judge_context(team_id=team_id, user_id=user_id, marker=marker)
            return
        assert is_scout_trial_judge_context(team_id=team_id, user_id=user_id, marker=marker) is (mismatch == "valid")
        if mismatch == "valid":
            judge_task = Task.objects.create(
                team=self.team,
                created_by=self.user,
                title="Synthetic trial judge",
                origin_product=Task.OriginProduct.SIGNALS_SCOUT,
                origin_key=f"scout-trial-judge:{snapshot.evaluation_id}:{evidence.launch_id}",
            )
            judge_run = judge_task.create_run(extra_state={"scout_trial_judge": marker, "use_dedicated_stream": False})
            with patch(
                "products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user",
                return_value="synthetic-judge-token",
            ) as mint:
                assert (
                    create_oauth_access_token_for_run(judge_task, judge_run.state, scopes="full")
                    == "synthetic-judge-token"
                )
            assert mint.call_args.kwargs["scopes"] == "signals_scout_judge"
            assert mint.call_args.kwargs["sandbox_task_id"] == judge_task.id

    @parameterized.expand(
        [(bound, status, None) for bound in (False, True) for status in ("pending", "unknown", "not_started")]
        + [
            (True, status, task_status)
            for status in ("completed", "failed", "cancelled", "skipped")
            for task_status in ("not_started", "queued", "in_progress")
        ]
    )
    def test_launch_needs_finalized_scout_and_task_before_scoring(
        self,
        bound: bool,
        status: Literal["pending", "unknown", "not_started", "completed", "failed", "cancelled", "skipped"],
        task_status: str | None,
    ) -> None:
        other = self.launch if bound else self.launch.model_copy(update={"id": uuid4()})
        self._save("launches", other.id, other)
        variant = self.request.variants[0].model_copy(update={"launch_ids": [other.id]})
        request = self.request.model_copy(update={"variants": [variant]})
        if task_status is not None:
            self.scout_run.task_run.status = task_status
            self.scout_run.task_run.save(update_fields=["status"])
            if status != "skipped":
                export_trial_result(self.scout_run, status=status)
        with patch(f"{MODULE}.get_trial_workflow_status", return_value=TrialWorkflowStatus(status=status)):
            with self.assertRaisesMessage(
                TrialEvaluationError, "task must finish" if task_status is not None else "known terminal state"
            ):
                prepare_trial_evaluation(config=self.config, user=self.user, request=request)
        assert not any("/evaluations/" in key for key in self.documents)
        if task_status is None:
            assert not any("/results/" in key for key in self.documents)

    @parameterized.expand(["foreign_chain", "oversized"])
    def test_trace_reads_reject_inherited_logs_and_fail_explicitly_above_sandbox_limit(self, scenario: str) -> None:
        urls = [self.scout_run.task_run.log_url]
        if scenario == "foreign_chain":
            urls.insert(0, "s3://example/another-run.jsonl")
        with (
            patch(f"{MODULE}.get_task_run_log_urls", return_value=urls),
            patch(f"{MODULE}.get_task_run_log_size", return_value=MAX_EVIDENCE_BYTES + 1),
            patch(f"{MODULE}.read_task_run_log_content") as read_content,
        ):
            if scenario == "oversized":
                with self.assertRaisesMessage(TrialEvaluationError, "128 MiB"):
                    prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
                assert read_trial_evaluation(self.team.id, self.request.evaluation_id) is None
            else:
                snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
                assert not any(file.kind == "trace" for file in snapshot.runs[0].files)
                assert any("inherited resume-chain" in limitation for limitation in snapshot.runs[0].limitations)
        read_content.assert_not_called()

    @parameterized.expand(["head", "read", "empty"])
    def test_transient_trace_storage_failure_does_not_freeze_evidence(self, failure_step: str) -> None:
        log = json.dumps(
            {
                "notification": {
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "tool_call_update",
                            "toolCallId": "example",
                            "status": "completed",
                            "rawOutput": "The independent check succeeded.",
                        }
                    },
                }
            }
        )
        with (
            patch(f"{MODULE}.get_task_run_log_urls", return_value=[self.scout_run.task_run.log_url]),
            patch("posthog.storage.object_storage.head_object", return_value=None) as lenient_head,
            patch(
                "posthog.storage.object_storage.head_object_strict", return_value={"ContentLength": len(log)}
            ) as head,
            patch(f"{MODULE}.read_task_run_log_content", return_value=log) as read,
        ):
            failing = head if failure_step == "head" else read
            if failure_step == "empty":
                read.return_value = ""
            else:
                failing.side_effect = object_storage.ObjectStorageError("Private synthetic storage detail")
            with self.assertRaisesMessage(TrialEvaluationNotReady, "Retry this evaluation") as failure:
                prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
            assert "Private synthetic" not in str(failure.exception)
            assert not any("/evaluations/" in key for key in self.documents)
            failing.side_effect = None
            read.return_value = log
            snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        lenient_head.assert_not_called()
        assert snapshot.evaluation_id == self.request.evaluation_id
        assert any("The independent check succeeded." in source.text for source in self._sources(snapshot))

    def test_multiple_large_reports_and_final_tool_evidence_are_preserved(self) -> None:
        reports = [
            TrialReport(id=f"synthetic-report-{index}", document={"summary": f"Finding {index}. " * 3000})
            for index in range(4)
        ]
        self.scout_run.task_run.state["scout_trial_private"] = {
            "reports": {report.id: report.model_dump(mode="json") for report in reports}
        }
        self.scout_run.task_run.save(update_fields=["state"])
        log = json.dumps(
            {
                "notification": {
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "tool_call_update",
                            "toolCallId": "readback",
                            "status": "completed",
                            "rawOutput": "The final saved measurement was read back.",
                        }
                    },
                }
            }
        )
        with (
            patch(f"{MODULE}.get_task_run_log_urls", return_value=[self.scout_run.task_run.log_url]),
            patch(f"{MODULE}.get_task_run_log_size", return_value=len(log)),
            patch(f"{MODULE}.read_task_run_log_content", return_value=log),
        ):
            snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        sources = self._sources(snapshot)
        assert len([source for source in sources if source.kind == "report"]) == 4
        for index in range(4):
            assert any(source.kind == "report" and f"Finding {index}." in source.text for source in sources)
        assert any(
            source.kind == "trace" and "The final saved measurement was read back." in source.text for source in sources
        )

    @parameterized.expand(["duplicated", "edited"])
    def test_full_logs_and_reports_are_saved_as_files_outside_the_snapshot(self, report_kind: str) -> None:
        self.scout_run.summary = "Synthetic finding. " * 12000
        self.scout_run.save(update_fields=["summary"])
        final_summary = "Synthetic authored finding. " * 320
        original_summary = final_summary if report_kind == "duplicated" else "Earlier synthetic finding. " * 12
        captured_report = TrialReport(
            id=str(uuid4()),
            document={"title": "Synthetic report", "summary": final_summary, "flag": True},
            payload={"title": "Synthetic report", "summary": original_summary, "repository": "NO_REPO", "flag": 1},
            edits=[{"summary": final_summary}] if report_kind == "edited" else [],
            operator_metadata={"skipped_automatic_repository_selection": False},
            artefacts=[{"type": "note", "content": "Synthetic diagnostic detail. " * 250}],
        )
        self.scout_run.task_run.state["scout_trial_private"] = {
            "reports": {captured_report.id: captured_report.model_dump(mode="json")}
        }
        self.scout_run.task_run.save(update_fields=["state"])
        log = (
            "\n".join(
                json.dumps(
                    {
                        "notification": {
                            "method": "session/update",
                            "params": {
                                "update": {
                                    "sessionUpdate": "tool_call_update",
                                    "toolCallId": f"call-{index}",
                                    "status": "completed",
                                    "rawOutput": "Synthetic measured value. " * 300,
                                }
                            },
                        }
                    }
                )
                for index in range(320)
            )
            + '\n{"final_synthetic_measurement": "The independent check failed near the end."}'
        )
        assert len(log.encode()) > 2 * 1024 * 1024
        with (
            patch(f"{MODULE}.get_task_run_log_urls", return_value=[self.scout_run.task_run.log_url]),
            patch(f"{MODULE}.get_task_run_log_size", return_value=len(log.encode())),
            patch(f"{MODULE}.read_task_run_log_content", return_value=log),
        ):
            snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        assert not snapshot.runs[0].sources
        assert len(snapshot.model_dump_json().encode()) < 32 * 1024
        assert not any("truncated" in item for item in snapshot.runs[0].limitations)
        sources = self._sources(snapshot)
        assert next(source.text for source in sources if source.kind == "summary") == self.scout_run.summary
        assert next(source.text for source in sources if source.kind == "trace") == log
        report = next(source for source in sources if source.kind == "report")
        packed = json.loads(report.text)["report"]
        assert packed["document"] == captured_report.document
        assert packed["edits"] == captured_report.edits
        assert packed["operator_metadata"] == captured_report.operator_metadata
        if report_kind == "duplicated":
            assert report.text.count(final_summary) == 1
        else:
            assert packed["captured_submission_details"]["summary"] == original_summary
        report_document = finish_trial_evaluation(self.team.id, snapshot.evaluation_id)
        assert len(report_document.model_dump_json().encode()) < 32 * 1024

    @parameterized.expand(["changed", "missing", "foreign_run", "duplicate", "renamed"])
    def test_evidence_loader_rejects_missing_changed_or_misbound_originals(self, corruption: str) -> None:
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        evidence = snapshot.runs[0]
        file = evidence.files[0]
        key = trial_evidence_storage_key(snapshot, evidence, file)
        if corruption == "changed":
            self.documents[key] = "Different private content."
        elif corruption == "missing":
            del self.documents[key]
        elif corruption == "foreign_run":
            evidence = evidence.model_copy(update={"launch_id": uuid4()})
        elif corruption == "duplicate":
            evidence = evidence.model_copy(update={"files": evidence.files * 2})
        else:
            evidence = evidence.model_copy(update={"files": [file.model_copy(update={"filename": "other.txt"})]})
        with self.assertRaises(TrialEvaluationError) as error:
            read_trial_evidence_sources(snapshot, evidence)
        assert "Different private content" not in str(error.exception)

    @parameterized.expand(
        [
            (False, "returned"),
            (True, "returned"),
            (False, "unexpected"),
            (False, "revocation"),
        ]
    )
    def test_retries_do_not_repeat_paid_judgments(self, interrupted: bool, failure_kind: str) -> None:
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        judgment = TrialRunJudgment(
            launch_id=self.launch.id,
            variant_id=self.request.baseline_variant_id,
            status="judge_error",
            summary="Synthetic unavailable judgment.",
            error="Synthetic failure",
        )
        judge = AsyncMock(return_value=judgment)
        if failure_kind == "unexpected":
            judge.side_effect = RuntimeError("Private synthetic failure detail")
        elif failure_kind == "revocation":
            judge.side_effect = TrialJudgeExecutionError(
                "The private evaluation failed at credential_revocation (RuntimeError). No exception details were saved."
            )
        with patch(f"{JUDGE_MODULE}.judge_trial_run", judge):
            async_to_sync(run_evaluation_run)(self.team.id, snapshot.evaluation_id, self.launch.id)
            if interrupted:
                del self.documents[
                    f"signals/scout-trials/{self.team.id}/evaluations/{snapshot.evaluation_id}/runs/{self.launch.id}.json"
                ]
            async_to_sync(run_evaluation_run)(self.team.id, snapshot.evaluation_id, self.launch.id)
        judge.assert_awaited_once()
        report = finish_trial_evaluation(self.team.id, snapshot.evaluation_id)
        assert report.runs[0].status == "judge_error"
        assert "Private synthetic" not in report.model_dump_json()
        if failure_kind != "returned":
            assert ("credential_revocation" if failure_kind == "revocation" else "judge_execution") in (
                report.runs[0].error or ""
            )

    def test_worker_rechecks_operator_access_before_judging(self) -> None:
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        self.user.is_staff = False
        self.user.save(update_fields=["is_staff"])
        judge = AsyncMock()
        with patch(f"{JUDGE_MODULE}.judge_trial_run", judge):
            async_to_sync(run_evaluation_run)(self.team.id, snapshot.evaluation_id, self.launch.id)
        judge.assert_not_called()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        assert finish_trial_evaluation(self.team.id, snapshot.evaluation_id).runs[0].status == "judge_error"

    @parameterized.expand(["before_start", "during_judging"])
    def test_flag_disable_preserves_unstarted_attempts_and_active_results(self, timing: str) -> None:
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        saved = dict(self.documents)
        judgment = TrialRunJudgment(
            launch_id=self.launch.id,
            variant_id=self.request.baseline_variant_id,
            status="judged",
            summary="Synthetic judgment completed.",
            criteria=[
                TrialCriterionVerdict(
                    criterion_id=criterion.id,
                    verdict="unknown",
                    reason="Synthetic evidence is insufficient.",
                    confidence="low",
                    evidence=[],
                )
                for criterion in snapshot.criteria
            ],
        )

        async def judge(*args: object) -> TrialRunJudgment:
            self.trials_flag.return_value = False
            return judgment

        with patch(f"{JUDGE_MODULE}.judge_trial_run", side_effect=judge) as paid_judge:
            if timing == "before_start":
                self.trials_flag.return_value = False
                with self.assertRaises(ScoutTrialsDisabled):
                    async_to_sync(run_evaluation_run)(self.team.id, snapshot.evaluation_id, self.launch.id)
                assert self.documents == saved
                paid_judge.assert_not_called()
                self.trials_flag.return_value = True
            async_to_sync(run_evaluation_run)(self.team.id, snapshot.evaluation_id, self.launch.id)
            async_to_sync(run_evaluation_run)(self.team.id, snapshot.evaluation_id, self.launch.id)
        paid_judge.assert_called_once()
        assert self.trials_flag.return_value is False
        report = finish_trial_evaluation(self.team.id, snapshot.evaluation_id)
        assert report.runs[0].status == "judged"
        assert read_trial_evaluation_report(snapshot) == report

    @parameterized.expand([(False, None), (True, None), (False, "failed"), (False, "cancelled"), (False, "skipped")])
    def test_automatic_comparison_waits_for_task_teardown_and_keeps_its_launch_rubric(
        self, manual_first: bool, excluded_status: Literal["failed", "cancelled", "skipped"] | None
    ) -> None:
        rubric = SavedScoutRubricReader(team_id=self.team.id).read(config_id=self.config.id, skill_name=self.skill.name)
        launch_ids = [self.launch.id]
        if excluded_status is not None:
            unsuccessful = self.launch.model_copy(update={"id": uuid4()})
            self._save("launches", unsuccessful.id, unsuccessful)
            launch_ids.append(unsuccessful.id)
        request = TrialComparisonRequest(
            comparison_id=self.request.evaluation_id,
            baseline_variant_id=self.request.baseline_variant_id,
            variants=[
                TrialComparisonVariant(
                    id=self.request.variants[0].id,
                    label=self.request.variants[0].label,
                    launch_ids=launch_ids,
                    model=self.launch.model,
                    reasoning_effort=self.launch.reasoning_effort,
                )
            ],
        )
        plan = TrialComparisonPlan(
            comparison_id=request.comparison_id,
            team_id=self.team.id,
            config_id=self.config.id,
            user_id=self.user.id,
            context_id=self.context.id,
            skill_name=self.skill.name,
            skill_version=self.skill.version,
            variants=[
                TrialComparisonVariantResult(
                    id=request.variants[0].id,
                    label=request.variants[0].label,
                    launch_ids=launch_ids,
                    model=self.launch.model,
                    reasoning_effort=self.launch.reasoning_effort,
                    skill_body_sha256="synthetic",
                )
            ],
            created_at=timezone.now(),
            request=request,
            request_hash="synthetic-plan",
            rubric_document=rubric,
            judge_model="gpt-5.5",
            judge_prompt_version=JUDGE_PROMPT_VERSION,
        )
        self.documents[f"signals/scout-trials/{self.team.id}/comparisons/{request.comparison_id}/plan.json"] = (
            plan.model_dump_json()
        )
        self.config.rubrics = {}
        self.config.save(update_fields=["rubrics"])
        module = "products.signals.backend.scout_harness.trial_comparison"

        def run_status(*, team_id: int, launch_id: UUID) -> TrialWorkflowStatus:
            return TrialWorkflowStatus(
                status=excluded_status if launch_id != self.launch.id and excluded_status else "completed"
            )

        with (
            patch(f"{module}.get_trial_workflow_status", side_effect=run_status),
            patch(f"{MODULE}.get_trial_workflow_status", side_effect=run_status),
            patch(
                "products.signals.backend.scout_harness.run_gates._read_flag_payload",
                return_value={"guaranteed_team_ids": [self.team.id], "default_team_config": {"max_runs_per_day": 1}},
            ),
            patch(f"{module}.check_spend_gates", return_value=None),
            patch(f"{WORKFLOW_MODULE}.start_trial_evaluation", return_value="synthetic-evaluation") as dispatch,
        ):
            self.scout_run.task_run.status = "in_progress"
            self.scout_run.task_run.save(update_fields=["status"])
            assert not prepare_comparison_evaluation(self.team.id, request.comparison_id)
            dispatch.assert_not_called()
            assert read_trial_evaluation(self.team.id, request.comparison_id) is None
            self.scout_run.task_run.status = "completed"
            self.scout_run.task_run.save(update_fields=["status"])
            rejection = check_fleet_gates(self.team.id)
            assert rejection is not None and rejection.reason == "daily_run_budget"
            if manual_first:
                prepare_trial_evaluation(config=self.config, user=self.user, request=request.evaluation_request())
            assert prepare_comparison_evaluation(self.team.id, request.comparison_id)
            snapshot = read_trial_evaluation(self.team.id, request.comparison_id)
            assert snapshot is not None
            assert snapshot.rubric_document == rubric
            assert snapshot.rubric_reference_context == self.reference
            assert snapshot.judge_prompt_version == JUDGE_PROMPT_VERSION
            assert snapshot.judge_model == "gpt-5.5"
            if excluded_status is not None:
                assert snapshot.runs[1].execution_status == excluded_status
                assert snapshot.runs[1].exclusion_reason is not None
            assert (
                prepare_trial_evaluation(config=self.config, user=self.user, request=request.evaluation_request())
                == snapshot
            )
            changed = request.evaluation_request().model_copy(
                update={"variants": [self.request.variants[0].model_copy(update={"label": "Changed"})]}
            )
            with self.assertRaisesMessage(TrialEvaluationError, "different request"):
                prepare_trial_evaluation(config=self.config, user=self.user, request=changed)
            dispatch.assert_called_once()
            with patch(
                "products.signals.backend.scout_harness.run_gates._read_flag_payload",
                return_value={"guaranteed_team_ids": []},
            ):
                with self.assertRaisesMessage(TrialEvaluationError, "not enabled for this project"):
                    prepare_comparison_evaluation(self.team.id, request.comparison_id)
            service = ScoutTrialComparisons(self.config, self.user)
            service._index(plan)
            progress_key = f"signals/scout-trials/{self.team.id}/comparisons/{request.comparison_id}/progress.json"
            self.documents[progress_key] = json.dumps({"status": "failed", "error": "Synthetic wrapper failure"})
            storage_client = MagicMock()
            storage_client.list_objects_v2.side_effect = lambda **kwargs: {
                "Contents": [{"Key": key} for key in sorted(self.documents) if key.startswith(kwargs["Prefix"])]
            }
            with patch.object(
                object_storage, "object_storage_client", return_value=object_storage.ObjectStorage(storage_client)
            ):
                assert service.history(10).results[0].status == "failed"
                finish_trial_evaluation(self.team.id, snapshot.evaluation_id)
                history = service.history(10)
            assert history.results[0].status == "completed"
            assert history.results[0].error is None
            assert history.results[0].evaluation is None

    @parameterized.expand(
        ["user_id", "config_id", "context_id", "request", "rubric_document", "judge_model", "judge_prompt_version"]
    )
    def test_comparison_never_exposes_or_dispatches_a_mismatched_saved_evaluation(self, field: str) -> None:
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        variant = TrialComparisonVariant(
            id=self.request.baseline_variant_id,
            label=self.request.variants[0].label,
            launch_ids=[self.launch.id],
            model=self.launch.model,
            reasoning_effort=self.launch.reasoning_effort,
        )
        request = TrialComparisonRequest(
            comparison_id=snapshot.evaluation_id,
            baseline_variant_id=variant.id,
            variants=[variant],
        )
        plan = TrialComparisonPlan(
            comparison_id=snapshot.evaluation_id,
            team_id=self.team.id,
            config_id=self.config.id,
            user_id=self.user.id,
            context_id=self.context.id,
            skill_name=self.skill.name,
            skill_version=self.skill.version,
            variants=[
                TrialComparisonVariantResult(
                    id=variant.id,
                    label=variant.label,
                    launch_ids=variant.launch_ids,
                    model=variant.model,
                    reasoning_effort=variant.reasoning_effort,
                    skill_body_sha256="synthetic",
                )
            ],
            created_at=timezone.now(),
            request=request,
            request_hash="synthetic-plan",
            rubric_document=snapshot.rubric_document,
            judge_model=snapshot.judge_model,
            judge_prompt_version=snapshot.judge_prompt_version,
        )
        changes: dict[str, object] = {
            "user_id": self.user.id + 1,
            "config_id": uuid4(),
            "context_id": uuid4(),
            "request": snapshot.request.model_copy(update={"baseline_variant_id": uuid4()}),
            "rubric_document": {**snapshot.rubric_document, "revision": 99},
            "judge_model": "synthetic-other-model",
            "judge_prompt_version": "7",
        }
        altered = snapshot.model_copy(update={field: changes[field]})
        self.documents[f"signals/scout-trials/{self.team.id}/evaluations/{snapshot.evaluation_id}/snapshot.json"] = (
            altered.model_dump_json()
        )
        self.documents[f"signals/scout-trials/{self.team.id}/comparisons/{snapshot.evaluation_id}/plan.json"] = (
            plan.model_dump_json()
        )
        with patch(f"{WORKFLOW_MODULE}.start_trial_evaluation") as dispatch:
            with self.assertRaisesMessage(TrialEvaluationError, "does not belong"):
                ScoutTrialComparisons(self.config, self.user).result(plan)
            with self.assertRaisesMessage(TrialEvaluationError, "does not belong"):
                prepare_comparison_evaluation(self.team.id, snapshot.evaluation_id)
            with self.assertRaisesMessage(TrialEvaluationError, "does not belong"):
                comparison_evaluation_finished(self.team.id, snapshot.evaluation_id)
            dispatch.assert_not_called()


class TestScoutTrialEvaluationWorkflow(SimpleTestCase):
    @parameterized.expand([False, True])
    async def test_bounds_concurrency_and_finalizes_after_one_activity_fails(self, disabled: bool) -> None:
        inputs = TrialEvaluationInput(team_id=2, evaluation_id=str(uuid4()))
        launch_ids = [str(uuid4()) for _ in range(7)]
        reached_limit = asyncio.Event()
        release = asyncio.Event()
        active = 0
        highest_active = 0
        completed: set[str] = set()
        finalized = False

        async def execute(function: Callable[..., object], payload: object, **options: object) -> object:
            nonlocal active, highest_active, finalized
            if function is load_scout_trial_evaluation_activity:
                return launch_ids
            if function is finish_scout_trial_evaluation_activity:
                assert completed == set(launch_ids)
                finalized = True
                return None
            assert isinstance(payload, TrialEvaluationRunInput)
            policy = options["retry_policy"]
            assert isinstance(policy, RetryPolicy) and policy.maximum_attempts == 1
            timeout = options["start_to_close_timeout"]
            assert isinstance(timeout, timedelta) and timeout >= timedelta(minutes=17)
            active += 1
            highest_active = max(highest_active, active)
            if active == 3:
                reached_limit.set()
            await release.wait()
            active -= 1
            completed.add(payload.launch_id)
            if payload.launch_id == launch_ids[0]:
                error = ActivityError(
                    "Synthetic worker interruption",
                    scheduled_event_id=1,
                    started_event_id=2,
                    identity="worker",
                    activity_type="judge_scout_trial_run_activity",
                    activity_id="scoring",
                    retry_state=None,
                )
                if disabled:
                    raise error from ApplicationError("Scout trials are disabled.", type="ScoutTrialsDisabled")
                raise error
            return None

        with patch(f"{WORKFLOW_MODULE}.workflow.execute_activity", side_effect=execute):
            task = asyncio.create_task(RunScoutTrialEvaluationWorkflow().run(inputs))
            wait_for_limit = asyncio.create_task(reached_limit.wait())
            try:
                await asyncio.wait({task, wait_for_limit}, return_when=asyncio.FIRST_COMPLETED)
                if task.done():
                    await task
                assert active == 3
            finally:
                release.set()
                wait_for_limit.cancel()
                await asyncio.gather(wait_for_limit, return_exceptions=True)
            if disabled:
                with self.assertRaisesMessage(ApplicationError, "Resume when they are enabled"):
                    await task
            else:
                assert await task == inputs.evaluation_id
        assert highest_active == 3
        assert completed == set(launch_ids)
        assert finalized is not disabled

    def test_new_evaluation_allows_all_bounded_judging_waves(self) -> None:
        client = AsyncMock()
        evaluation_id = uuid4()
        with patch(f"{WORKFLOW_MODULE}.async_connect", AsyncMock(return_value=client)):
            start_trial_evaluation(2, evaluation_id)
        timeout = client.start_workflow.call_args.kwargs["execution_timeout"]
        assert timeout >= timedelta(minutes=-(-MAX_TRIAL_RUNS // 3) * 17 + 2)
        assert client.start_workflow.call_args.args[1] == TrialEvaluationInput(
            team_id=2, evaluation_id=str(evaluation_id)
        )

    async def test_activity_failure_does_not_put_evidence_in_temporal_history(self) -> None:
        with patch(f"{MODULE}.read_trial_evaluation", side_effect=ValueError("Private synthetic evidence")):
            with self.assertRaisesMessage(ApplicationError, "snapshot_load (ValueError)") as failure:
                await load_scout_trial_evaluation_activity(TrialEvaluationInput(team_id=2, evaluation_id=str(uuid4())))
        assert "Private synthetic evidence" not in str(failure.exception)
        assert failure.exception.non_retryable
