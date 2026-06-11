from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from products.feature_flags.backend.flag_status import (
    FeatureFlagStatus,
    FeatureFlagStatusChecker,
    filter_flags_by_active_param,
)
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
        # Usage-based stale: active but not evaluated in 30+ days
        self.stale_by_usage = FeatureFlag.objects.create(
            team=self.team,
            key="stale-by-usage",
            active=True,
            last_called_at=timezone.now() - timedelta(days=35),
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            created_by=self.user,
        )
        # Multivariate stale: one variant at 100% plus a fully rolled out release condition
        self.stale_multivariate = FeatureFlag.objects.create(
            team=self.team,
            key="stale-multivariate",
            active=True,
            created_at=timezone.now() - timedelta(days=60),
            filters={
                "multivariate": {"variants": [{"key": "control", "rollout_percentage": 100}]},
                "groups": [{"properties": [], "rollout_percentage": 100}],
            },
            created_by=self.user,
        )

    def _filter(self, value):
        return set(
            filter_flags_by_active_param(FeatureFlag.objects.filter(team=self.team), value).values_list(
                "key", flat=True
            )
        )

    def test_filters_enabled(self):
        assert self._filter("true") == {"enabled", "stale", "stale-by-usage", "stale-multivariate"}

    def test_filters_disabled(self):
        assert self._filter("false") == {"disabled"}

    def test_filters_stale(self):
        assert self._filter("STALE") == {"stale", "stale-by-usage", "stale-multivariate"}

    def test_accepts_native_booleans(self):
        assert self._filter(True) == {"enabled", "stale", "stale-by-usage", "stale-multivariate"}
        assert self._filter(False) == {"disabled"}

    def test_stale_filter_agrees_with_status_checker(self):
        """The SQL filter and the per-flag status checker must classify the same flags as stale."""
        checker_stale = {
            flag.key
            for flag in FeatureFlag.objects.filter(team=self.team)
            if FeatureFlagStatusChecker(feature_flag=flag).get_status()[0] == FeatureFlagStatus.STALE
        }
        assert self._filter("STALE") == checker_stale
