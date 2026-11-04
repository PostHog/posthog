from datetime import timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team

from products.experiments.backend.models.experiment import Experiment
from products.replay_vision.backend.management.commands.copy_replay_vision_scanner import Scrubber
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.tests.helpers import create_experiment, snapshot_for
from products.signals.backend.models import SignalScratchpad

COMMAND = "products.replay_vision.backend.management.commands.copy_replay_vision_scanner"


class TestScrubber(SimpleTestCase):
    @parameterized.expand(
        [
            ("email", "wrote jane.doe+x@example.com in the form", "wrote [email] in the form"),
            ("phone", "typed +1 (555) 010-0199 as phone", "typed [phone] as phone"),
            ("term ignores case", "the ACME pricing page", "the [redacted] pricing page"),
            ("date stays", "on 2026-10-04 at 12:30", "on 2026-10-04 at 12:30"),
        ]
    )
    def test_text(self, _name: str, text: str, expected: str) -> None:
        self.assertEqual(Scrubber(["acme"]).text(text), expected)

    def test_json_keeps_variant_keys(self) -> None:
        scrubbed = Scrubber(["acme"]).json(
            {"experiment_variant": "acme-test", "model_output": {"summary": "acme", "segments": [{"text": "acme"}]}}
        )

        self.assertEqual(
            scrubbed,
            {
                "experiment_variant": "acme-test",
                "model_output": {"summary": "[redacted]", "segments": [{"text": "[redacted]"}]},
            },
        )


@time_machine.travel("2026-11-04T12:00:00Z", tick=False)
class TestCopyReplayVisionScanner(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.experiment = create_experiment(
            self.team, "redesign", self.user, launched=True, variants=["control", "test"]
        )
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="Acme redesign",
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={"prompt": "How do Acme users use the page?", "experiment_id": self.experiment.id},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        target_org = Organization.objects.create(name="Eval")
        OrganizationMembership.objects.create(
            user=self.user, organization=target_org, level=OrganizationMembership.Level.ADMIN
        )
        self.target_team = Team.objects.create(organization=target_org, name="Eval")
        self.completed = timezone.now() - timedelta(days=10)
        for session_id, hours_before, variant in [("s-new", 0, "test"), ("s-old", 3, "control")]:
            self._observation(session_id, self.completed - timedelta(hours=hours_before), variant)

    def _observation(self, session_id: str, completed_at: Any, variant: str) -> None:
        row = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=session_id,
            distinct_id=f"person-{session_id}",
            recording_subject_email="jane@example.com",
            session_geoip={"$geoip_city_name": "Springfield"},
            session_group_keys={"0": "acme-inc"},
            status=ObservationStatus.SUCCEEDED,
            scanner_snapshot=snapshot_for(self.scanner),
            scanner_result={
                "model_output": {
                    "scanner_type": "experiment",
                    "confidence": 0.9,
                    "title": "Compares plans",
                    "summary": "Jane (jane@example.com) compares Acme plans",
                },
                "experiment_variant": variant,
            },
            triggered_by=ObservationTrigger.SCHEDULE,
            completed_at=completed_at,
        )
        ReplayObservation.objects.filter(pk=row.pk).update(created_at=completed_at)

    def _copy(self, *extra: str) -> None:
        call_command(
            "copy_replay_vision_scanner",
            f"--source-scanner-id={self.scanner.id}",
            f"--target-team-id={self.target_team.id}",
            f"--user-email={self.user.email}",
            "--redact=acme",
            *extra,
        )

    @patch(f"{COMMAND}.capture_observation_event")
    def test_copy_scrubs_personal_data_and_remaps_the_experiment(self, capture: MagicMock) -> None:
        self._copy("--commit")

        copied = ReplayScanner.objects.get(team=self.target_team)
        experiment = Experiment.objects.get(team=self.target_team)
        self.assertFalse(copied.enabled)
        self.assertNotIn("acme", copied.name.lower())
        self.assertEqual(copied.scanner_config["experiment_id"], experiment.id)
        rows = list(ReplayObservation.objects.filter(scanner=copied).order_by("-completed_at"))
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row.team_id, self.target_team.id)
            self.assertIsNone(row.recording_subject_email)
            self.assertIsNone(row.session_geoip)
            self.assertIsNone(row.session_group_keys)
            self.assertTrue(row.session_id.startswith("eval-"))
            self.assertNotIn(row.distinct_id, {"person-s-new", "person-s-old"})
            self.assertEqual(row.scanner_result["model_output"]["summary"], "Jane ([email]) compares [redacted] plans")
            self.assertEqual(row.scanner_snapshot["scanner_config"]["experiment_id"], experiment.id)
        self.assertEqual([r.scanner_result["experiment_variant"] for r in rows], ["test", "control"])
        self.assertEqual(rows[0].completed_at, timezone.now() - timedelta(hours=2))
        self.assertEqual(rows[0].completed_at - rows[1].completed_at, timedelta(hours=3))
        self.assertEqual(rows[0].created_at, rows[0].completed_at)
        self.assertEqual(
            sorted(call.kwargs["timestamp"] for call in capture.call_args_list), [r.completed_at for r in rows[::-1]]
        )

    @patch(f"{COMMAND}.capture_observation_event")
    def test_preview_writes_nothing(self, capture: MagicMock) -> None:
        self._copy()

        self.assertFalse(ReplayScanner.objects.filter(team=self.target_team).exists())
        self.assertFalse(Experiment.objects.filter(team=self.target_team).exists())
        capture.assert_not_called()

    @patch(f"{COMMAND}.capture_observation_event")
    def test_reset_scout_tally_deletes_only_the_copied_scanners_entries(self, _capture: MagicMock) -> None:
        self._copy("--commit")
        copied = ReplayScanner.objects.get(team=self.target_team)
        SignalScratchpad.all_teams.create(team=self.target_team, key=f"{copied.id}:pattern:variant-tally", content="{}")
        SignalScratchpad.all_teams.create(team=self.target_team, key="other:pattern:variant-tally", content="{}")

        call_command("copy_replay_vision_scanner", f"--reset-scout-tally={copied.id}")

        self.assertEqual(
            list(SignalScratchpad.objects.for_team(self.target_team.id).values_list("key", flat=True)),
            ["other:pattern:variant-tally"],
        )
        with self.assertRaises(CommandError):
            call_command("copy_replay_vision_scanner", f"--reset-scout-tally={self.scanner.id}")
