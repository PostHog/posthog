import importlib

from posthog.test.base import APIBaseTest

from django.apps import apps

from products.early_access_features.backend.models import EarlyAccessFeature
from products.feature_flags.backend.models.feature_flag import FeatureFlag

m8 = importlib.import_module(
    "products.early_access_features.backend.migrations.0008_backfill_earlyaccessfeature_created_by"
)


class TestEarlyAccessFeatureCreatedByBackfill(APIBaseTest):
    def test_backfills_from_flag_creator_and_leaves_others_untouched(self) -> None:
        other_user = self._create_user("other@posthog.com")
        flag = FeatureFlag.objects.create(team=self.team, key="flag-with-creator", created_by=other_user)
        unset = EarlyAccessFeature.objects.create(team=self.team, name="unset", stage="beta", feature_flag=flag)
        already_set = EarlyAccessFeature.objects.create(
            team=self.team, name="already-set", stage="beta", feature_flag=flag, created_by=self.user
        )
        flagless = EarlyAccessFeature.objects.create(team=self.team, name="flagless", stage="beta")

        m8.backfill_created_by(apps, None)

        unset.refresh_from_db()
        already_set.refresh_from_db()
        flagless.refresh_from_db()
        assert unset.created_by_id == other_user.id
        assert already_set.created_by_id == self.user.id
        assert flagless.created_by_id is None
