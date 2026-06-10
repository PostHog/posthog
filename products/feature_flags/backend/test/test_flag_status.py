from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from products.feature_flags.backend.flag_status import filter_flags_by_active_param
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestFilterFlagsByActiveParam(BaseTest):
    def setUp(self):
        super().setUp()
        self.enabled = FeatureFlag.objects.create(team=self.team, key="enabled", active=True, created_by=self.user)
        self.disabled = FeatureFlag.objects.create(team=self.team, key="disabled", active=False, created_by=self.user)
        # Config-based stale: 30+ days old, no usage data, fully rolled out to 100%
        self.stale = FeatureFlag.objects.create(
            team=self.team,
            key="stale",
            active=True,
            created_at=timezone.now() - timedelta(days=60),
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )

    def _filter(self, value):
        return set(
            filter_flags_by_active_param(FeatureFlag.objects.filter(team=self.team), value).values_list(
                "key", flat=True
            )
        )

    def test_filters_enabled(self):
        assert self._filter("true") == {"enabled", "stale"}

    def test_filters_disabled(self):
        assert self._filter("false") == {"disabled"}

    def test_filters_stale(self):
        assert self._filter("STALE") == {"stale"}

    def test_accepts_native_booleans(self):
        assert self._filter(True) == {"enabled", "stale"}
        assert self._filter(False) == {"disabled"}
