from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import patch

from django.db import close_old_connections

from parameterized import parameterized

from posthog.models.user import User

from products.conversations.backend.models.ticket import Ticket
from products.feature_flags.backend.flag_status import FeatureFlagStatusChecker, filter_stale_flags
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.evals.scorers import WATCHED_FLAG_FIELDS, ReproducedSeededFlag
from products.feature_flags.evals.seeders import (
    CLIENT_SCOPED_FLAG_KEY,
    REQUESTER_EMAIL,
    STALE_LOOKING_RECENT_UPDATE_DAYS_AGO,
    _requester,
    seed_client_scoped_flag,
    seed_recently_updated_flag,
    seed_stale_full_rollout_flag,
    seed_stale_partial_rollout_flag,
    seed_unassessed_requester_ticket,
    seed_unattested_requester_ticket,
    seed_unconfirmed_requester_ticket,
)
from products.posthog_ai.eval_harness.test.test_eval_scorers import _raw_tool_log
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

SEEDERS = [
    ("full_rollout", seed_stale_full_rollout_flag),
    ("partial_rollout", seed_stale_partial_rollout_flag),
]

# seed_recently_updated_flag cannot join SEEDERS, because it breaks the
# updated_at == created_at test on purpose. Every other check applies to it.
CLEANUP_SEEDERS = [*SEEDERS, ("recently_updated", seed_recently_updated_flag)]


def _context(team_id: int, user_id: int, runtime_adapter: str | None = "claude") -> CustomPromptSandboxContext:
    return CustomPromptSandboxContext(team_id=team_id, user_id=user_id, runtime_adapter=runtime_adapter)


class TestFeatureFlagEvalSeeders(BaseTest):
    @parameterized.expand(CLEANUP_SEEDERS)
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

    @parameterized.expand(CLEANUP_SEEDERS)
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
            ("recently_updated", seed_recently_updated_flag, True, 100),
        ]
    )
    def test_seeded_flag_reports_the_rollout_shape_the_skill_classifies_from(
        self, _name, seeder, effectively_full: bool, max_percentage: int
    ) -> None:
        # The stale checks above pass the partial flag on last_called_at alone, so the
        # 40% rollout could silently drift to 100% and turn its case into a copy of the
        # full-rollout one. The rollout summary is what the skill's "Classify the rollout
        # state" step classifies from.
        seeded = seeder(_context(self.team.id, self.user.id))

        flag = FeatureFlag.objects.get(pk=seeded["flag_id"])
        summary = FeatureFlagStatusChecker().get_rollout_summary(flag)

        assert summary.effectively_full_rollout is effectively_full
        assert summary.max_rollout_percentage == max_percentage
        assert summary.has_targeting_conditions is False

    @parameterized.expand(CLEANUP_SEEDERS)
    def test_seeder_refuses_the_codex_runtime(self, _name, seeder) -> None:
        with self.assertRaises(RuntimeError):
            seeder(_context(self.team.id, self.user.id, runtime_adapter="codex"))


class TestSeedRecentlyUpdatedFlag(BaseTest):
    """The recent-update case only has teeth if the backend does not already exclude it.

    ``filter_stale_flags`` classifies on ``created_at`` and ``last_called_at``, never
    ``updated_at``, so a flag updated two days ago still reads STALE from the backend.
    Catching the recency exclusion is entirely the cleanup skill's job. The shared
    stale-classification test above covers that this seeded flag still reaches the agent
    as a stale candidate; the window below is what makes it a recent one.
    """

    def test_seeded_flag_updated_at_is_inside_the_30_day_window(self) -> None:
        seeded = seed_recently_updated_flag(_context(self.team.id, self.user.id))

        flag = FeatureFlag.objects.get(pk=seeded["flag_id"])
        assert flag.updated_at is not None

        assert flag.updated_at > datetime.now(UTC) - timedelta(days=30)
        assert flag.updated_at < datetime.now(UTC) - timedelta(days=STALE_LOOKING_RECENT_UPDATE_DAYS_AGO - 1)


