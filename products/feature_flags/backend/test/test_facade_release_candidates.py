from posthog.test.base import BaseTest

from posthog.constants import AvailableFeature
from posthog.models import Team

from products.access_control.backend.facade.testing import create_access_control
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.feature_flags.backend.facade.release_candidates import (
    ReleaseFlagCondition,
    ReleaseFlagVariant,
    release_flag_states,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestReleaseFlagStates(BaseTest):
    def test_reads_the_rollout_of_the_team_s_live_flags(self) -> None:
        rollout = FeatureFlag.objects.create(
            team=self.team,
            key="quiet-theme",
            filters={
                "groups": [{"properties": [{"key": "plan", "value": "paid"}], "rollout_percentage": None}],
                "multivariate": {"variants": [{"key": "test", "rollout_percentage": 100}]},
                "holdout": {"id": 1, "exclusion_percentage": 10},
                "feature_enrollment": True,
            },
        )
        rules = FeatureFlag.objects.create(team=self.team, key="rules", filters={"version": 2, "rules": []})
        deleted = FeatureFlag.objects.create(team=self.team, key="gone", deleted=True)
        elsewhere = FeatureFlag.objects.create(team=Team.objects.create(organization=self.organization), key="other")

        states = release_flag_states(
            team_id=self.team.id, flag_ids=[rollout.id, rules.id, deleted.id, elsewhere.id], access_control=None
        )

        assert [(state.key, state.is_v1_config) for state in states] == [("quiet-theme", True), ("rules", False)]
        assert (states[0].conditions, states[0].variants) == (
            (
                ReleaseFlagCondition(
                    property_count=1, rollout_percentage=None, variant=None, aggregation_group_type_index=None
                ),
            ),
            (ReleaseFlagVariant(key="test", rollout_percentage=100),),
        )
        assert (states[0].holdout_exclusion_percentage, states[0].feature_enrollment) == (10, True)
        assert (states[1].conditions, states[1].variants) == ((), ())

    def test_leaves_out_a_flag_the_viewer_may_not_see(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        author = self._create_user("author@example.com")
        shown = FeatureFlag.objects.create(team=self.team, key="shown", created_by=author)
        hidden = FeatureFlag.objects.create(team=self.team, key="hidden", created_by=author)
        create_access_control(
            team_id=self.team.id, resource="feature_flag", resource_id=str(hidden.id), access_level="none"
        )

        states = release_flag_states(
            team_id=self.team.id,
            flag_ids=[shown.id, hidden.id],
            access_control=UserAccessControl(user=self.user, team=self.team),
        )

        assert [state.key for state in states] == ["shown"]
