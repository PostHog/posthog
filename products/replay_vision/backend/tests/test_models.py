from posthog.test.base import BaseTest

from django.db import IntegrityError
from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.models import ReplayObservation, ReplayScanner
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ObservationTrigger
from products.replay_vision.backend.models.replay_scanner import ScannerModel, ScannerProvider, ScannerType
from products.replay_vision.backend.tests.helpers import snapshot_for as _snapshot_for


def _make_scanner(team, **overrides) -> ReplayScanner:
    defaults = {
        "team": team,
        "name": "my-scanner",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "test"},
        "model": ScannerModel.GEMINI_3_FLASH,
    }
    defaults.update(overrides)
    return ReplayScanner.objects.create(**defaults)


class TestReplayScanner(BaseTest):
    def _create_scanner(self, **overrides) -> ReplayScanner:
        return _make_scanner(self.team, **overrides)

    def test_create_with_required_fields(self) -> None:
        scanner = self._create_scanner()
        self.assertEqual(scanner.scanner_type, ScannerType.MONITOR)
        self.assertTrue(scanner.enabled)
        self.assertEqual(scanner.provider, ScannerProvider.GOOGLE)
        self.assertEqual(scanner.sampling_rate, 1.0)
        self.assertEqual(scanner.scanner_version, 1)
        self.assertFalse(scanner.emits_signals)
        self.assertIsNotNone(scanner.last_swept_at)

    def test_unique_team_name(self) -> None:
        self._create_scanner(name="dup")
        with self.assertRaises(IntegrityError):
            self._create_scanner(name="dup")

    def test_same_name_different_teams_allowed(self) -> None:
        other_team = self.organization.teams.create(name="other")
        self._create_scanner(name="shared")
        ReplayScanner.objects.create(
            team=other_team,
            name="shared",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "test"},
            model=ScannerModel.GEMINI_3_FLASH,
        )

    def test_str_includes_name_and_type(self) -> None:
        scanner = self._create_scanner(name="checkout-friction", scanner_type=ScannerType.CLASSIFIER)
        self.assertIn("checkout-friction", str(scanner))
        self.assertIn(ScannerType.CLASSIFIER.value, str(scanner))

    @parameterized.expand(
        [
            ("below_zero", -0.1, True),
            ("above_one", 1.5, True),
            ("zero_boundary", 0.0, False),
            ("one_boundary", 1.0, False),
        ]
    )
    def test_sampling_rate_constraint(self, label: str, value: float, expect_error: bool) -> None:
        if expect_error:
            with self.assertRaises(IntegrityError):
                self._create_scanner(name=label, sampling_rate=value)
        else:
            self._create_scanner(name=label, sampling_rate=value)

    def test_scanner_version_starts_at_one(self) -> None:
        scanner = self._create_scanner()
        self.assertEqual(scanner.scanner_version, 1)

    @parameterized.expand(
        [
            ("scanner_type", ScannerType.CLASSIFIER),
            ("scanner_config", {"prompt": "different prompt"}),
            ("query", {"properties": [{"key": "foo"}]}),
            ("sampling_rate", 0.25),
            ("model", ScannerModel.GEMINI_3_FLASH_LITE),
            ("emits_signals", True),
        ]
    )
    def test_scanner_version_bumps_on_tracked_field_change(self, field: str, new_value) -> None:
        scanner = self._create_scanner()
        setattr(scanner, field, new_value)
        scanner.save()
        self.assertEqual(scanner.scanner_version, 2)

    def test_scanner_version_does_not_bump_on_metadata_change(self) -> None:
        scanner = self._create_scanner(name="original")
        scanner.name = "renamed"
        scanner.description = "now described"
        scanner.save()
        self.assertEqual(scanner.scanner_version, 1)

    def test_scanner_version_does_not_bump_on_no_change(self) -> None:
        scanner = self._create_scanner()
        scanner.save()
        self.assertEqual(scanner.scanner_version, 1)

    def test_scanner_version_bumps_per_save_of_changed_config(self) -> None:
        scanner = self._create_scanner()
        scanner.sampling_rate = 0.5
        scanner.save()
        scanner.sampling_rate = 0.25
        scanner.save()
        self.assertEqual(scanner.scanner_version, 3)

    def test_scanner_version_does_not_bump_with_non_tracked_update_fields(self) -> None:
        scanner = self._create_scanner()
        scanner.scanner_config = {"prompt": "in-memory only"}  # tracked change in memory
        scanner.enabled = False
        scanner.save(update_fields=["enabled"])  # save only enabled — tracked change shouldn't bump
        scanner.refresh_from_db()
        self.assertEqual(scanner.scanner_version, 1)
        self.assertFalse(scanner.enabled)

    def test_scanner_version_bumps_with_tracked_update_field_persists(self) -> None:
        scanner = self._create_scanner()
        scanner.scanner_config = {"prompt": "persisted"}
        scanner.save(update_fields=["scanner_config"])
        scanner.refresh_from_db()
        self.assertEqual(scanner.scanner_version, 2)
        self.assertEqual(scanner.scanner_config, {"prompt": "persisted"})

    @parameterized.expand([("full_save", None), ("update_fields_save", ["enabled"])])
    def test_reenabling_resets_sweep_watermark(self, _label: str, update_fields: list[str] | None) -> None:
        # Without the reset, a re-enabled scanner backfills every session since it was disabled.
        stale = timezone.now() - timezone.timedelta(days=21)
        scanner = self._create_scanner(enabled=False, last_swept_at=stale, last_seen_session_id="sess-tie")
        scanner.enabled = True
        scanner.save(update_fields=update_fields)
        scanner.refresh_from_db()
        self.assertGreater(scanner.last_swept_at, timezone.now() - timezone.timedelta(hours=1))
        self.assertEqual(scanner.last_seen_session_id, "")

    @parameterized.expand(
        [
            ("disable", True, False),
            ("stays_enabled", True, True),
            ("stays_disabled", False, False),
        ]
    )
    def test_watermark_is_kept_unless_reenabled(self, label: str, enabled_before: bool, enabled_after: bool) -> None:
        stale = timezone.now() - timezone.timedelta(days=21)
        scanner = self._create_scanner(
            name=label, enabled=enabled_before, last_swept_at=stale, last_seen_session_id="sess-tie"
        )
        scanner.enabled = enabled_after
        scanner.description = "touched"
        scanner.save()
        scanner.refresh_from_db()
        self.assertEqual(scanner.last_swept_at, stale)
        self.assertEqual(scanner.last_seen_session_id, "sess-tie")


