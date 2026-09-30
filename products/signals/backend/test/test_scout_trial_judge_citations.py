from __future__ import annotations

import json
from typing import TYPE_CHECKING

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import TypeAdapter

from products.signals.backend.scout_harness.trial_evaluation_types import TrialEvidenceSource, TrialJudgeVerdicts
from products.signals.backend.scout_harness.trial_judge_citations import (
    CitationReferenceError,
    build_citation_sources,
    resolve_citation_references,
)

if TYPE_CHECKING:
    from pydantic import JsonValue


class TestScoutTrialJudgeCitations(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty", ""),
            ("blank", " \t\r\n" * 300),
            ("lines", 'Observed count: 13.\r\nThe label was "café".\n' * 40),
            ("words", "An invented result contains words and spaces. " * 40),
            ("unbroken", "é" * 1001),
        ]
    )
    def test_excerpts_preserve_every_character(self, _name: str, text: str) -> None:
        source = TrialEvidenceSource(id="trace:result", kind="trace", text=text)
        rendered = build_citation_sources([source])

        self.assertEqual(len(rendered), 1)
        item = rendered[0]
        assert isinstance(item, dict)
        self.assertEqual(item["id"], source.id)
        self.assertEqual(item["kind"], source.kind)
        self.assertNotIn("text", item)
        excerpts = TypeAdapter(list[dict[str, str]]).validate_python(item["excerpts"], strict=True)
        self.assertEqual("".join(excerpt["text"] for excerpt in excerpts), text)
        self.assertTrue(all(0 < len(excerpt["text"]) <= 500 for excerpt in excerpts))
        self.assertEqual(len({excerpt["id"] for excerpt in excerpts}), len(excerpts))
        other = TrialEvidenceSource(id="report:other", kind="report", text="An unrelated invented report.")
        self.assertEqual(build_citation_sources([other, source])[1], item)

    @parameterized.expand(
        [
            ("first_excerpt", 'Observed count: 13.\nLabel: "café".\n', "excerpt-0001"),
            ("later_excerpt", "x" * 500 + 'Observed count: 13.\nLabel: "café".\n', "excerpt-0002"),
        ]
    )
    def test_references_resolve_to_the_same_source_and_public_schema(
        self, _name: str, text: str, excerpt_id: str
    ) -> None:
        sources = [
            TrialEvidenceSource(id="trace:request", kind="trace", text="Requested the invented count."),
            TrialEvidenceSource(id="trace:result", kind="trace", text=text),
        ]
        expected_quote = 'Observed count: 13.\nLabel: "café".\n'
        criterion: dict[str, JsonValue] = {
            "criterion_id": "count",
            "verdict": "pass",
            "reason": "The result contains the count.",
            "confidence": "high",
            "evidence": [{"source_id": "trace:result", "excerpt_id": excerpt_id}],
        }
        content: dict[str, JsonValue] = {"summary": "The count was observed.", "criteria": [criterion]}

        resolved = resolve_citation_references(json.dumps(content), sources)
        verdicts = TrialJudgeVerdicts.model_validate_json(resolved)

        self.assertEqual(verdicts.criteria[0].evidence[0].source_id, "trace:result")
        self.assertEqual(verdicts.criteria[0].evidence[0].quote, expected_quote)
        self.assertEqual(
            json.loads(resolved),
            {
                **content,
                "criteria": [
                    {
                        **criterion,
                        "evidence": [{"source_id": "trace:result", "quote": expected_quote}],
                    }
                ],
            },
        )

    @parameterized.expand(
        [
            ("unknown_source", {"source_id": "trace:missing", "excerpt_id": "excerpt-0001"}),
            ("unknown_excerpt", {"source_id": "trace:result", "excerpt_id": "excerpt-9999"}),
            ("blank_source", {"source_id": " ", "excerpt_id": "excerpt-0001"}),
            ("blank_excerpt", {"source_id": "trace:result", "excerpt_id": "\t"}),
            ("numeric_excerpt", {"source_id": "trace:result", "excerpt_id": 1}),
            ("missing_excerpt", {"source_id": "trace:result"}),
            ("authored_quote", {"source_id": "trace:result", "excerpt_id": "excerpt-0001", "quote": "Observed 99."}),
            ("extra_field", {"source_id": "trace:result", "excerpt_id": "excerpt-0001", "extra": True}),
            ("trimmed_source", {"source_id": " trace:result", "excerpt_id": "excerpt-0001"}),
            ("trimmed_excerpt", {"source_id": "trace:result", "excerpt_id": "excerpt-0001 "}),
            ("not_an_object", "excerpt-0001"),
        ]
    )
    def test_rejects_invalid_references_without_repair(self, _name: str, reference: JsonValue) -> None:
        source = TrialEvidenceSource(id="trace:result", kind="trace", text="Observed 13.")
        content = json.dumps({"criteria": [{"evidence": [reference]}]})

        with self.assertRaises(CitationReferenceError):
            resolve_citation_references(content, [source])

    @parameterized.expand([("empty", ""), ("blank", " \n\t")])
    def test_empty_or_blank_sources_cannot_supply_evidence(self, _name: str, text: str) -> None:
        source = TrialEvidenceSource(id="trace:result", kind="trace", text=text)
        content = json.dumps({"criteria": [{"evidence": [{"source_id": source.id, "excerpt_id": "excerpt-0001"}]}]})

        with self.assertRaises(CitationReferenceError):
            resolve_citation_references(content, [source])

    def test_duplicate_source_ids_are_rejected_before_resolution(self) -> None:
        sources = [
            TrialEvidenceSource(id="trace:result", kind="trace", text="Observed 13."),
            TrialEvidenceSource(id="trace:result", kind="trace", text="Observed 99."),
        ]

        with self.assertRaises(CitationReferenceError):
            build_citation_sources(sources)
        with self.assertRaises(CitationReferenceError):
            resolve_citation_references('{"criteria": []}', sources)
