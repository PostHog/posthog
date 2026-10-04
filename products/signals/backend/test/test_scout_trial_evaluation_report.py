from datetime import UTC, datetime
from uuid import uuid4

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.scout_harness.trial_evaluation_report import build_trial_comparison_report
from products.signals.backend.scout_harness.trial_evaluation_types import (
    TrialComparisonReport,
    TrialCriterionVerdict,
    TrialEvaluationCriterion,
    TrialEvaluationRequest,
    TrialEvaluationSnapshot,
    TrialEvaluationVariant,
    TrialRunEvidence,
    TrialRunJudgment,
)
from products.signals.backend.test.test_scout_trial_judge import _reference_context


class TestScoutTrialEvaluationReport(SimpleTestCase):
    def setUp(self) -> None:
        self.baseline = TrialEvaluationVariant(id=uuid4(), label="Baseline", launch_ids=[uuid4(), uuid4()])
        self.candidate = TrialEvaluationVariant(id=uuid4(), label="Candidate", launch_ids=[uuid4(), uuid4()])
        request = TrialEvaluationRequest(
            evaluation_id=uuid4(),
            baseline_variant_id=self.baseline.id,
            variants=[self.baseline, self.candidate],
            rubric_source="saved",
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
            rubric_document={"revision": 3},
            rubric_reference_context=_reference_context(),
            rubric_reference_generation_id=str(uuid4()),
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
            judge_prompt_version="sandbox-1",
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
        assert report.outcome is not None
        assert report.outcome.status == ("tie" if candidate_verdict == "fail" else "inconclusive")
        assert report.outcome.variant_ids == (
            [self.baseline.id, self.candidate.id] if candidate_verdict == "fail" else []
        )

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
        assert report.outcome is not None and report.outcome.status == "inconclusive"
        assert report.outcome.variant_ids == []

    @parameterized.expand([("unknown", 0.0), ("not_applicable", None)])
    def test_no_decisive_verdicts_produce_no_score(self, verdict: str, coverage: float | None) -> None:
        report = build_trial_comparison_report(
            self.snapshot, [self._judgment(run, verdict) for run in self.snapshot.runs]
        )
        assert all(variant.score is None and variant.coverage == coverage for variant in report.variants)
        assert all(variant.baseline_delta is None for variant in report.variants)
        assert report.outcome is not None and report.outcome.status == "inconclusive"

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
        assert report.outcome is not None and report.outcome.status == "winner"
        assert report.outcome.variant_ids == [self.candidate.id]
        assert "2 of 2" in report.outcome.summary
        assert report.rubric_source == "saved"
        assert report.rubric_revision == 3
        assert report.rubric_reference_context == self.snapshot.rubric_reference_context
        assert report.rubric_reference_generation_id == self.snapshot.rubric_reference_generation_id
        assert report.evidence == self.snapshot.runs
        assert report.criteria == self.snapshot.criteria
        exported = report.model_dump_json()
        assert TrialComparisonReport.model_validate_json(exported) == report
        historical = report.model_dump(mode="json", exclude={"outcome"})
        assert TrialComparisonReport.model_validate(historical).outcome is None

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
        assert report.outcome is not None and report.outcome.status == "inconclusive"

    def test_fewer_repeats_cannot_win_by_avoiding_a_failed_run(self) -> None:
        snapshot = self.snapshot.model_copy(
            update={
                "runs": self.snapshot.runs[:-1],
                "request": self.snapshot.request.model_copy(
                    update={
                        "variants": [
                            self.baseline,
                            self.candidate.model_copy(update={"launch_ids": self.candidate.launch_ids[:1]}),
                        ]
                    }
                ),
            }
        )
        report = build_trial_comparison_report(
            snapshot,
            [
                self._judgment(run, verdict)
                for run, verdict in zip(snapshot.runs, ["pass", "fail", "pass"], strict=True)
            ],
        )
        assert report.variants[1].score == 1.0
        assert report.outcome is not None and report.outcome.status == "inconclusive"
        assert "different numbers of runs" in report.outcome.summary

    def test_only_top_variants_share_a_tie(self) -> None:
        third = self.candidate.model_copy(update={"id": uuid4(), "label": "Third", "launch_ids": [uuid4(), uuid4()]})
        third_runs = [
            self.snapshot.runs[2].model_copy(update={"launch_id": launch_id, "variant_id": third.id})
            for launch_id in third.launch_ids
        ]
        snapshot = self.snapshot.model_copy(
            update={
                "request": self.snapshot.request.model_copy(
                    update={"variants": [self.baseline, self.candidate, third]}
                ),
                "runs": [*self.snapshot.runs, *third_runs],
            }
        )
        report = build_trial_comparison_report(
            snapshot,
            [self._judgment(run, "fail" if run.variant_id == self.baseline.id else "pass") for run in snapshot.runs],
        )
        assert report.outcome is not None and report.outcome.status == "tie"
        assert report.outcome.variant_ids == [self.candidate.id, third.id]

    def test_equal_pass_counts_tie_when_passes_are_distributed_differently_across_repeats(self) -> None:
        variants = [
            variant.model_copy(update={"launch_ids": [uuid4() for _ in range(3)]})
            for variant in (self.baseline, self.candidate)
        ]
        criteria = [self.snapshot.criteria[0].model_copy(update={"id": f"check-{index}"}) for index in range(5)]
        runs = [
            self.snapshot.runs[0].model_copy(update={"launch_id": launch_id, "variant_id": variant.id})
            for variant in variants
            for launch_id in variant.launch_ids
        ]
        snapshot = self.snapshot.model_copy(
            update={
                "request": self.snapshot.request.model_copy(update={"variants": variants}),
                "runs": runs,
                "criteria": criteria,
            }
        )
        judgments = []
        for run, passes in zip(runs, [0, 0, 3, 1, 1, 1], strict=True):
            judgment = self._judgment(run, "pass")
            judgments.append(
                judgment.model_copy(
                    update={
                        "criteria": [
                            judgment.criteria[0].model_copy(
                                update={"criterion_id": criterion.id, "verdict": "pass" if index < passes else "fail"}
                            )
                            for index, criterion in enumerate(criteria)
                        ]
                    }
                )
            )
        report = build_trial_comparison_report(snapshot, judgments)
        assert report.outcome is not None and report.outcome.status == "tie"
        assert report.outcome.variant_ids == [self.baseline.id, self.candidate.id]
        assert "3 of 15" in report.outcome.summary
