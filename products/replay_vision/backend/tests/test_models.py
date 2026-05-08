from posthog.test.base import BaseTest

from django.db import IntegrityError
from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.models import ReplayLens, ReplayLensObservation
from products.replay_vision.backend.models.replay_lens import LensModel, LensProvider, LensStatus, LensType
from products.replay_vision.backend.models.replay_lens_observation import ObservationStatus, ObservationTrigger


def _make_lens(team, **overrides) -> ReplayLens:
    """Shared lens factory for both test classes; pass `team=self.team` from a BaseTest."""
    defaults = {
        "team": team,
        "name": "my-lens",
        "lens_type": LensType.MONITOR,
        "lens_config": {"prompt": "test"},
        "model": LensModel.GEMINI_3_FLASH,
    }
    defaults.update(overrides)
    return ReplayLens.objects.create(**defaults)


class TestReplayLens(BaseTest):
    def _create_lens(self, **overrides) -> ReplayLens:
        return _make_lens(self.team, **overrides)

    def test_create_with_required_fields(self) -> None:
        lens = self._create_lens()
        self.assertEqual(lens.lens_type, LensType.MONITOR)
        self.assertEqual(lens.status, LensStatus.ACTIVE)
        self.assertEqual(lens.provider, LensProvider.GOOGLE)
        self.assertEqual(lens.sampling_rate, 1.0)
        self.assertEqual(lens.lens_version, 1)
        self.assertFalse(lens.is_builtin)
        self.assertFalse(lens.emits_signals)
        self.assertIsNotNone(lens.last_swept_at)

    def test_unique_team_name(self) -> None:
        self._create_lens(name="dup")
        with self.assertRaises(IntegrityError):
            self._create_lens(name="dup")

    def test_same_name_different_teams_allowed(self) -> None:
        other_team = self.organization.teams.create(name="other")
        self._create_lens(name="shared")
        ReplayLens.objects.create(
            team=other_team,
            name="shared",
            lens_type=LensType.MONITOR,
            lens_config={"prompt": "test"},
            model=LensModel.GEMINI_3_FLASH,
        )

    def test_str_includes_name_and_type(self) -> None:
        lens = self._create_lens(name="checkout-friction", lens_type=LensType.CLASSIFIER)
        self.assertIn("checkout-friction", str(lens))
        self.assertIn(LensType.CLASSIFIER.value, str(lens))

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
                self._create_lens(name=label, sampling_rate=value)
        else:
            self._create_lens(name=label, sampling_rate=value)

    def test_lens_version_starts_at_one(self) -> None:
        lens = self._create_lens()
        self.assertEqual(lens.lens_version, 1)

    @parameterized.expand(
        [
            ("lens_type", LensType.CLASSIFIER),
            ("lens_config", {"prompt": "different prompt"}),
            ("query", {"properties": [{"key": "foo"}]}),
            ("sampling_rate", 0.25),
            ("model", LensModel.GEMINI_3_FLASH_LITE),
            ("emits_signals", True),
        ]
    )
    def test_lens_version_bumps_on_tracked_field_change(self, field: str, new_value) -> None:
        lens = self._create_lens()
        # Classifier needs `tags` in lens_config; supply a valid one to satisfy any future validation.
        if field == "lens_type":
            lens.lens_config = {"prompt": "p", "tags": ["a"]}
        setattr(lens, field, new_value)
        lens.save()
        self.assertEqual(lens.lens_version, 2)

    def test_lens_version_does_not_bump_on_metadata_change(self) -> None:
        lens = self._create_lens(name="original")
        lens.name = "renamed"
        lens.description = "now described"
        lens.save()
        self.assertEqual(lens.lens_version, 1)

    def test_lens_version_does_not_bump_on_no_change(self) -> None:
        lens = self._create_lens()
        lens.save()
        self.assertEqual(lens.lens_version, 1)

    def test_lens_version_bumps_per_save_of_changed_config(self) -> None:
        lens = self._create_lens()
        lens.sampling_rate = 0.5
        lens.save()
        lens.sampling_rate = 0.25
        lens.save()
        self.assertEqual(lens.lens_version, 3)

    def test_lens_version_does_not_bump_with_non_tracked_update_fields(self) -> None:
        lens = self._create_lens()
        lens.lens_config = {"prompt": "in-memory only"}  # tracked change in memory
        lens.status = LensStatus.PAUSED
        lens.save(update_fields=["status"])  # save only status — tracked change shouldn't bump
        lens.refresh_from_db()
        self.assertEqual(lens.lens_version, 1)
        self.assertEqual(lens.status, LensStatus.PAUSED)

    def test_lens_version_bumps_with_tracked_update_field_persists(self) -> None:
        lens = self._create_lens()
        lens.lens_config = {"prompt": "persisted"}
        lens.save(update_fields=["lens_config"])
        lens.refresh_from_db()
        self.assertEqual(lens.lens_version, 2)
        self.assertEqual(lens.lens_config, {"prompt": "persisted"})