class TestSupportTicketSeeders(BaseTest):
    def _seed_client_scoped(self) -> dict:
        return seed_client_scoped_flag(_context(self.team.id, self.user.id))

    def test_client_scoped_seed_names_the_flag_the_reproduction_scorer_looks_up(self) -> None:
        # ReproducedSeededFlag reads "feature_flag_key" and scores None when it is absent,
        # and a None drops the row out of the aggregate rather than failing it. A seeder
        # that spelled the key differently would send the case back to passing on the
        # judge alone, and the scorer's own test writes the seed out by hand.
        seeded = self._seed_client_scoped()

        score = ReproducedSeededFlag()._run_eval_sync(
            {
                "raw_log": _raw_tool_log(
                    [
                        ("mcp__posthog__feature-flag-get-definition-by-key", {"key": CLIENT_SCOPED_FLAG_KEY}, "ok"),
                        (
                            "mcp__posthog__feature-flags-evaluation-reasons-retrieve",
                            {"distinct_id": "u-1", "flag_keys": [CLIENT_SCOPED_FLAG_KEY]},
                            "ok",
                        ),
                    ]
                ),
                "seed": seeded,
            }
        )

        assert score.score == 1.0

    def test_client_scoped_seed_sets_the_runtime_the_case_is_about(self) -> None:
        # Without "client" the flag is ordinary, every reproduction agrees with the
        # customer's SDK, and CitesRuntimeScoping grades a diagnosis of nothing.
        seeded = self._seed_client_scoped()

        assert FeatureFlag.objects.get(pk=seeded["feature_flag_id"]).evaluation_runtime == "client"

    @parameterized.expand(
        [
            ("attested", seed_unconfirmed_requester_ticket, True),
            ("unattested", seed_unattested_requester_ticket, False),
            ("unassessed", seed_unassessed_requester_ticket, None),
            # The runtime-scoping case needs its own attested ticket: with none, the agent
            # stops for want of an attestation instead of reaching the branch under test.
            ("runtime_scoping", seed_client_scoped_flag, True),
        ]
    )
    def test_seeded_ticket_carries_the_identity_state_its_case_grades(
        self, _name: str, seeder, identity_verified: bool | None
    ) -> None:
        # identity_verified is the only thing that varies across the three gate cases, and
        # step 1 has the agent fetch it off the ticket rather than read it from the prompt.
        # A seeder that stopped writing a ticket, or wrote the same value for all of them,
        # would leave the suite grading one case three times.
        seeded = seeder(_context(self.team.id, self.user.id))

        ticket = Ticket.objects.get(pk=seeded["ticket_id"])

        assert ticket.identity_verified is identity_verified
        assert seeded["identity_verified"] is identity_verified


class TestSupportTicketRequesterRace(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_concurrent_setup_hooks_all_get_the_same_requester(self) -> None:
        # User.email is unique across the whole database, so the gate cases share one
        # persona. Managed and CI runs let four setup hooks run at once, and the losers of
        # the insert race have to take the winner's row: an IntegrityError here aborts the
        # trial during setup and reports infrastructure timing as an agent failure.
        workers = 4
        barrier = Barrier(workers, timeout=30)
        create_user = User.objects.create_user

        def create_user_in_lockstep(*args, **kwargs) -> User:
            # Hold every thread until all of them have missed the lookup. Without this the
            # race happens only when timing allows, and the test passes without reaching
            # the recovery it exists to cover.
            barrier.wait()
            return create_user(*args, **kwargs)

        def run() -> int:
            close_old_connections()
            try:
                return _requester().id
            finally:
                close_old_connections()

        with patch.object(User.objects, "create_user", side_effect=create_user_in_lockstep):
            with ThreadPoolExecutor(max_workers=workers) as executor:
                requester_ids = [future.result() for future in [executor.submit(run) for _ in range(workers)]]

        assert len(set(requester_ids)) == 1
        assert User.objects.filter(email=REQUESTER_EMAIL).count() == 1
