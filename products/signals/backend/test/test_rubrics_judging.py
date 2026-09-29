import sys
import json
import subprocess
from collections import Counter
from pathlib import Path
from uuid import UUID

from unittest import TestCase

from parameterized import parameterized

from products.signals.backend.rubrics_judging import (
    TrialCriterionAggregate,
    TrialCriterionVerdict,
    TrialEvaluationCriterion,
    TrialEvidenceSource,
    TrialJudgeValidationError,
    TrialVariantAggregate,
    build_rubric_judge_messages,
    coverage,
    overall_comparable,
    parse_trial_judgment,
    pass_rate,
)

CRITERION = TrialEvaluationCriterion(
    id="quality",
    title="Check the invented result",
    description="Review the saved result.",
    pass_condition="The report matches the saved result.",
    applicability="When a result is reported.",
)
SOURCES = [
    TrialEvidenceSource(id="report:one", kind="report", text="Three invented tasks completed."),
    TrialEvidenceSource(id="instructions:one", kind="instructions", text="Report every finding."),
    TrialEvidenceSource(id="context:one", kind="context", text="Two prior reports existed."),
]
SYNTHETIC_RESPONSE = """{
    "summary": "The saved result supports the invented report.",
    "criteria": [{
        "criterion_id": "quality",
        "verdict": "pass",
        "reason": "The report matches the saved result.",
        "confidence": "high",
        "evidence": [{"source_id": "report:one", "quote": "Three invented tasks completed."}]
    }]
}"""


def verdicts(statuses: list[str]) -> list[TrialCriterionVerdict]:
    recorded = json.loads(SYNTHETIC_RESPONSE)["criteria"][0]
    return [TrialCriterionVerdict.model_validate({**recorded, "verdict": status}) for status in statuses]


def variant(statuses: list[str], *, total_runs: int = 2) -> TrialVariantAggregate:
    rows = verdicts(statuses)
    counts = Counter(statuses)
    return TrialVariantAggregate(
        variant_id=UUID(int=1),
        label="Invented variant",
        is_baseline=False,
        total_runs=total_runs,
        judged_runs=len(rows),
        excluded_runs=total_runs - len(rows),
        judge_errors=0,
        score=pass_rate(rows),
        coverage=coverage(rows),
        criteria=[
            TrialCriterionAggregate(
                criterion_id="quality",
                passed=counts["pass"],
                failed=counts["fail"],
                unknown=counts["unknown"],
                not_applicable=counts["not_applicable"],
                pass_rate=pass_rate(rows),
                coverage=coverage(rows),
            )
        ],
    )


