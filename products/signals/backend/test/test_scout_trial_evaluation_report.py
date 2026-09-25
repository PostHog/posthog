from datetime import UTC, datetime
from uuid import uuid4

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.scout_harness.trial_evaluation_report import build_trial_comparison_report
from products.signals.backend.scout_harness.trial_evaluation_types import (
    TrialCriterionVerdict,
    TrialEvaluationCriterion,
    TrialEvaluationRequest,
    TrialEvaluationSnapshot,
    TrialEvaluationVariant,
    TrialRunEvidence,
    TrialRunJudgment,
)


class TestScoutTrialEvaluationReport(SimpleTestCase):
    def setUp(self) -> None:
        self.baseline = TrialEvaluationVariant(id=uuid4(), label="Baseline", launch_ids=[uuid4(), uuid4()])
        self.candidate = TrialEvaluationVariant(id=uuid4(), label="Candidate", launch_ids=[uuid4(), uuid4()])
        request = TrialEvaluationRequest(
            evaluation_id=uuid4(),
            baseline_variant_id=self.baseline.id,
            variants=[self.baseline, self.candidate],
            rubric_source="mock",
        )
        self.snapshot = TrialEvaluationSnapshot(
            evaluation_id=request.evaluation_id,
            team_id=2,
            config_id=uuid4(),
            user_id=1,
            context_id=uuid4(),
            created_at=datetime.now(UTC),
            request=request,
            request_hash="synthetic-request-hash",
            rubric_document={"revision": 0},
            criteria=[
                TrialEvaluationCriterion(
                    id="evidence",
                    title="Evidence",
                    description="Claims follow sources",
                    pass_condition="Cite sources",
                    applicability="When making a claim",
                )
            ],
            judge_model="example-judge",
            judge_prompt_version="1",
            runs=[
                TrialRunEvidence(
                    launch_id=launch_id,
                    variant_id=variant.id,
                    run_id=uuid4(),
                    task_id=uuid4(),
                    task_run_id=uuid4(),
                    execution_status="completed",
                    model="example-model",
                    runtime_adapter="codex",
                    reasoning_effort="medium",
                    skill_body_sha256="example-hash",
                )
                for variant in request.variants
                for launch_id in variant.launch_ids
            ],
        )

    def _judgment(self, run: TrialRunEvidence, verdict: str) -> TrialRunJudgment:
        return TrialRunJudgment(
            launch_id=run.launch_id,
            variant_id=run.variant_id,
            status="judged",
            summary="Synthetic judgment",
            criteria=[
                TrialCriterionVerdict.model_validate(
                    {
                        "criterion_id": "evidence",
                        "verdict": verdict,
                        "reason": "Fixture criterion verdict",
                        "confidence": "medium",
                        "evidence": [],
                    }
                )
            ],
        )

    @parameterized.expand(
        [
            ("decisive", "fail", 0.5, 1.0, 0.0),
            ("missing_evidence", "unknown", 1.0, 0.5, None),
            ("not_applicable", "not_applicable", 1.0, 1.0, None),
        ]
    )
    def test_uncertain_or_different_applicability_does_not_become_a_baseline_win(
        self, _name: str, candidate_verdict: str, score: float, coverage: float, delta: float | None
    ) -> None:
        verdicts = ["pass", "fail", "pass", candidate_verdict]
        report = build_trial_comparison_report(
            self.snapshot,
            [self._judgment(run, verdict) for run, verdict in zip(self.snapshot.runs, verdicts, strict=True)],
        )
        assert report.variants[0].score == 0.5
        assert report.variants[1].score == score
        assert report.variants[1].coverage == coverage
        assert report.variants[1].baseline_delta == delta
        assert report.variants[1].criteria[0].baseline_delta == delta
        assert report.runs[-1].score == (0.0 if candidate_verdict == "fail" else None)

    @parameterized.expand([("excluded",), ("judge_error",)])
    def test_execution_and_judge_failures_stay_separate_from_quality(self, status: str) -> None:
        judgments = [self._judgment(run, "pass") for run in self.snapshot.runs]
        judgments[-1] = TrialRunJudgment.model_validate(
            {
                "launch_id": self.snapshot.runs[-1].launch_id,
                "variant_id": self.candidate.id,
                "status": status,
                "summary": "The run could not be judged",
                "error": "Synthetic infrastructure failure",
            }
        )
        report = build_trial_comparison_report(self.snapshot, judgments)
        candidate = report.variants[1]
        assert candidate.score == 1.0
        assert candidate.judged_runs == 1
        assert candidate.total_runs == 2
        assert candidate.baseline_delta is None
        assert candidate.criteria[0].failed == 0
        assert candidate.excluded_runs == (1 if status == "excluded" else 0)
        assert candidate.judge_errors == (1 if status == "judge_error" else 0)
        assert report.runs[-1].score is None

    @parameterized.expand([("unknown", 0.0), ("not_applicable", None)])
    def test_no_decisive_verdicts_produce_no_score(self, verdict: str, coverage: float | None) -> None:
        report = build_trial_comparison_report(
            self.snapshot, [self._judgment(run, verdict) for run in self.snapshot.runs]
        )
        assert all(variant.score is None and variant.coverage == coverage for variant in report.variants)
        assert all(variant.baseline_delta is None for variant in report.variants)

    def test_duplicate_or_missing_run_cannot_silently_improve_the_report(self) -> None:
        judgments = [self._judgment(run, "pass") for run in self.snapshot.runs]
        for incomplete in [judgments[:-1], [judgments[0], *judgments[:-1]]]:
            with self.assertRaisesRegex(ValueError, "exactly one outcome"):
                build_trial_comparison_report(self.snapshot, incomplete)

    def test_complete_repeats_show_descriptive_improvement_and_saved_provenance(self) -> None:
        judgments = [
            self._judgment(run, "fail" if run.variant_id == self.baseline.id else "pass") for run in self.snapshot.runs
        ]
        report = build_trial_comparison_report(self.snapshot, judgments)
        assert report.variants[1].baseline_delta == 1.0
        assert report.variants[1].criteria[0].baseline_delta == 1.0
        assert "+100 percentage points" in report.summary
        assert report.rubric_source == "mock"
        assert report.rubric_revision == 0
        assert report.evidence == self.snapshot.runs
        assert report.criteria == self.snapshot.criteria

    def test_repeats_have_equal_weight_when_applicable_criteria_differ(self) -> None:
        snapshot = self.snapshot.model_copy(
            update={
                "criteria": [*self.snapshot.criteria, self.snapshot.criteria[0].model_copy(update={"id": "clarity"})]
            }
        )
        judgments = [self._judgment(run, "pass") for run in snapshot.runs]
        judgments = [
            judgment.model_copy(
                update={
                    "criteria": [
                        *judgment.criteria,
                        judgment.criteria[0].model_copy(
                            update={"criterion_id": "clarity", "verdict": "fail" if index == 0 else "not_applicable"}
                        ),
                    ]
                }
            )
            for index, judgment in enumerate(judgments)
        ]
        report = build_trial_comparison_report(snapshot, judgments)
        assert report.runs[0].score == 0.5
        assert report.runs[1].score == 1.0
        assert report.variants[0].score == 0.75
        assert report.variants[1].baseline_delta is None
