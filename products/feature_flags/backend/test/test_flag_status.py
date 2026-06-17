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


class TestRolloutSummary(BaseTest):
    def _summary(self, filters):
        flag = FeatureFlag.objects.create(team=self.team, key="rollout-flag", filters=filters, created_by=self.user)
        return FeatureFlagStatusChecker(feature_flag=flag).get_rollout_summary(flag)

    def test_blanket_full_rollout(self):
        summary = self._summary({"groups": [{"properties": [], "rollout_percentage": 100}]})
        assert summary.effectively_full_rollout is True
        assert summary.has_targeting_conditions is False
        assert summary.max_rollout_percentage == 100
        assert summary.is_multivariate is False

    def test_partial_rollout(self):
        summary = self._summary({"groups": [{"properties": [], "rollout_percentage": 50}]})
        assert summary.effectively_full_rollout is False
        assert summary.has_targeting_conditions is False
        assert summary.max_rollout_percentage == 50

    def test_targeting_conditions(self):
        summary = self._summary(
            {"groups": [{"properties": [{"key": "email", "value": "x"}], "rollout_percentage": 100}]}
        )
        assert summary.effectively_full_rollout is False
        assert summary.has_targeting_conditions is True
        assert summary.max_rollout_percentage == 100

    def test_missing_rollout_percentage_treated_as_full_for_max_only(self):
        # A missing rollout_percentage evaluates to 100% at runtime, so max_rollout_percentage
        # reflects that. effectively_full_rollout stays stricter (requires an explicit 100), to
        # match the staleness detection it shares logic with.
        summary = self._summary({"groups": [{"properties": []}]})
        assert summary.max_rollout_percentage == 100
        assert summary.effectively_full_rollout is False

    def test_no_groups(self):
        summary = self._summary({"groups": []})
        # No release conditions means a boolean flag evaluates to true for everyone.
        assert summary.effectively_full_rollout is True
        assert summary.has_targeting_conditions is False
        assert summary.max_rollout_percentage is None

    def test_multivariate_fully_rolled_out(self):
        summary = self._summary(
            {
                "multivariate": {"variants": [{"key": "control", "rollout_percentage": 100}]},
                "groups": [{"properties": [], "rollout_percentage": 100}],
            }
        )
        assert summary.is_multivariate is True
        assert summary.effectively_full_rollout is True

    def test_multivariate_not_fully_rolled_out(self):
        summary = self._summary(
            {
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
                "groups": [{"properties": [], "rollout_percentage": 100}],
            }
        )
        assert summary.is_multivariate is True
        assert summary.effectively_full_rollout is False

    def test_handles_none_filters(self):
        flag = FeatureFlag.objects.create(team=self.team, key="none-filters", created_by=self.user)
        flag.filters = None
        summary = FeatureFlagStatusChecker(feature_flag=flag).get_rollout_summary(flag)
        assert summary.effectively_full_rollout is True
        assert summary.max_rollout_percentage is None
        assert summary.is_multivariate is False
