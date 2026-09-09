from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from products.access_control.backend.facade.mcp_access import mcp_access_denial
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.team_feature_flag_policy_config import team_requires_flag_tags
from products.feature_flags.evals.seeders import (
    DEPENDENT_FLAG_KEY,
    EXISTING_FLAG_FROM_PERCENTAGE,
    EXISTING_FLAG_KEY,
    EXISTING_FLAG_TO_PERCENTAGE,
    ROLLOUT_FLAG_KEY,
    ROLLOUT_FROM_PERCENTAGE,
    ROLLOUT_INITIAL_FILTERS,
    ROLLOUT_TO_PERCENTAGE,
    STALE_FLAG_KEY,
    STALE_FLAG_LAST_CALLED_DAYS_AGO,
    seed_active_flag,
    seed_existing_key_flag,
    seed_inactive_flag,
    seed_metadata_flag,
    seed_read_only_mcp_org,
    seed_require_flag_tags,
    seed_rollout_flag,
    seed_stale_flag,
)

if TYPE_CHECKING:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext


class TestFlagLifecycleSeeders(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The seeders read team_id and user_id only, so a namespace stands in for the
        # real sandbox context.
        self.context = cast("CustomPromptSandboxContext", SimpleNamespace(team_id=self.team.id, user_id=self.user.id))

    # `PreservedUnrelatedConfig` and the tool scorers read these keys out of the payload,
    # and the scorer tests hand-build the dict rather than calling the seeder. A seeder
    # that stopped returning one of them would fail every case with "seed carries no
    # initial_filters", which reads as an agent regression rather than a broken fixture.
    @parameterized.expand(
        [
            ("metadata", seed_metadata_flag),
            ("existing_key", seed_existing_key_flag),
            ("active", seed_active_flag),
            ("inactive", seed_inactive_flag),
            ("rollout", seed_rollout_flag),
            ("stale", seed_stale_flag),
        ]
    )
    def test_seeder_payload_identifies_its_flag(self, _name: str, seeder: Any) -> None:
        payload = seeder(self.context)

        flag = FeatureFlag.objects.get(team_id=self.team.id, pk=payload["feature_flag_id"])
        assert payload["feature_flag_key"] == flag.key
        assert payload["initial_filters"] == flag.filters
        assert payload["initial_active"] == flag.active

    def test_rollout_seeder_carries_the_percentages_the_scorer_reads(self) -> None:
        payload = seed_rollout_flag(self.context)

        assert payload["initial_filters"] == ROLLOUT_INITIAL_FILTERS
        assert payload["rollout_from_percentage"] == ROLLOUT_FROM_PERCENTAGE
        assert payload["rollout_to_percentage"] == ROLLOUT_TO_PERCENTAGE
        assert payload["feature_flag_key"] == ROLLOUT_FLAG_KEY

    def test_existing_key_seeder_carries_the_percentages_the_scorer_reads(self) -> None:
        payload = seed_existing_key_flag(self.context)

        assert payload["feature_flag_key"] == EXISTING_FLAG_KEY
        assert payload["rollout_from_percentage"] == EXISTING_FLAG_FROM_PERCENTAGE
        assert payload["rollout_to_percentage"] == EXISTING_FLAG_TO_PERCENTAGE
        rollouts = [group["rollout_percentage"] for group in payload["initial_filters"]["groups"]]
        assert rollouts == [EXISTING_FLAG_FROM_PERCENTAGE]

    # The dependent flag is the case's whole point, and `FinalMessageNames` grades the
    # answer against this key. A seeder that stopped planting it would leave the case
    # asking for evidence that is not there.
    def test_stale_seeder_plants_a_dependent_flag_pointing_at_the_stale_one(self) -> None:
        payload = seed_stale_flag(self.context)

        assert payload["feature_flag_key"] == STALE_FLAG_KEY
        assert payload["dependent_flag_key"] == DEPENDENT_FLAG_KEY
        assert payload["last_called_days_ago"] == STALE_FLAG_LAST_CALLED_DAYS_AGO

        dependent = FeatureFlag.objects.get(team_id=self.team.id, key=DEPENDENT_FLAG_KEY)
        conditions = dependent.filters["groups"][0]["properties"]
        assert [condition["key"] for condition in conditions] == [str(payload["feature_flag_id"])]
        assert conditions[0]["operator"] == "flag_evaluates_to"

    # Both policy seeders raise instead of returning when the policy did not take, so a
    # case can never score an agent for handling a restriction it never met. These check
    # the happy path actually applies the policy the case is named after.
    def test_read_only_seeder_caps_the_organization(self) -> None:
        seed_read_only_mcp_org(self.context)

        self.organization.refresh_from_db()
        assert mcp_access_denial(self.organization, is_mcp=True, writes=True)

    def test_require_tags_seeder_binds_the_policy_to_the_team(self) -> None:
        seed_require_flag_tags(self.context)

        assert team_requires_flag_tags(self.team.id)
