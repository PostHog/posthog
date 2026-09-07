from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.feature_flags.backend.flag_status import filter_stale_flags
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.evals.seeders import seed_stale_full_rollout_flag, seed_stale_partial_rollout_flag

if TYPE_CHECKING:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext

SEEDERS = [
    ("full_rollout", seed_stale_full_rollout_flag),
    ("partial_rollout", seed_stale_partial_rollout_flag),
]


def _context(team_id: int, user_id: int, runtime_adapter: str | None = "claude") -> CustomPromptSandboxContext:
    # The seeders read only these three fields; a namespace stands in for the real
    # sandbox context here.
    return cast(
        "CustomPromptSandboxContext",
        SimpleNamespace(team_id=team_id, user_id=user_id, runtime_adapter=runtime_adapter),
    )


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
    def test_seeder_refuses_the_codex_runtime(self, _name, seeder) -> None:
        with self.assertRaises(RuntimeError):
            seeder(_context(self.team.id, self.user.id, runtime_adapter="codex"))
