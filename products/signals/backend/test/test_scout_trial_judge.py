from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.facade.rubrics import ScoutRubricReferenceContext
from products.signals.backend.scout_harness.trial_evaluation_types import (
    TrialEvaluationRequest,
    TrialEvaluationSnapshot,
    TrialEvaluationVariant,
)
from products.signals.backend.trial_judging import (
    JUDGE_PROMPT_VERSION,
    TrialJudgeInput,
    TrialJudgeValidationError,
    build_trial_judge_prompt,
    parse_trial_judgment,
)
from products.signals.backend.trial_judging_types import (
    TrialEvaluationCriterion,
    TrialEvidenceFile,
    TrialEvidenceSource,
    TrialRunEvidence,
)


def _reference_context(
    *,
    skill_id: str = "synthetic-skill",
    skill_name: str = "signals-scout-example",
    instructions: str = "Inspect the checkout result.",
) -> ScoutRubricReferenceContext:
    return ScoutRubricReferenceContext.model_validate(
        {
            "skill_id": skill_id,
            "skill_name": skill_name,
            "skill_version": 1,
            "description": "Inspect an invented checkout result.",
            "instructions": instructions,
            "instructions_truncated": False,
            "report_channel": "emit",
            "report_disposition_instructions": "Write a report for a confirmed checkout defect.",
            "reference_files": [],
            "reference_files_truncated": False,
            "reference_texts": [],
            "reference_limits": {"omitted_files": 0, "truncated_files": []},
        }
    )


def _criterion(identifier: str = "default-evidence") -> TrialEvaluationCriterion:
    return TrialEvaluationCriterion(
        id=identifier,
        title="Evidence",
        description="Assess support for claims.",
        pass_condition="Claims follow from inspected sources.",
        applicability="When a finding makes factual claims.",
    )


def _snapshot() -> TrialEvaluationSnapshot:
    variant_id, launch_id, evaluation_id = uuid4(), uuid4(), uuid4()
    return TrialEvaluationSnapshot(
        evaluation_id=evaluation_id,
        team_id=2,
        config_id=uuid4(),
        user_id=17,
        context_id=uuid4(),
        created_at=datetime.now(UTC),
        request=TrialEvaluationRequest(
            evaluation_id=evaluation_id,
            baseline_variant_id=variant_id,
            variants=[TrialEvaluationVariant(id=variant_id, label="Hidden variant label", launch_ids=[launch_id])],
            rubric_source="saved",
        ),
        request_hash="synthetic-request-hash",
        rubric_document={"reference_context": _reference_context().model_dump(mode="json")},
        rubric_reference_generation_id=str(uuid4()),
        criteria=[_criterion()],
        judge_model="gpt-6-astra",
        judge_prompt_version=JUDGE_PROMPT_VERSION,
        runs=[
            TrialRunEvidence(
                launch_id=launch_id,
                variant_id=variant_id,
                run_id=uuid4(),
                task_id=uuid4(),
                task_run_id=uuid4(),
                execution_status="completed",
                runtime_adapter="codex",
                model="hidden-source-model",
                reasoning_effort="high",
                skill_body_sha256="synthetic-hash",
                files=[
                    TrialEvidenceFile(
                        id="rubric-reference",
                        kind="instructions",
                        filename="rubric-reference.txt",
                        sha256="b" * 64,
                        size_bytes=1024,
                    ),
                    TrialEvidenceFile(
                        id="trace", kind="trace", filename="run-log.jsonl", sha256="a" * 64, size_bytes=3_000_000
                    ),
                ],
                sources=[TrialEvidenceSource(id="report:1", kind="report", text="The invented check failed twice.")],
            )
        ],
    )


def _verdict(
    *,
    identifier: str = "default-evidence",
    verdict: str = "pass",
    source_id: str = "report:1",
    quote: str = "failed twice",
) -> dict[str, object]:
    return {
        "criterion_id": identifier,
        "verdict": verdict,
        "reason": "The result records the observation.",
        "confidence": "high",
        "evidence": [{"source_id": source_id, "quote": quote}],
    }


def _tool_line(event: str = "tool_call_update", **values: object) -> str:
    return json.dumps(
        {"notification": {"method": "session/update", "params": {"update": {"sessionUpdate": event, **values}}}}
    )