class TestReplayLensObservation(BaseTest):
    def _create_lens(self, **overrides) -> ReplayLens:
        return _make_lens(self.team, **overrides)

    def _create_observation(self, lens: ReplayLens, session_id: str = "abc-123") -> ReplayLensObservation:
        # team is auto-populated from lens by save() override.
        return ReplayLensObservation.objects.create(
            lens=lens,
            session_id=session_id,
            lens_version=lens.lens_version,
            lens_config_snapshot=lens.lens_config,
            triggered_by=ObservationTrigger.SCHEDULE,
        )

    def test_create_with_required_fields(self) -> None:
        lens = self._create_lens()
        obs = self._create_observation(lens)
        self.assertEqual(obs.status, ObservationStatus.PENDING)
        self.assertEqual(obs.error_reason, "")
        self.assertEqual(obs.workflow_id, "")
        self.assertIsNone(obs.started_at)
        self.assertIsNone(obs.completed_at)

    def test_unique_lens_session(self) -> None:
        lens = self._create_lens()
        self._create_observation(lens, session_id="s1")
        with self.assertRaises(IntegrityError):
            self._create_observation(lens, session_id="s1")

    def test_same_session_different_lenses_allowed(self) -> None:
        lens_a = self._create_lens()
        lens_b = ReplayLens.objects.create(
            team=self.team,
            name="other-lens",
            lens_type=LensType.MONITOR,
            lens_config={"prompt": "test"},
            model=LensModel.GEMINI_3_FLASH,
        )
        self._create_observation(lens_a, session_id="shared-session")
        self._create_observation(lens_b, session_id="shared-session")

    def test_observation_cascade_deletes_with_lens(self) -> None:
        lens = self._create_lens()
        self._create_observation(lens)
        lens_id = lens.id
        lens.delete()
        self.assertEqual(ReplayLensObservation.objects.filter(lens_id=lens_id).count(), 0)

    def test_team_id_auto_populated_from_lens(self) -> None:
        lens = self._create_lens()
        obs = ReplayLensObservation.objects.create(
            lens=lens,
            session_id="auto-team",
            lens_version=lens.lens_version,
            lens_config_snapshot=lens.lens_config,
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        self.assertEqual(obs.team_id, lens.team_id)

    def test_mismatched_team_rejected(self) -> None:
        lens = self._create_lens()
        other_team = self.organization.teams.create(name="other")
        with self.assertRaises(ValueError):
            ReplayLensObservation.objects.create(
                lens=lens,
                team=other_team,
                session_id="mismatch",
                lens_version=lens.lens_version,
                lens_config_snapshot=lens.lens_config,
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
        lens = self._create_lens()
        kwargs = {
            "lens": lens,
            "session_id": label,
            "lens_version": lens.lens_version,
            "lens_config_snapshot": lens.lens_config,
            "triggered_by": ObservationTrigger.SCHEDULE,
            "status": status,
        }
        if has_completed_at:
            kwargs["completed_at"] = timezone.now()
        if expect_error:
            with self.assertRaises(IntegrityError):
                ReplayLensObservation.objects.create(**kwargs)
        else:
            ReplayLensObservation.objects.create(**kwargs)

    def test_team_delete_cascades_to_lens_and_observations(self) -> None:
        other_team = self.organization.teams.create(name="cascade-target")
        lens = ReplayLens.objects.create(
            team=other_team,
            name="doomed",
            lens_type=LensType.MONITOR,
            lens_config={"prompt": "test"},
            model=LensModel.GEMINI_3_FLASH,
        )
        self._create_observation(lens, session_id="doomed-session")
        lens_id = lens.id
        other_team.delete()
        self.assertFalse(ReplayLens.objects.filter(id=lens_id).exists())
        self.assertEqual(ReplayLensObservation.objects.filter(lens_id=lens_id).count(), 0)

    def test_user_delete_nulls_triggered_by_user(self) -> None:
        from django.contrib.auth import get_user_model

        ephemeral = get_user_model().objects.create_user(email="ephemeral@example.com", password="x", first_name="Eph")
        lens = self._create_lens()
        obs = ReplayLensObservation.objects.create(
            lens=lens,
            session_id="user-cascade",
            lens_version=lens.lens_version,
            lens_config_snapshot=lens.lens_config,
            triggered_by=ObservationTrigger.ON_DEMAND,
            triggered_by_user=ephemeral,
        )
        self.assertEqual(obs.triggered_by_user_id, ephemeral.id)
        ephemeral.delete()
        obs.refresh_from_db()
        self.assertIsNone(obs.triggered_by_user_id)

    def test_lens_config_snapshot_immutable_to_lens_edits(self) -> None:
        lens = self._create_lens(lens_config={"prompt": "original"})
        obs = self._create_observation(lens, session_id="snap-test")
        self.assertEqual(obs.lens_config_snapshot, {"prompt": "original"})
        lens.lens_config = {"prompt": "edited"}
        lens.save()
        obs.refresh_from_db()
        self.assertEqual(obs.lens_config_snapshot, {"prompt": "original"})

    def test_mark_succeeded_sets_completed_at(self) -> None:
        lens = self._create_lens()
        obs = self._create_observation(lens, session_id="mark-ok")
        self.assertIsNone(obs.completed_at)
        obs.mark_succeeded()
        obs.refresh_from_db()
        self.assertEqual(obs.status, ObservationStatus.SUCCEEDED)
        self.assertIsNotNone(obs.completed_at)

    def test_mark_failed_sets_completed_at_and_error(self) -> None:
        lens = self._create_lens()
        obs = self._create_observation(lens, session_id="mark-fail")
        obs.mark_failed("provider timeout after retries")
        obs.refresh_from_db()
        self.assertEqual(obs.status, ObservationStatus.FAILED)
        self.assertIsNotNone(obs.completed_at)
        self.assertEqual(obs.error_reason, "provider timeout after retries")