class TestReplayObservation(BaseTest):
    def _create_scanner(self, **overrides) -> ReplayScanner:
        return _make_scanner(self.team, **overrides)

    def _create_observation(self, scanner: ReplayScanner, session_id: str = "abc-123") -> ReplayObservation:
        # team is auto-populated from scanner by save() override.
        return ReplayObservation.objects.create(
            scanner=scanner,
            session_id=session_id,
            scanner_snapshot=_snapshot_for(scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
        )

    def test_create_with_required_fields(self) -> None:
        scanner = self._create_scanner()
        obs = self._create_observation(scanner)
        self.assertEqual(obs.status, ObservationStatus.PENDING)
        self.assertEqual(obs.error_reason, "")
        self.assertEqual(obs.workflow_id, "")
        self.assertIsNone(obs.started_at)
        self.assertIsNone(obs.completed_at)

    def test_unique_scanner_session(self) -> None:
        scanner = self._create_scanner()
        self._create_observation(scanner, session_id="s1")
        with self.assertRaises(IntegrityError):
            self._create_observation(scanner, session_id="s1")

    def test_same_session_different_scanners_allowed(self) -> None:
        scanner_a = self._create_scanner()
        scanner_b = ReplayScanner.objects.create(
            team=self.team,
            name="other-scanner",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "test"},
            model=ScannerModel.GEMINI_3_FLASH,
        )
        self._create_observation(scanner_a, session_id="shared-session")
        self._create_observation(scanner_b, session_id="shared-session")

    def test_observation_cascade_deletes_with_scanner(self) -> None:
        scanner = self._create_scanner()
        self._create_observation(scanner)
        scanner_id = scanner.id
        scanner.delete()
        self.assertEqual(ReplayObservation.objects.filter(scanner_id=scanner_id).count(), 0)

    def test_team_id_auto_populated_from_scanner(self) -> None:
        scanner = self._create_scanner()
        obs = ReplayObservation.objects.create(
            scanner=scanner,
            session_id="auto-team",
            scanner_snapshot=_snapshot_for(scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        self.assertEqual(obs.team_id, scanner.team_id)

    def test_mismatched_team_rejected(self) -> None:
        scanner = self._create_scanner()
        other_team = self.organization.teams.create(name="other")
        with self.assertRaises(ValueError):
            ReplayObservation.objects.create(
                scanner=scanner,
                team=other_team,
                session_id="mismatch",
                scanner_snapshot=_snapshot_for(scanner),
                triggered_by=ObservationTrigger.SCHEDULE,
            )

    @parameterized.expand(
        [
            ("pending_with_completed_at", ObservationStatus.PENDING, True, True),
            ("succeeded_without_completed_at", ObservationStatus.SUCCEEDED, False, True),
            ("succeeded_with_completed_at", ObservationStatus.SUCCEEDED, True, False),
        ]
    )
    def test_completed_at_status_invariant(
        self, label: str, status: str, has_completed_at: bool, expect_error: bool
    ) -> None:
        scanner = self._create_scanner()
        kwargs: dict = {
            "scanner": scanner,
            "session_id": label,
            "scanner_snapshot": _snapshot_for(scanner),
            "triggered_by": ObservationTrigger.SCHEDULE,
            "status": status,
        }
        if has_completed_at:
            kwargs["completed_at"] = timezone.now()
        if expect_error:
            with self.assertRaises(IntegrityError):
                ReplayObservation.objects.create(**kwargs)
        else:
            ReplayObservation.objects.create(**kwargs)

    def test_team_delete_cascades_to_scanner_and_observations(self) -> None:
        other_team = self.organization.teams.create(name="cascade-target")
        scanner = ReplayScanner.objects.create(
            team=other_team,
            name="doomed",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "test"},
            model=ScannerModel.GEMINI_3_FLASH,
        )
        self._create_observation(scanner, session_id="doomed-session")
        scanner_id = scanner.id
        other_team.delete()
        self.assertFalse(ReplayScanner.objects.filter(id=scanner_id).exists())
        self.assertEqual(ReplayObservation.objects.filter(scanner_id=scanner_id).count(), 0)

    def test_user_delete_nulls_triggered_by_user(self) -> None:
        from django.contrib.auth import get_user_model

        ephemeral = get_user_model().objects.create_user(email="ephemeral@example.com", password="x", first_name="Eph")
        scanner = self._create_scanner()
        obs = ReplayObservation.objects.create(
            scanner=scanner,
            session_id="user-cascade",
            scanner_snapshot=_snapshot_for(scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            triggered_by_user=ephemeral,
        )
        self.assertEqual(obs.triggered_by_user_id, ephemeral.id)
        ephemeral.delete()
        obs.refresh_from_db()
        self.assertIsNone(obs.triggered_by_user_id)

    def test_scanner_snapshot_immutable_to_scanner_edits(self) -> None:
        scanner = self._create_scanner(scanner_config={"prompt": "original"})
        obs = self._create_observation(scanner, session_id="snap-test")
        self.assertEqual(obs.scanner_snapshot["scanner_config"], {"prompt": "original"})
        scanner.scanner_config = {"prompt": "edited"}
        scanner.save()
        obs.refresh_from_db()
        self.assertEqual(obs.scanner_snapshot["scanner_config"], {"prompt": "original"})