class TestSandboxJudgePrompt(SimpleTestCase):
    def test_prompt_provides_rubric_and_file_locations_without_loading_run_content(self) -> None:
        snapshot = _snapshot()
        prompt = build_trial_judge_prompt(
            TrialJudgeInput(
                criteria=snapshot.criteria,
                rubric_reference_context=snapshot.rubric_reference_context.model_dump(mode="json"),
                judge_model=snapshot.judge_model,
                judge_prompt_version=JUDGE_PROMPT_VERSION,
            ),
            snapshot.runs[0],
        )
        self.assertIn("run-log.jsonl", prompt)
        self.assertIn("rubric-reference.txt", prompt)
        self.assertIn(snapshot.criteria[0].pass_condition, prompt)
        self.assertNotIn("Inspect the checkout result.", prompt)
        self.assertNotIn(snapshot.runs[0].sources[0].text, prompt)
        self.assertNotIn("hidden-source-model", prompt)
        self.assertNotIn("Hidden variant label", prompt)

    @parameterized.expand(
        [
            ("old_version",),
            ("missing_reference",),
            ("duplicate_criteria",),
            ("missing_files",),
            ("missing_reference_file",),
            ("reference_is_observation",),
        ]
    )
    def test_invalid_input_is_rejected_before_starting_a_judge(self, failure: str) -> None:
        snapshot = _snapshot()
        criteria = snapshot.criteria * 2 if failure == "duplicate_criteria" else snapshot.criteria
        data = TrialJudgeInput(
            criteria=criteria,
            rubric_reference_context={} if failure == "missing_reference" else {"instructions": "Check."},
            judge_model=snapshot.judge_model,
            judge_prompt_version="15" if failure == "old_version" else JUDGE_PROMPT_VERSION,
        )
        evidence = snapshot.runs[0].model_copy(update={"files": []}) if failure == "missing_files" else snapshot.runs[0]
        if failure == "missing_reference_file":
            evidence = evidence.model_copy(
                update={"files": [file for file in evidence.files if file.id != "rubric-reference"]}
            )
        elif failure == "reference_is_observation":
            evidence = evidence.model_copy(
                update={
                    "files": [
                        file.model_copy(update={"kind": "report"}) if file.id == "rubric-reference" else file
                        for file in evidence.files
                    ]
                }
            )
        with self.assertRaises(TrialJudgeValidationError):
            build_trial_judge_prompt(data, evidence)


