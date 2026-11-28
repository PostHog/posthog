from posthog.test.base import BaseTest

from posthog.constants import AvailableFeature
from posthog.models import Team

from products.access_control.backend.facade.testing import create_access_control
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.early_access_features.backend.facade.api import EarlyAccessListAccess, early_access_features_for_flags
from products.early_access_features.backend.models import EarlyAccessFeature
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestEarlyAccessFeaturesForFlags(BaseTest):
    def test_lists_the_team_s_features_on_the_flags_and_names_flags_with_a_hidden_one(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        author = self._create_user("author@example.com")
        beta_flag = FeatureFlag.objects.create(team=self.team, key="quiet-theme")
        hidden_flag = FeatureFlag.objects.create(team=self.team, key="secret-theme")
        other_team = Team.objects.create(organization=self.organization)
        other_flag = FeatureFlag.objects.create(team=other_team, key="quiet-theme")
        EarlyAccessFeature.objects.create(
            team=self.team, feature_flag=beta_flag, name="Quiet theme beta", stage="beta", created_by=author
        )
        hidden = EarlyAccessFeature.objects.create(
            team=self.team, feature_flag=hidden_flag, name="Secret beta", stage="alpha", created_by=author
        )
        EarlyAccessFeature.objects.create(team=other_team, feature_flag=other_flag, name="Elsewhere", stage="beta")
        create_access_control(
            team_id=self.team.id, resource="early_access_feature", resource_id=str(hidden.id), access_level="none"
        )

        access_filter = UserAccessControl(user=self.user, team=self.team).list_access_filter("early_access_feature")
        assert access_filter is not None

        result = early_access_features_for_flags(
            team_id=self.team.id,
            flag_ids=[beta_flag.id, hidden_flag.id, other_flag.id],
            access=EarlyAccessListAccess(
                viewer_id=self.user.id,
                only_allowed=access_filter.only_allowed,
                allowed_ids=access_filter.allowed_ids,
                blocked_ids=access_filter.blocked_ids,
            ),
        )

        assert [(feature.name, feature.stage, feature.feature_flag_id) for feature in result.features] == [
            ("Quiet theme beta", "beta", beta_flag.id)
        ]
        assert result.hidden_flag_ids == frozenset({hidden_flag.id})
