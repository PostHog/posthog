from __future__ import annotations

import json
import hashlib
import tempfile
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.test.test_saved_dataset import SOURCE, write_dataset_case
from products.signals.evals.agentic.saved_case import SavedFile, SavedScoutCase
from products.signals.evals.agentic.saved_comparison_plan import (
    SavedComparison,
    SavedComparisonPlan,
    SavedComparisonVariant,
)
from products.signals.evals.saved_comparison import snapshot_plan


def baseline_variant(**changes: object) -> SavedComparisonVariant:
    return SavedComparisonVariant.model_validate(
        {"label": "Baseline", "model": "gpt-5.5", "reasoning_effort": "high", **changes}
    )


def instructions(path: Path, content: bytes) -> SavedFile:
    path.write_bytes(content)
    return SavedFile(path=path.name, sha256=hashlib.sha256(content).hexdigest())


class TestSavedComparisonPlan(SimpleTestCase):
    @parameterized.expand(
        ["duplicate_labels", "blank_label", "blank_model", "blank_effort", "launch_count", "same_scout"]
    )
    def test_invalid_comparisons_are_rejected(self, failure: str) -> None:
        with self.assertRaises(ValueError):
            values: dict[str, object] = {}
            if failure == "blank_label":
                values["label"] = " \n "
            elif failure == "blank_model":
                values["model"] = "   "
            elif failure == "blank_effort":
                values["reasoning_effort"] = "\t"
            elif failure == "launch_count":
                values["repeats"] = 11
            first = baseline_variant(**values)
            variants: tuple[SavedComparisonVariant, ...] = (first,)
            if failure == "duplicate_labels":
                variants += (baseline_variant(label=" Baseline "),)
            elif failure == "launch_count":
                variants += (baseline_variant(label="Alternative", repeats=10),)
            comparison = SavedComparison(skill_name="signals-scout-queue", variants=variants)
            SavedComparisonPlan(comparisons=(comparison, comparison) if failure == "same_scout" else (comparison,))

    @parameterized.expand(
        ["checksum", "utf8", "empty", "whitespace", "too_long", "missing_scout", "capacity", "long_note"]
    )
    def test_input_preflight_rejects_unusable_content_before_runtime(self, failure: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = write_dataset_case(
                root / "source",
                "signals-scout-queue",
                manifest_changes={"run_note": "x" * 900} if failure == "long_note" else None,
            )
            body = b"Inspect the invented delivery queue."
            if failure == "utf8":
                body = b"\xff"
            elif failure == "empty":
                body = b""
            elif failure == "whitespace":
                body = b" \n\t"
            elif failure == "too_long":
                body = b"x" * 100_001
            reference = instructions(root / "variant.md", body)
            if failure == "checksum":
                (root / "variant.md").write_text("Unexpected replacement.")
            comparison = SavedComparison(
                skill_name="signals-scout-missing" if failure == "missing_scout" else case.skill_name,
                variants=(baseline_variant(instructions=reference, repeats=2),),
            )
            plan = SavedComparisonPlan(comparisons=(comparison,))

            with self.assertRaises((ValueError, UnicodeError)):
                plan.validate_inputs(
                    root, (case,), 1 if failure == "capacity" else 2, target_cutoff=SOURCE + timedelta(days=3)
                )

    def test_case_mismatch_is_rejected_before_loading_online_types(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            saved = write_dataset_case(root / "source", "signals-scout-queue")
            comparison = SavedComparison(skill_name="signals-scout-another", variants=(baseline_variant(),))

            with self.assertRaisesRegex(ValueError, "does not match"):
                comparison.request(root, saved, target_cutoff=SOURCE)


class TestSavedComparisonRequest(SimpleTestCase):
    def test_snapshotted_instructions_survive_changed_and_deleted_original(self) -> None:
        body = 'Inspect the invented queue.\nKeep "waiting" and 2030-06-04 literal.\n'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            saved = write_dataset_case(root / "source", "signals-scout-queue")
            source_path = root / "candidate.md"
            reference = instructions(source_path, body.encode())
            plan = SavedComparisonPlan(
                comparisons=(
                    SavedComparison(
                        skill_name=saved.skill_name,
                        variants=(baseline_variant(instructions=reference),),
                    ),
                )
            )
            destination = root / "retained"
            destination.mkdir()
            output_path = destination / "comparison-plan.json"
            snapshot = snapshot_plan(plan, root, output_path)
            retained = SavedComparisonPlan.model_validate_json(output_path.read_text())
            self.assertEqual(retained, snapshot)
            retained_reference = retained.comparisons[0].variants[0].instructions
            assert retained_reference is not None
            self.assertNotEqual(retained_reference.path, reference.path)
            self.assertEqual(retained_reference.sha256, hashlib.sha256(body.encode()).hexdigest())

            for delete_original in (False, True):
                if delete_original:
                    source_path.unlink()
                else:
                    source_path.write_text("Different instructions now exist at the original path.")
                retained.validate_inputs(destination, (saved,), 1, target_cutoff=SOURCE)
                request = retained.comparisons[0].request(destination, saved, target_cutoff=SOURCE)
                self.assertEqual(request.variants[0].skill_body, body)
                self.assertEqual(retained_reference.resolve(destination).read_text(), body)

    def test_literal_instructions_unique_ids_baseline_and_shifted_window(self) -> None:
        identifier = UUID("11111111-2222-4333-8444-555555555555")
        body = f'Inspect the queue at 2030-06-04 and record {identifier}.\nKeep "waiting" literal.\n'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            saved = write_dataset_case(
                root / "source",
                "signals-scout-queue",
                state={
                    "checkpoint": SOURCE,
                    "complete": True,
                    "scratchpad": [{"id": identifier, "created_at": SOURCE, "key": "queue", "content": "Waiting"}],
                },
                manifest_changes={
                    "time_strings": ["2030-06-04"],
                    "string_replacements": {"queue": "delivery desk"},
                    "investigation_start": (SOURCE - timedelta(days=1)).isoformat(),
                    "run_note": "Inspect the queue.",
                },
            )
            manifest = json.loads(saved.path.read_text())
            body_reference = instructions(saved.path.parent / "skill.md", body.encode())
            manifest["skill"]["body"] = body_reference.model_dump()
            saved.path.write_text(json.dumps(manifest))
            saved = SavedScoutCase.load(saved.path)
            reference = instructions(root / "variant.md", body.encode())
            comparison = SavedComparison(
                skill_name=saved.skill_name,
                variants=(
                    baseline_variant(repeats=2),
                    baseline_variant(label="Same instructions", instructions=reference),
                ),
            )
            plan = SavedComparisonPlan(comparisons=(comparison,))
            target = SOURCE + timedelta(days=3)
            plan.validate_inputs(root, (saved,), 3, target_cutoff=target)
            requests = [comparison.request(root, saved, target_cutoff=target) for _ in range(2)]

            for request in requests:
                self.assertEqual(request.baseline_variant_id, request.variants[0].id)
                self.assertIsNone(request.variants[0].skill_body)
                self.assertEqual(request.variants[1].skill_body, body)
                self.assertEqual(saved.manifest.skill.body.resolve(saved.path.parent).read_text(), body)
                self.assertEqual([len(variant.launch_ids) for variant in request.variants], [2, 1])
                self.assertIn(SOURCE.isoformat(), request.note)
                self.assertIn(target.isoformat(), request.note)
                self.assertIn((target - timedelta(days=1)).isoformat(), request.note)
                self.assertIn("delivery desk", request.note)
                self.assertIn("exclude the end", request.note)
            all_ids = [
                identifier
                for request in requests
                for identifier in [
                    request.comparison_id,
                    *[variant.id for variant in request.variants],
                    *[launch_id for variant in request.variants for launch_id in variant.launch_ids],
                ]
            ]
            self.assertEqual(len(all_ids), len(set(all_ids)))
