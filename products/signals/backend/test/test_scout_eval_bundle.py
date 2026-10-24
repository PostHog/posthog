from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from products.posthog_ai.eval_harness.environment.dataset import EnvironmentDataset
from products.posthog_ai.eval_harness.environment.events import EnvironmentEvents
from products.posthog_ai.eval_harness.environment.restore import PreparedEnvironment
from products.signals.backend.facade.eval_environment import freeze_scout_bundle
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.eval_environment.prompt import read_native_prompt
from products.signals.backend.scout_harness.eval_environment.schema import (
    ScoutEnvironmentCase,
    ScoutEnvironmentRecord,
    ScoutEnvironmentSkill,
    ScoutEnvironmentStartingState,
)
from products.signals.backend.scout_harness.profile_version import INVENTORY_SOURCE_VERSION
from products.skills.backend.models.skills import LLMSkill


@override_settings(DEBUG=True, CLOUD_DEPLOYMENT=None)
class TestPortableScoutBundle(BaseTest):
    def _dataset(self, root: Path) -> EnvironmentDataset:
        cutoff = datetime(2030, 6, 4, 12, 0, 0, 123456, tzinfo=UTC)
        case = ScoutEnvironmentCase(
            environment_id="example-scout-environment",
            source_cutoff=cutoff,
            checkpoint=cutoff,
            prompt_mode="native",
            config={"output_destinations": {"slack": None, "webhook": None, "inbox": True}},
            steering="Investigate failed parcel scans.",
            state=ScoutEnvironmentStartingState(
                profile=ScoutEnvironmentRecord(
                    id=UUID("00000000-0000-4000-8000-000000000020"),
                    created_at=cutoff,
                    fields={
                        "source_version": INVENTORY_SOURCE_VERSION,
                        "expires_at": (cutoff + timedelta(hours=1)).isoformat(),
                        "payload": {"inventory": {"top_events": []}},
                    },
                )
            ),
            skill=ScoutEnvironmentSkill(
                id=UUID("00000000-0000-4000-8000-000000000001"),
                name="example-parcel-scout",
                body="Inspect parcel scan events and report repeated failures.",
                version=1,
                origin="custom",
                license="Example private license",
                compatibility="PostHog event queries",
                files={"references/scans.md": "The parcel_scanned event records each scan attempt."},
            ),
        )
        path = root / "case.json"
        path.write_text(case.model_dump_json())
        return EnvironmentDataset.build(
            root / "bundle",
            environment_id=case.environment_id,
            event_paths=[],
            scout_case_path=path,
            source_cutoff=cutoff,
        )

    @parameterized.expand(["clean", "seed_changed", "skill_changed"])
    def test_restore_draft_scout_freezes_native_context_and_reuse_verifies_it(self, reuse: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = self._dataset(root)
            workspace = root / "state"
            with (
                patch.object(PreparedEnvironment, "assert_migrations_current"),
                patch.object(EnvironmentEvents, "preflight"),
                patch.object(EnvironmentEvents, "restore", return_value={}),
                patch.object(EnvironmentEvents, "validate", return_value={}),
            ):
                restored = PreparedEnvironment.restore(dataset, workspace, user_id=self.user.id)
                assert dataset.manifest.scout is not None
                case_path = dataset.manifest.scout.resolve(dataset.path.parent)
                freeze_scout_bundle(case_path, dataset.path.parent, workspace)
                context = read_native_prompt(workspace / "runtime-prompt.json")
                self.assertEqual(context.team_id, restored.team_id)
                self.assertEqual(context.skill_name, "example-parcel-scout")
                self.assertFalse(SignalScoutRun.objects.for_team(restored.team_id).exists())
                config = SignalScoutConfig.objects.for_team(restored.team_id).get(id=context.config_id)
                self.assertFalse(config.enabled)
                self.assertEqual(config.output_destinations, {"slack": None, "webhook": None, "inbox": True})
                skill = LLMSkill.objects.get(team_id=restored.team_id, name=context.skill_name)
                self.assertEqual(skill.compatibility, "PostHog event queries")
                self.assertEqual(skill.files.get().path, "references/scans.md")
                receipt = PreparedEnvironment.read_receipt(workspace)
                assert receipt is not None
                self.assertEqual(receipt.phase, "complete")
                self.assertIsNotNone(receipt.scout_seed_sha256)
                self.assertEqual(receipt.target_cutoff.microsecond, dataset.manifest.source_cutoff.microsecond)
                if reuse == "seed_changed":
                    seed_path = workspace / "scout-seed.json"
                    seed_path.write_bytes(seed_path.read_bytes() + b"\n")
                elif reuse == "skill_changed":
                    LLMSkill.objects.filter(id=skill.id).update(body="Changed instructions.")
                if reuse == "clean":
                    self.assertTrue(PreparedEnvironment.restore(dataset, workspace, user_id=self.user.id).reused)
                    freeze_scout_bundle(case_path, dataset.path.parent, workspace)
                else:
                    before = (workspace / "receipt.json").read_bytes()
                    with self.assertRaises(ValueError):
                        PreparedEnvironment.restore(dataset, workspace, user_id=self.user.id)
                    self.assertEqual((workspace / "receipt.json").read_bytes(), before)
                    self.assertEqual(SignalScoutConfig.objects.for_team(restored.team_id).count(), 1)

    def test_failed_scout_seed_leaves_failed_receipt_and_cannot_reuse_partial_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = self._dataset(root)
            workspace = root / "state"
            with (
                patch.object(PreparedEnvironment, "assert_migrations_current"),
                patch.object(EnvironmentEvents, "preflight"),
                patch.object(EnvironmentEvents, "restore", return_value={}),
                patch.object(EnvironmentEvents, "validate", return_value={}),
                patch.object(LLMSkill.objects, "create", side_effect=RuntimeError("Simulated unavailable storage")),
            ):
                with self.assertRaisesRegex(RuntimeError, "unavailable storage"):
                    PreparedEnvironment.restore(dataset, workspace, user_id=self.user.id)
                receipt = PreparedEnvironment.read_receipt(workspace)
                assert receipt is not None
                assert receipt.team_id is not None
                self.assertEqual(receipt.phase, "failed")
                self.assertFalse((workspace / "scout-seed.json").exists())
                self.assertFalse(SignalScoutConfig.objects.for_team(receipt.team_id).exists())
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    PreparedEnvironment.restore(dataset, workspace, user_id=self.user.id)
