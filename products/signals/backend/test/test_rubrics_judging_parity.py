from __future__ import annotations

import json
from types import SimpleNamespace

from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.scout_harness.trial_evaluation_report import build_trial_comparison_report
from products.signals.backend.scout_harness.trial_evaluation_types import TrialRunJudgment
from products.signals.backend.scout_harness.trial_judge import build_trial_judge_messages, parse_trial_judgment
from products.signals.backend.test.test_scout_trial_judge import _criterion, _snapshot
from products.signals.evals.agentic.rubric_evidence import build_offline_evidence
from products.signals.evals.agentic.rubric_judge import RubricModelResponse, judge_rubric


class TestRubricsJudgingParity(SimpleTestCase):
    @parameterized.expand(["complete", "nonliteral_quote", "instruction_only"])
    async def test_synthetic_verdicts_normalize_and_score_identically_through_both_adapters(
        self, scenario: str
    ) -> None:
        observation = 'The invented queue returned "waiting".\nNo delivery was dispatched.'
        output: dict[str, object] = {
            "summary": observation,
            "instructions": "Read the invented dispatch history before reporting.",
            "raw_log": json.dumps({"tool_result": {"text": observation}}),
            "artifacts": {"task_run": {"status": "completed"}},
        }
        evidence = build_offline_evidence(output)
        report_id = next(
            source_id for source_id, locations in evidence.source_locations.items() if "output:/summary" in locations
        )
        instruction_id = next(source.id for source in evidence.sources if source.kind == "instructions")
        statuses = ["pass", "fail", "unknown", "not_applicable"]
        snapshot = _snapshot()
        run = snapshot.runs[0].model_copy(update={"sources": evidence.sources, "limitations": evidence.limitations})
        snapshot = snapshot.model_copy(update={"criteria": [_criterion(status) for status in statuses], "runs": [run]})
        assert snapshot.rubric_reference_context is not None
        references = snapshot.rubric_reference_context.model_dump(mode="json")
        rows: list[dict[str, object]] = [
            {
                "criterion_id": status,
                "verdict": status,
                "reason": "The synthetic response describes the queue result.",
                "confidence": "high",
                "evidence": [{"source_id": report_id, "quote": observation}],
            }
            for status in statuses
        ]
        if scenario == "nonliteral_quote":
            rows[0]["evidence"] = [{"source_id": report_id, "quote": "A different queue result was reported."}]
        elif scenario == "instruction_only":
            rows[0]["evidence"] = [{"source_id": instruction_id, "quote": output["instructions"]}]
        response = json.dumps({"summary": "Synthetic verdicts.", "criteria": list(reversed(rows))})
        ask = AsyncMock(
            return_value=RubricModelResponse(requested_model="invented-model", text=response, finish_reason="stop")
        )
        with patch(
            "posthog.helpers.tiktoken_encoding.get_tiktoken_encoding_for_model",
            return_value=SimpleNamespace(encode=lambda text, **kwargs: text.split()),
        ):
            offline = await judge_rubric(
                output,
                [{**criterion.model_dump(mode="json"), "enabled": True} for criterion in snapshot.criteria],
                references,
                ask,
            )
        messages = build_trial_judge_messages(snapshot, run)
        normalized = parse_trial_judgment(
            response,
            criteria=snapshot.criteria,
            sources=run.sources,
            judge_prompt_version=snapshot.judge_prompt_version,
        )
        report = build_trial_comparison_report(
            snapshot,
            [
                TrialRunJudgment(
                    launch_id=run.launch_id,
                    variant_id=run.variant_id,
                    status="judged",
                    summary=normalized.summary,
                    criteria=normalized.criteria,
                )
            ],
        )
        self.assertEqual(offline.status, "judged")
        self.assertEqual(offline.request_messages, messages)
        self.assertEqual(offline.judge_prompt_version, report.judge_prompt_version)
        self.assertEqual(offline.criteria, normalized.criteria)
        self.assertEqual(offline.summary, normalized.summary)
        self.assertEqual((offline.score, offline.coverage), (report.runs[0].score, report.runs[0].coverage))
        self.assertEqual((offline.score, offline.coverage), (report.variants[0].score, report.variants[0].coverage))
        self.assertEqual(
            [criterion.verdict for criterion in offline.criteria],
            statuses if scenario == "complete" else ["unknown", *statuses[1:]],
        )
        self.assertEqual((offline.score, offline.coverage), (0.5, 2 / 3) if scenario == "complete" else (0.0, 1 / 3))
        ask.assert_awaited_once()