class TestSandboxJudgeVerdicts(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing", []),
            ("duplicate", [_verdict(), _verdict()]),
            ("unknown_id", [_verdict(identifier="invented")]),
            ("invalid_verdict", [_verdict(verdict="excellent")]),
        ]
    )
    def test_missing_or_invalid_criteria_are_not_accepted(self, _name: str, criteria: list[dict]) -> None:
        with self.assertRaises(TrialJudgeValidationError):
            parse_trial_judgment(
                json.dumps({"summary": "Synthetic result.", "criteria": criteria}),
                criteria=[_criterion()],
                sources=_snapshot().runs[0].sources,
            )

    @parameterized.expand(
        [
            ("unknown_source", "report:missing", "failed twice"),
            ("wrong_quote", "report:1", "succeeded twice"),
            ("blank_quote", "report:1", " "),
            ("instructions_only", "instructions", "Check the result"),
        ]
    )
    def test_unverifiable_citations_cannot_pass(self, _name: str, source_id: str, quote: str) -> None:
        sources = [
            *_snapshot().runs[0].sources,
            TrialEvidenceSource(id="instructions", kind="instructions", text="Check the result"),
        ]
        result = parse_trial_judgment(
            json.dumps({"summary": "Synthetic result.", "criteria": [_verdict(source_id=source_id, quote=quote)]}),
            criteria=[_criterion()],
            sources=sources,
        )
        self.assertEqual(result.criteria[0].verdict, "unknown")
        self.assertEqual(result.criteria[0].confidence, "low")

    def test_result_preserves_rubric_order_and_decoded_report_quotes(self) -> None:
        source = TrialEvidenceSource(id="report:1", kind="report", text=json.dumps({"body": "Line one.\nLine two."}))
        result = parse_trial_judgment(
            json.dumps(
                {
                    "summary": "Both checked.",
                    "criteria": [
                        _verdict(identifier="second", quote="Line one.\nLine two."),
                        _verdict(quote="Line two."),
                    ],
                }
            ),
            criteria=[_criterion(), _criterion("second")],
            sources=[source],
        )
        self.assertEqual([item.criterion_id for item in result.criteria], ["default-evidence", "second"])
        self.assertTrue(all(item.verdict == "pass" for item in result.criteria))

    @parameterized.expand([('"count":7',), ('"count": 7',)])
    def test_numeric_tool_quotes_preserve_compact_and_spaced_json(self, quote: str) -> None:
        source = TrialEvidenceSource(
            id="trace", kind="trace", text=_tool_line(status="completed", rawOutput={"count": 7})
        )
        result = parse_trial_judgment(
            json.dumps({"summary": "Checked count.", "criteria": [_verdict(source_id="trace:1", quote=quote)]}),
            criteria=[_criterion()],
            sources=[source],
        )
        self.assertEqual(result.criteria[0].verdict, "pass")

    @parameterized.expand([("acp",), ("pi",)])
    def test_tool_evidence_at_end_of_large_log_is_available(self, runtime: str) -> None:
        output = {"type": "text", "text": "Affected checkouts: 7.\nFilter: last 24 hours."}
        if runtime == "acp":
            tail = _tool_line(toolCallId="query-1", status="completed", rawOutput={"content": [output]})
        else:
            tail = json.dumps(
                {
                    "type": "pi_event",
                    "event": {
                        "type": "tool_call_updated",
                        "toolCall": {"id": "query-1", "status": "completed", "rawOutput": [output]},
                    },
                }
            )
        log = (json.dumps({"type": "notification", "padding": "x" * 1200}) + "\n") * 2000 + tail
        result = parse_trial_judgment(
            json.dumps(
                {
                    "summary": "Observed the result.",
                    "criteria": [_verdict(source_id="trace:2001", quote=output["text"])],
                }
            ),
            criteria=[_criterion()],
            sources=[TrialEvidenceSource(id="trace", kind="trace", text=log)],
        )
        self.assertEqual(result.criteria[0].verdict, "pass")
        self.assertEqual(result.criteria[0].evidence[0].quote, output["text"])

    @parameterized.expand(
        [
            ("narration", _tool_line("agent_message", content={"text": "The operation succeeded"}), "trace:1"),
            ("thought", _tool_line(rawOutput=[{"type": "thinking", "text": "The operation succeeded"}]), "trace:1"),
            ("metadata", _tool_line(rawOutput={"_meta": "The operation succeeded"}), "trace:1"),
            ("wrong_line", _tool_line(rawOutput="The operation succeeded"), "trace:2"),
            ("whole_trace", _tool_line(rawOutput="The operation succeeded"), "trace"),
            ("malformed", "The operation succeeded", "trace:1"),
            ("redacted_null", _tool_line(rawOutput=[{"type": "thinking", "text": "Excluded."}]), "trace:1", "null"),
            ("redacted_object", _tool_line(rawOutput={"thinking": "Excluded."}), "trace:1", "{}"),
            (
                "redacted_adjacency",
                _tool_line(rawOutput={"before": 1, "thinking": "Excluded.", "after": 2}),
                "trace:1",
                '"before": 1, "after": 2',
            ),
            ("empty_tool", _tool_line(), "trace:1", "{}"),
        ]
    )
    def test_trace_citation_requires_the_recorded_tool_event(
        self, _name: str, log: str, source_id: str, quote: str = "The operation succeeded"
    ) -> None:
        result = parse_trial_judgment(
            json.dumps(
                {
                    "summary": "Claimed success.",
                    "criteria": [_verdict(source_id=source_id, quote=quote)],
                }
            ),
            criteria=[_criterion()],
            sources=[TrialEvidenceSource(id="trace", kind="trace", text=log)],
        )
        self.assertEqual(result.criteria[0].verdict, "unknown")
        self.assertEqual(result.criteria[0].evidence, [])

    @parameterized.expand(
        [
            (verdict, source_id)
            for verdict in ("pass", "fail", "not_applicable", "unknown")
            for source_id in (None, "rubric-reference")
        ]
    )
    def test_conclusive_verdicts_require_observed_citations(self, verdict: str, source_id: str | None) -> None:
        quote = "The operation succeeded."
        result = parse_trial_judgment(
            json.dumps(
                {
                    "summary": "No observations.",
                    "criteria": [
                        {
                            **_verdict(verdict=verdict),
                            "evidence": [{"source_id": source_id, "quote": quote}] if source_id else [],
                        }
                    ],
                }
            ),
            criteria=[_criterion()],
            sources=[
                TrialEvidenceSource(
                    id="rubric-reference", kind="instructions", text=json.dumps({"instructions": quote})
                )
            ],
        )
        self.assertEqual(result.criteria[0].verdict, "unknown")
