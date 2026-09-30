from __future__ import annotations

import hashlib
import tempfile
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from unittest.mock import AsyncMock, Mock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.temporal.oauth import SIGNALS_APP_ID_DEV

from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.rubrics_schema import default_criteria
from products.signals.backend.scout_harness.rubrics import ScoutRubricDocument, read_rubric_state
from products.signals.backend.scout_harness.trial_rubrics import SavedScoutRubricReader, ScoutRubricReadError
from products.signals.backend.test.test_saved_dataset import SOURCE, write_dataset_case
from products.signals.evals.agentic.rubric_session import RubricSnapshot, SessionRubric
from products.signals.evals.agentic.saved_comparison import SavedComparisonSuite
from products.signals.evals.agentic.saved_comparison_plan import SavedComparisonPlan
from products.signals.evals.agentic.saved_comparison_rubrics import (
    install_session_rubric,
    validate_session_rubric_time_shift,
)
from products.signals.evals.agentic.saved_dataset import SavedScoutDataset


@override_settings(TEST=True, DEBUG=True)
class TestSavedComparisonRubrics(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config = SignalScoutConfig(team_id=7, skill_name="signals-scout-deliveries")
        self.document = SessionRubric(
            scout_name=self.config.skill_name,
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
            criteria=default_criteria(),
            canonical_references={"instructions": "Unbounded original instructions stay in the private artifact."},
            source={"case_id": "invented-deliveries"},
            generation={
                "source_bundle": {
                    "scout_context": {
                        "skill_name": self.config.skill_name,
                        "skill_version": 4,
                        "description": "Review late deliveries.",
                        "instructions": "Inspect delivery dates and report delays under the delivery rules.",
                        "instructions_truncated": False,
                        "report_channel": "emit",
                        "report_disposition_instructions": "Report confirmed delivery delays.",
                        "reference_files": ["references/delivery.md"],
                        "reference_files_truncated": False,
                        "recent_runs": [],
                    },
                    "reference_texts": [
                        {
                            "path": "references/delivery.md",
                            "content_type": "text/markdown",
                            "content": "Confirm the delivery date before reporting a delay.",
                        }
                    ],
                    "reference_limits": {"omitted_files": 0, "truncated_files": []},
                }
            },
        )
        self.enterContext(
            patch("products.signals.evals.agentic.saved_comparison_rubrics.transaction.atomic", side_effect=nullcontext)
        )
        self.save = self.enterContext(patch.object(self.config, "save"))
        self.enterContext(
            patch("products.signals.backend.facade.rubrics.get_scout_rubric", side_effect=self._read_document)
        )

    def _read_document(self, team_id: int, config_id: str) -> ScoutRubricDocument:
        self.assertEqual(team_id, self.config.team_id)
        self.assertEqual(config_id, str(self.config.id))
        return ScoutRubricDocument(
            config_id=self.config.id,
            skill_name=self.config.skill_name,
            state=read_rubric_state(self.config),
        )

    def _snapshot(self) -> RubricSnapshot:
        content = self.document.model_dump_json(indent=2).encode()
        path = self.directory / "rubric.json"
        path.write_bytes(content)
        return RubricSnapshot(document=self.document, path=path, sha256=hashlib.sha256(content).hexdigest())

    def test_installs_exact_frozen_criteria_and_generator_reference_with_provenance(self) -> None:
        snapshot = self._snapshot()
        original = snapshot.path.read_bytes()
        install_session_rubric(self.config, snapshot)
        first = self.config.rubrics
        install_session_rubric(self.config, snapshot)

        self.assertEqual(self.config.rubrics, first)
        state = read_rubric_state(self.config)
        self.assertEqual(state.criteria, snapshot.document.criteria)
        self.assertEqual(state.revision, 1)
        self.assertIsNone(state.generation)
        self.assertIsNotNone(state.reference_generation_id)
        assert state.reference_generation_id is not None
        self.assertEqual(UUID(state.reference_generation_id).version, 5)
        reference = state.reference_context
        assert reference is not None
        self.assertEqual(reference.skill_id, f"offline-session-rubric:{snapshot.sha256}")
        self.assertEqual(reference.skill_version, 4)
        self.assertEqual(reference.instructions, "Inspect delivery dates and report delays under the delivery rules.")
        self.assertEqual(reference.reference_texts[0].content, "Confirm the delivery date before reporting a delay.")
        assert self.config.rubrics is not None
        self.assertEqual(
            self.config.rubrics["offline_session_rubric"], {"sha256": snapshot.sha256, "path": str(snapshot.path)}
        )
        self.assertEqual(snapshot.path.read_bytes(), original)
        self.assertEqual(snapshot.document.model_dump_json(indent=2).encode(), original)
        self.assertEqual(self.save.call_count, 2)
        self.assertEqual(
            SavedScoutRubricReader(team_id=self.config.team_id).read(
                config_id=self.config.id, skill_name=self.config.skill_name
            )["criteria"],
            [criterion.model_dump(mode="json") for criterion in snapshot.document.criteria],
        )

    @parameterized.expand(["instructions_truncated", "reference_files_truncated", "omitted_files", "truncated_files"])
    def test_rejects_incomplete_generator_reference_through_production_reader(self, incomplete: str) -> None:
        bundle = self.document.generation["source_bundle"]
        assert isinstance(bundle, dict)
        context = bundle["scout_context"]
        limits = bundle["reference_limits"]
        assert isinstance(context, dict) and isinstance(limits, dict)
        if incomplete in ("instructions_truncated", "reference_files_truncated"):
            context[incomplete] = True
        elif incomplete == "omitted_files":
            limits[incomplete] = 1
        else:
            limits[incomplete] = ["references/delivery.md"]
        previous = self.config.rubrics

        with self.assertRaisesMessage(ScoutRubricReadError, "reference instructions are incomplete"):
            install_session_rubric(self.config, self._snapshot())

        self.assertEqual(self.config.rubrics, previous)

    @parameterized.expand(["missing_generator_reference", "wrong_scout", "production", "debug_off"])
    def test_rejects_invalid_installation_before_writing(self, invalid: str) -> None:
        if invalid == "missing_generator_reference":
            self.document.generation.clear()
        elif invalid == "wrong_scout":
            self.config.skill_name = "signals-scout-another-job"
        with override_settings(TEST=invalid != "production", DEBUG=invalid != "debug_off"):
            with self.assertRaises((RuntimeError, ValueError)):
                install_session_rubric(self.config, self._snapshot())
        self.save.assert_not_called()

    @parameterized.expand(["criterion", "instructions", "report_policy", "reference_file"])
    def test_declared_shift_of_frozen_requirements_fails_without_changing_source(self, field: str) -> None:
        saved = write_dataset_case(
            self.directory / "case", self.config.skill_name, manifest_changes={"time_strings": ["2030-06-04"]}
        )
        text = "Inspect deliveries starting at 2030-06-04."
        bundle = self.document.generation["source_bundle"]
        assert isinstance(bundle, dict)
        context = bundle["scout_context"]
        assert isinstance(context, dict)
        if field == "criterion":
            self.document.criteria[0].pass_condition = text
        elif field == "reference_file":
            references = bundle["reference_texts"]
            assert isinstance(references, list) and isinstance(references[0], dict)
            references[0]["content"] = text
        else:
            context["report_disposition_instructions" if field == "report_policy" else field] = text
        snapshot = self._snapshot()
        original = snapshot.path.read_bytes()
        source = saved.path.read_bytes()
        target = SOURCE + timedelta(days=1)

        with self.assertRaisesRegex(ValueError, "would change frozen rubric") as raised:
            validate_session_rubric_time_shift(saved, snapshot, target)

        self.assertIn(SOURCE.isoformat(), str(raised.exception))
        self.assertIn(target.isoformat(), str(raised.exception))
        self.assertEqual(snapshot.path.read_bytes(), original)
        self.assertEqual(snapshot.document.model_dump_json(indent=2).encode(), original)
        self.assertEqual(saved.path.read_bytes(), source)
        self.save.assert_not_called()

    @parameterized.expand(
        [
            "no_shift",
            "unchanged_rendering",
            "undeclared_date",
            "provenance",
            "non_time_replacement",
            "timestamp_boundary",
            "disabled_criterion",
        ]
    )
    def test_time_guard_does_not_reinterpret_unaffected_frozen_content(self, scenario: str) -> None:
        changes: dict[str, object] = {"time_strings": ["2030-06-04"]}
        if scenario in ("undeclared_date", "non_time_replacement"):
            changes["time_strings"] = []
        if scenario == "non_time_replacement":
            changes["string_replacements"] = {"2030-06-04": "2030-06-05"}
        saved = write_dataset_case(self.directory / "case", self.config.skill_name, manifest_changes=changes)
        bundle = self.document.generation["source_bundle"]
        assert isinstance(bundle, dict)
        context = bundle["scout_context"]
        assert isinstance(context, dict)
        if scenario == "provenance":
            context["source_cutoff"] = "2030-06-04"
            self.document.source["source_cutoff"] = "2030-06-04"
            self.document.generation["requested_at"] = "2030-06-04"
        elif scenario == "disabled_criterion":
            self.document.criteria[0].enabled = False
            self.document.criteria[0].pass_condition = "Inspect deliveries starting at 2030-06-04."
        else:
            context["instructions"] = (
                "Inspect deliveries starting at 2030-06-04T12:00:00Z."
                if scenario == "timestamp_boundary"
                else "Inspect deliveries starting at 2030-06-04."
            )
        target = SOURCE + timedelta(days=1)
        if scenario == "no_shift":
            target = SOURCE
        elif scenario == "unchanged_rendering":
            target = SOURCE + timedelta(hours=1)
        snapshot = self._snapshot()
        original = snapshot.path.read_bytes()

        validate_session_rubric_time_shift(saved, snapshot, target)

        self.assertEqual(snapshot.path.read_bytes(), original)
        self.assertEqual(snapshot.document.model_dump_json(indent=2).encode(), original)
        self.save.assert_not_called()

    async def test_clock_conflict_stops_the_suite_before_workflow_execution(self) -> None:
        saved = write_dataset_case(
            self.directory / "case", self.config.skill_name, manifest_changes={"time_strings": ["2030-06-04"]}
        )
        self.document.criteria[0].pass_condition = "Inspect deliveries starting at 2030-06-04."
        suite = SavedComparisonSuite(
            Mock(spec=SavedScoutDataset, cases=(saved,)),
            Mock(spec=SavedComparisonPlan, comparisons=(SimpleNamespace(skill_name=saved.skill_name),)),
            self.directory,
            SOURCE + timedelta(days=1),
            self.directory / "session",
            self.directory / "output",
            "gpt-6-sol",
        )
        module = "products.signals.evals.agentic.saved_comparison"
        with (
            patch(f"{module}.call_command"),
            patch(f"{module}.get_signals_app", return_value=SimpleNamespace(id=SIGNALS_APP_ID_DEV)),
            patch(f"{module}.private_backend_gateway", return_value=nullcontext()),
            patch(f"{module}.SavedRubrics.prepare", AsyncMock(return_value=self._snapshot())),
            patch(f"{module}.WorkflowPrivateEval", AsyncMock()) as execute,
        ):
            with self.assertRaisesRegex(ValueError, "would change frozen rubric"):
                await suite.run(Mock(spec=EvalContext))
        execute.assert_not_called()
