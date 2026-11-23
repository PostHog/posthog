from posthog.test.base import BaseTest

from posthog.models import Team

from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.facade import api
from products.subscriptions.backend.facade.testing import create_subscription


class TestDisableSubscription(BaseTest):
    def test_disables_only_an_enabled_subscription_of_the_given_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        mine, theirs = (
            str(create_subscription(team_id=team.pk, insight_id=Insight.objects.create(team=team).pk))
            for team in (self.team, other_team)
        )

        assert api.enabled_subscription_ids([self.team.pk]) == [mine]
        assert api.disable_subscription(mine, team_id=self.team.pk) is True
        assert api.disable_subscription(mine, team_id=self.team.pk) is False
        assert api.disable_subscription(theirs, team_id=self.team.pk) is False
        assert api.enabled_subscription_ids([self.team.pk, other_team.pk]) == [theirs]
