import copy
import json
import hashlib

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.rubrics_judging import TrialEvaluationCriterion, TrialEvidenceSource, parse_trial_judgment
from products.signals.evals.agentic.rubric_evidence import OfflineEvidence, build_offline_evidence


def source_at(evidence: OfflineEvidence, location: str) -> TrialEvidenceSource:
    source_id = next(source_id for source_id, locations in evidence.source_locations.items() if location in locations)
    return next(source for source in evidence.sources if source.id == source_id)


class TestSavedScoutEvidence(SimpleTestCase):
    def test_unchanged_rows_share_content_with_all_original_positions_and_stable_ids(self) -> None:
        first = {"id": "invented-one", "body": 'The queue returned "ready".\nDispatch began.', "tags": []}
        second = {"id": "invented-two", "body": "The invented delivery was delayed.", "tags": ["review"]}
        updated = {**second, "body": "The invented delivery arrived."}
        output: dict[str, object] = {
            "artifacts": {
                "before": {"reports": [first, second]},
                "after": {"reports": [first, updated]},
                "changes": {"reports": {"created": [], "updated": [], "deleted": []}},
            },
            "raw_log": "",
        }
        original = copy.deepcopy(output)

        evidence = build_offline_evidence(output)

        shared = source_at(evidence, "output:/artifacts/before/reports/0")
        self.assertEqual(shared, source_at(evidence, "output:/artifacts/after/reports/0"))
        self.assertEqual(
            evidence.source_locations[shared.id],
            ["output:/artifacts/after/reports/0", "output:/artifacts/before/reports/0"],
        )
        self.assertIn(str(first["body"]), shared.text)
        self.assertIn("output:/artifacts/before/reports/0", shared.text)
        self.assertIn("output:/artifacts/after/reports/0", shared.text)
        previous = source_at(evidence, "output:/artifacts/before/reports/1")
        current = source_at(evidence, "output:/artifacts/after/reports/1")
        self.assertNotEqual(previous.id, current.id)
        self.assertIn(str(second["body"]), previous.text)
        self.assertIn(str(updated["body"]), current.text)
        reordered = build_offline_evidence({"artifacts": {"after": {"reports": [updated, first]}}})
        self.assertEqual(shared.id, source_at(reordered, "output:/artifacts/after/reports/1").id)
        self.assertEqual(output, original)
        self.assertEqual(
            evidence.output_sha256,
            hashlib.sha256(
                json.dumps(output, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest(),
        )
        self.assertEqual(len({source.id for source in evidence.sources}), len(evidence.sources))
        self.assertTrue(all(len(source.id) <= 100 for source in evidence.sources))

    def test_candidate_inputs_are_separate_from_tool_results_and_report_suggestions(self) -> None:
        text = "Inspect the invented delivery queue before reporting."
        entries = [
            {
                "type": "notification",
                "notification": {"method": "session/new", "params": {"_meta": {"systemPrompt": {"append": text}}}},
            },
            {
                "type": "notification",
                "notification": {"method": "session/prompt", "params": {"prompt": [{"type": "text", "text": text}]}},
            },
            {
                "notification": {
                    "method": "session/update",
                    "params": {
                        "update": {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": text}}
                    },
                }
            },
            {
                "notification": {
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "tool_call_update",
                            "rawOutput": {"content": [{"type": "text", "text": text}]},
                        }
                    },
                }
            },
        ]
        output: dict[str, object] = {
            "instructions": text,
            "prompt": text,
            "run_note": text,
            "summary": text,
            "raw_log": "\n".join(json.dumps(entry) for entry in entries),
            "artifacts": {
                "requested": {"run_note": text, "agent_model": "invented-model"},
                "before": {"scout_runs": [{"metadata": {"run_note": text, "status": "completed"}}]},
                "after": {
                    "scout_runs": [{"metadata": {"run_note": text, "status": "completed"}}],
                    "reports": [{"suggested_prompts": [text]}],
                },
            },
        }

        evidence = build_offline_evidence(output)

        for location in [
            "output:/instructions",
            "output:/prompt",
            "output:/run_note",
            "output:/artifacts/requested/run_note",
            "output:/artifacts/before/scout_runs/0/metadata/run_note",
            "output:/artifacts/after/scout_runs/0/metadata/run_note",
            "transcript:/0/notification/params/_meta/systemPrompt",
            "transcript:/1/notification/params/prompt",
            "transcript:/2/notification/params/update/content",
        ]:
            with self.subTest(location=location):
                source = source_at(evidence, location)
                self.assertEqual(source.kind, "instructions")
                self.assertIn(text, source.text)
        self.assertEqual(source_at(evidence, "transcript:/3").kind, "trace")
        self.assertIn(text, source_at(evidence, "transcript:/3").text)
        self.assertEqual(source_at(evidence, "output:/artifacts/after/reports/0").kind, "report")
        summary = source_at(evidence, "output:/summary")
        self.assertEqual(summary.kind, "summary")
        self.assertNotEqual(summary.id, source_at(evidence, "output:/instructions").id)

    def test_decoded_tool_text_and_unfamiliar_events_remain_literal_and_complete(self) -> None:
        text = 'The invented worker printed "done".\nNext line: C:\\delivery\\queue\t✓\u2028continued'
        entries: list[object] = [
            {"notification": {"method": "unfamiliar/update", "params": {"output": text, "empty": {}, "items": []}}},
            [False, None, 0, {"odd/~field": "Another invented observation"}],
            "A standalone captured message",
        ]
        output: dict[str, object] = {"raw_log": "\n\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries)}

        evidence = build_offline_evidence(output)

        source = source_at(evidence, "transcript:/0")
        self.assertIn(text, source.text)
        self.assertNotIn(json.dumps(text), source.text)
        self.assertIn('"empty": {\n\n}', source.text)
        self.assertIn('"items": [\n\n]', source.text)
        unusual = source_at(evidence, "transcript:/1")
        self.assertIn("[\nfalse\nnull\n0\n", unusual.text)
        self.assertIn('"odd/~field"', unusual.text)
        self.assertIn("Another invented observation", unusual.text)
        self.assertIn("A standalone captured message", source_at(evidence, "transcript:/2").text)
        self.assertEqual(
            evidence.transcript_sha256,
            hashlib.sha256(
                json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
        self.assertFalse(any("output:/raw_log" in locations for locations in evidence.source_locations.values()))

    @parameterized.expand(
        [
            ("malformed_line", '{"saved":"first"}\nnot JSON\n{"saved":"last"}'),
            ("duplicate_keys", '{"saved":"first","saved":"last"}'),
            ("nonfinite_number", '{"saved":NaN}'),
            ("numeric_overflow", '{"saved":1e999}'),
            ("empty", ""),
            ("whitespace", " \n\t"),
            ("structured_capture", {"unexpected": "Invented structured log"}),
        ]
    )
    def test_undecodable_log_retains_every_captured_value(self, _name: str, raw_log: object) -> None:
        evidence = build_offline_evidence(
            {"raw_log": raw_log, "odd/~metadata": {"nested": ["Unfamiliar saved value", None]}}
        )

        raw = source_at(evidence, "output:/raw_log")
        self.assertEqual(raw.kind, "instructions")
        if isinstance(raw_log, str):
            self.assertIn(raw_log, raw.text)
        else:
            self.assertIn("Invented structured log", raw.text)
        self.assertIsNone(evidence.transcript_sha256)
        self.assertTrue(
            any("execution evidence cannot be separated safely" in limitation for limitation in evidence.limitations)
        )
        self.assertIn("Unfamiliar saved value", source_at(evidence, "output:/odd~1~0metadata").text)

    @parameterized.expand(
        [
            ("missing", {}),
            ("wrong_shape", {"artifacts": ["Invented capture"]}),
            ("empty_state", {"artifacts": {"before": {}, "after": {"reports": []}}}),
        ]
    )
    def test_missing_trace_and_unusual_artifact_shapes_are_explicit(
        self, _name: str, output: dict[str, object]
    ) -> None:
        evidence = build_offline_evidence(output)

        self.assertTrue(any("no raw_log field" in limitation for limitation in evidence.limitations))
        self.assertIsNone(evidence.transcript_sha256)
        if _name == "wrong_shape":
            self.assertIn("Invented capture", source_at(evidence, "output:/artifacts").text)
        elif _name == "empty_state":
            self.assertIn("{\n\n}", source_at(evidence, "output:/artifacts/before").text)
            self.assertIn("[\n\n]", source_at(evidence, "output:/artifacts/after/reports").text)

    def test_repeated_tool_text_has_one_source_and_every_original_location(self) -> None:
        text = ('The invented courier printed "delivered".\n' * 120) + "Final invented line."
        entries = [
            {"tool": "inspect", "output": {"body": text}, "status": "completed"},
            {"tool": "verify", "output": {"body": text}, "status": "completed"},
        ]
        evidence = build_offline_evidence(
            {"instructions": text, "raw_log": "\n".join(json.dumps(entry) for entry in entries)}
        )

        first = source_at(evidence, "transcript:/0/output/body")
        second = source_at(evidence, "transcript:/1/output/body")
        self.assertEqual(first, second)
        self.assertIn(text, first.text)
        instruction = source_at(evidence, "output:/instructions")
        self.assertEqual(instruction.kind, "instructions")
        self.assertEqual(first.kind, "trace")
        self.assertNotEqual(instruction.id, first.id)
        self.assertEqual(sum(text in source.text for source in evidence.sources if source.kind == "trace"), 1)
        self.assertEqual(
            evidence.source_locations[first.id], ["transcript:/0/output/body", "transcript:/1/output/body"]
        )
        self.assertIn('"inspect"', source_at(evidence, "transcript:/0/tool").text)
        self.assertIn('"verify"', source_at(evidence, "transcript:/1/tool").text)
        self.assertIn('"completed"', source_at(evidence, "transcript:/0/status").text)
        array = build_offline_evidence({"metadata": {"payload": [text, text]}})
        numeric_keys = build_offline_evidence({"metadata": {"payload": {"0": text, "1": text}}})
        self.assertNotEqual(array.sources, numeric_keys.sources)
        self.assertIn('"type":"array"', source_at(array, "output:/metadata/payload").text)
        self.assertIn('"length":2', source_at(array, "output:/metadata/payload").text)
        self.assertIn('"type":"object"', source_at(numeric_keys, "output:/metadata/payload").text)
        self.assertIn('"keys":["0","1"]', source_at(numeric_keys, "output:/metadata/payload").text)
        self.assertEqual(
            source_at(array, "output:/metadata/payload/0").id,
            source_at(numeric_keys, "output:/metadata/payload/0").id,
        )

    def test_malformed_log_cannot_turn_candidate_instruction_into_observed_compliance(self) -> None:
        instruction = "The invented courier must deliver all parcels."
        raw_log = (
            json.dumps({"notification": {"method": "session/prompt", "params": {"prompt": instruction}}}) + "\ninvalid"
        )
        evidence = build_offline_evidence({"raw_log": raw_log})
        source = source_at(evidence, "output:/raw_log")

        judgment = parse_trial_judgment(
            json.dumps(
                {
                    "summary": "An invented delivery judgment.",
                    "criteria": [
                        {
                            "criterion_id": "delivery",
                            "verdict": "pass",
                            "reason": "The candidate was instructed to deliver the parcels.",
                            "confidence": "high",
                            "evidence": [{"source_id": source.id, "quote": instruction}],
                        }
                    ],
                }
            ),
            criteria=[
                TrialEvaluationCriterion(
                    id="delivery",
                    title="Deliver parcels",
                    description="Evaluate the invented delivery.",
                    pass_condition="All parcels were delivered.",
                    applicability="Always.",
                )
            ],
            sources=evidence.sources,
        )

        self.assertIn(raw_log, source.text)
        self.assertEqual(judgment.criteria[0].verdict, "unknown")
        self.assertEqual(judgment.criteria[0].confidence, "low")
