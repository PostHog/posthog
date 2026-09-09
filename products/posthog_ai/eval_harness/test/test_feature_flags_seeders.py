from __future__ import annotations

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.feature_flags.backend.flag_status import FeatureFlagStatusChecker, filter_stale_flags
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.evals.scorers import WATCHED_FLAG_FIELDS
from products.feature_flags.evals.seeders import seed_stale_full_rollout_flag, seed_stale_partial_rollout_flag
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

SEEDERS = [
    ("full_rollout", seed_stale_full_rollout_flag),
    ("partial_rollout", seed_stale_partial_rollout_flag),
]


def _context(team_id: int, user_id: int, runtime_adapter: str | None = "claude") -> CustomPromptSandboxContext:
    return CustomPromptSandboxContext(team_id=team_id, user_id=user_id, runtime_adapter=runtime_adapter)


class TestFeatureFlagEvalSeeders(BaseTest):
    @parameterized.expand(SEEDERS)
    def test_seeded_flag_is_classified_stale(self, _name, seeder) -> None:
        # Every cleanup case depends on the agent finding the flag under active="STALE".
        # If the seeded shape drifts out of the stale set, the cases pass by finding nothing.
        seeded = seeder(_context(self.team.id, self.user.id))

        stale_keys = {flag.key for flag in filter_stale_flags(FeatureFlag.objects.filter(team_id=self.team.id))}

        assert seeded["flag_key"] in stale_keys

    @parameterized.expand(SEEDERS)
    def test_seeded_flag_does_not_read_as_changed_today(self, _name, seeder) -> None:
        # updated_at is auto_now, and feature-flag-get-all returns it while withholding
        # created_at. Left at its default, the flag reads as modified seconds ago and the
        # skill's "changed recently" exclusion ends the run before the branch under test.
        seeded = seeder(_context(self.team.id, self.user.id))

        flag = FeatureFlag.objects.get(pk=seeded["flag_id"])

        assert flag.updated_at == flag.created_at

    @parameterized.expand(SEEDERS)
    def test_seed_carries_the_state_snapshot_the_unchanged_scorer_compares(self, _name, seeder) -> None:
        # FlagStateUnchanged skips silently when the seed has no "state", so a seeder
        # that drops the snapshot would turn the mutation check off across the suite.
        # The snapshot itself comes from the shared read_flag_state, so only its
        # presence and field coverage need pinning here.
        seeded = seeder(_context(self.team.id, self.user.id))

        assert set(seeded["state"]) == set(WATCHED_FLAG_FIELDS)

    @parameterized.expand(
        [
            ("full_rollout", seed_stale_full_rollout_flag, True, 100),
            ("partial_rollout", seed_stale_partial_rollout_flag, False, 40),
        ]
    )
    def test_seeded_flag_reports_the_rollout_shape_the_skill_classifies_from(
        self, _name, seeder, effectively_full: bool, max_percentage: int
    ) -> None:
        # The stale checks above pass the partial flag on last_called_at alone, so the
        # 40% rollout could silently drift to 100% and turn its case into a copy of the
        # full-rollout one. The rollout summary is what step 3 classifies from.
        seeded = seeder(_context(self.team.id, self.user.id))

        flag = FeatureFlag.objects.get(pk=seeded["flag_id"])
        summary = FeatureFlagStatusChecker().get_rollout_summary(flag)

        assert summary.effectively_full_rollout is effectively_full
        assert summary.max_rollout_percentage == max_percentage
        assert summary.has_targeting_conditions is False

    @parameterized.expand(SEEDERS)
    def test_seeder_refuses_the_codex_runtime(self, _name, seeder) -> None:
        with self.assertRaises(RuntimeError):
            seeder(_context(self.team.id, self.user.id, runtime_adapter="codex"))