class TestRubricsJudging(TestCase):
    def test_import_does_not_load_django_or_provider_sdk(self) -> None:
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import products.signals.backend.rubrics_judging; "
                "assert 'django' not in sys.modules; assert 'openai' not in sys.modules",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[4],
        )

    @parameterized.expand([(str(version),) for version in range(1, 8)])
    def test_saved_prompt_versions_keep_reference_and_normalization_rules(self, version: str) -> None:
        references = {"body": "Keep the frozen reporting condition."}
        messages = build_rubric_judge_messages(
            criteria=[CRITERION],
            sources=SOURCES,
            reference_context=references,
            limitations=["Only the invented captured result is available."],
            judge_prompt_version=version,
        )
        envelope = json.loads(messages[1]["content"])
        if version in {"5", "6", "7"}:
            self.assertEqual(envelope["rubric_reference_context"], references)
            self.assertIn("cannot remove, relax or replace", messages[0]["content"])
            with self.assertRaisesRegex(TrialJudgeValidationError, "no reference instructions"):
                build_rubric_judge_messages(
                    criteria=[CRITERION],
                    sources=SOURCES,
                    reference_context=None,
                    limitations=[],
                    judge_prompt_version=version,
                )
        else:
            self.assertNotIn("rubric_reference_context", envelope)
        self.assertEqual(envelope["sources"][1]["text"], "Report every finding.")

        response = json.loads(SYNTHETIC_RESPONSE)
        response["criteria"][0]["evidence"][0]["source_id"] = "missing:one"
        checked = parse_trial_judgment(
            json.dumps(response), criteria=[CRITERION], sources=SOURCES, judge_prompt_version=version
        )
        reason = checked.criteria[0].reason
        self.assertTrue(
            reason.startswith(
                "A cited source ID is absent"
                if version in {"6", "7"}
                else "The cited sources do not establish this criterion."
            )
        )
        self.assertEqual(checked.criteria[0].verdict, "unknown")

    @parameterized.expand(
        [
            ("valid", "pass", [("report:one", "Three invented tasks completed.")], "pass", 1),
            ("missing_source", "pass", [("missing:one", "Three invented tasks completed.")], "unknown", 0),
            ("nonliteral", "fail", [("report:one", "Four invented tasks completed.")], "unknown", 0),
            (
                "mixed",
                "pass",
                [("report:one", "Three invented tasks completed."), ("missing:one", "Invented missing quotation")],
                "unknown",
                1,
            ),
            ("instructions_only", "pass", [("instructions:one", "Report every finding.")], "unknown", 1),
            (
                "instructions_only_not_applicable",
                "not_applicable",
                [("instructions:one", "Report every finding.")],
                "unknown",
                1,
            ),
            ("starting_context", "pass", [("context:one", "Two prior reports existed.")], "pass", 1),
            ("missing_evidence", "pass", [], "unknown", 0),
            ("unknown_without_evidence", "unknown", [], "unknown", 0),
            ("blank_quote", "pass", [("report:one", "   ")], "unknown", 0),
        ]
    )
    def test_normalizes_only_unsupported_verdicts(
        self,
        _name: str,
        verdict: str,
        citations: list[tuple[str, str]],
        expected_verdict: str,
        retained_citations: int,
    ) -> None:
        response = json.loads(SYNTHETIC_RESPONSE)
        response["criteria"][0].update(
            verdict=verdict, evidence=[{"source_id": source_id, "quote": quote} for source_id, quote in citations]
        )
        checked = parse_trial_judgment(json.dumps(response), criteria=[CRITERION], sources=SOURCES)
        row = checked.criteria[0]
        self.assertEqual(row.verdict, expected_verdict)
        self.assertEqual(len(row.evidence), retained_citations)
        if expected_verdict != verdict:
            self.assertEqual(row.confidence, "low")
            self.assertTrue(checked.summary.startswith("Some verdicts are unknown"))
        else:
            self.assertEqual(row.confidence, "high")
            self.assertEqual(checked.summary, response["summary"])

    def test_returns_verdicts_in_saved_criterion_order(self) -> None:
        response = json.loads(SYNTHETIC_RESPONSE)
        row = response["criteria"][0]
        response["criteria"] = [{**row, "criterion_id": "activity"}, row]
        checked = parse_trial_judgment(
            json.dumps(response),
            criteria=[CRITERION, CRITERION.model_copy(update={"id": "activity"})],
            sources=SOURCES,
        )
        self.assertEqual([row.criterion_id for row in checked.criteria], ["quality", "activity"])

    @parameterized.expand(["missing", "duplicate", "unexpected", "extra_field", "malformed"])
    def test_rejects_invalid_verdict_documents(self, failure: str) -> None:
        response = json.loads(SYNTHETIC_RESPONSE)
        criteria = [CRITERION]
        if failure == "missing":
            criteria.append(CRITERION.model_copy(update={"id": "activity"}))
        elif failure == "duplicate":
            response["criteria"].append(response["criteria"][0])
        elif failure == "unexpected":
            response["criteria"][0]["criterion_id"] = "unexpected"
        elif failure == "extra_field":
            response["extra"] = "not in the verdict schema"
        content = "{" if failure == "malformed" else json.dumps(response)
        with self.assertRaises(TrialJudgeValidationError):
            parse_trial_judgment(content, criteria=criteria, sources=SOURCES)

    @parameterized.expand(["unsupported_version", "duplicate_criteria", "duplicate_sources"])
    def test_rejects_ambiguous_or_unsupported_inputs(self, failure: str) -> None:
        criteria = [CRITERION, CRITERION] if failure == "duplicate_criteria" else [CRITERION]
        sources = [*SOURCES, SOURCES[0]] if failure == "duplicate_sources" else SOURCES
        version = "future" if failure == "unsupported_version" else "7"
        with self.assertRaises(TrialJudgeValidationError):
            build_rubric_judge_messages(
                criteria=criteria,
                sources=sources,
                reference_context={},
                limitations=[],
                judge_prompt_version=version,
            )
        with self.assertRaises(TrialJudgeValidationError):
            parse_trial_judgment(SYNTHETIC_RESPONSE, criteria=criteria, sources=sources, judge_prompt_version=version)

    def test_explicit_input_budget_keeps_complete_source_text(self) -> None:
        text = "x" * 120_001
        source = TrialEvidenceSource(id="trace:one", kind="trace", text=text)
        with self.assertRaisesRegex(TrialJudgeValidationError, "exceed the scoring limit"):
            build_rubric_judge_messages(criteria=[CRITERION], sources=[source], reference_context={}, limitations=[])
        messages = build_rubric_judge_messages(
            criteria=[CRITERION],
            sources=[source],
            reference_context={},
            limitations=[],
            max_input_characters=200_000,
        )
        self.assertEqual(json.loads(messages[1]["content"])["sources"][0]["text"], text)

    @parameterized.expand(
        [
            (["pass", "fail", "unknown", "not_applicable"], 0.5, 2 / 3),
            (["unknown"], None, 0.0),
            (["not_applicable"], None, None),
            ([], None, None),
            (["pass", "not_applicable"], 1.0, 1.0),
        ]
    )
    def test_scores_decisive_verdicts_and_reports_coverage(
        self, statuses: list[str], expected_score: float | None, expected_coverage: float | None
    ) -> None:
        rows = verdicts(statuses)
        self.assertEqual(pass_rate(rows), expected_score)
        self.assertEqual(coverage(rows), expected_coverage)

    @parameterized.expand(
        [
            ("complete", ["pass", "fail"], ["pass", "pass"], True),
            ("unknown", ["pass", "unknown"], ["pass", "pass"], False),
            ("excluded_run", ["pass"], ["pass", "pass"], False),
            ("mixed_applicability", ["pass", "not_applicable"], ["pass", "pass"], False),
            ("both_not_applicable", ["not_applicable", "not_applicable"], ["not_applicable", "not_applicable"], True),
            ("different_applicability", ["not_applicable", "not_applicable"], ["pass", "pass"], False),
        ]
    )
    def test_withholds_comparisons_without_complete_compatible_evidence(
        self, _name: str, candidate: list[str], baseline: list[str], expected: bool
    ) -> None:
        self.assertEqual(overall_comparable(variant(candidate), variant(baseline)), expected)
