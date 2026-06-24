from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

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
        # Empty-variants stale: a present-but-empty multivariate block routes through the boolean
        # branch (both the SQL filter's jsonb_array_length(variants)=0 and the checker's has_variants).
        self.stale_empty_variants = FeatureFlag.objects.create(
            team=self.team,
            key="stale-empty-variants",
            active=True,
            created_at=timezone.now() - timedelta(days=60),
            filters={
                "multivariate": {"variants": []},
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
        assert self._filter("true") == {
            "enabled",
            "stale",
            "stale-by-usage",
            "stale-multivariate",
            "stale-empty-variants",
        }

    def test_filters_disabled(self):
        assert self._filter("false") == {"disabled"}

    def test_filters_stale(self):
        assert self._filter("STALE") == {"stale", "stale-by-usage", "stale-multivariate", "stale-empty-variants"}

    def test_accepts_native_booleans(self):
        assert self._filter(True) == {
            "enabled",
            "stale",
            "stale-by-usage",
            "stale-multivariate",
            "stale-empty-variants",
        }
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

    # (name, filters, effectively_full_rollout, has_targeting_conditions, max_rollout_percentage, is_multivariate)
    @parameterized.expand(
        [
            (
                "blanket_full_rollout",
                {"groups": [{"properties": [], "rollout_percentage": 100}]},
                True,
                False,
                100,
                False,
            ),
            (
                "partial_rollout",
                {"groups": [{"properties": [], "rollout_percentage": 50}]},
                False,
                False,
                50,
                False,
            ),
            (
                "targeting_conditions",
                {"groups": [{"properties": [{"key": "email", "value": "x"}], "rollout_percentage": 100}]},
                False,
                True,
                100,
                False,
            ),
            # A missing rollout_percentage evaluates to 100% at runtime, so max_rollout_percentage
            # reflects that. effectively_full_rollout stays stricter (requires an explicit 100), to
            # match the staleness detection it shares logic with.
            ("missing_rollout_percentage", {"groups": [{"properties": []}]}, False, False, 100, False),
            # No release conditions means a boolean flag evaluates to true for everyone.
            ("no_groups", {"groups": []}, True, False, None, False),
            (
                "max_rollout_percentage_across_multiple_groups",
                {
                    "groups": [
                        {"properties": [{"key": "email", "value": "x"}], "rollout_percentage": 30},
                        {"properties": [], "rollout_percentage": 75},
                    ]
                },
                False,
                True,
                75,
                False,
            ),
            (
                "multivariate_fully_rolled_out",
                {
                    "multivariate": {"variants": [{"key": "control", "rollout_percentage": 100}]},
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                },
                True,
                False,
                100,
                True,
            ),
            (
                "multivariate_not_fully_rolled_out",
                {
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 50},
                            {"key": "test", "rollout_percentage": 50},
                        ]
                    },
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                },
                False,
                False,
                100,
                True,
            ),
            # An empty variant list is treated as a boolean flag, so a 100% blanket group is a full
            # rollout and is_multivariate is False — consistent with effectively_full_rollout.
            (
                "empty_multivariate_variants",
                {"multivariate": {"variants": []}, "groups": [{"properties": [], "rollout_percentage": 100}]},
                True,
                False,
                100,
                False,
            ),
        ]
    )
    def test_rollout_summary(
        self,
        _name,
        filters,
        effectively_full_rollout,
        has_targeting_conditions,
        max_rollout_percentage,
        is_multivariate,
    ):
        summary = self._summary(filters)
        assert summary.effectively_full_rollout is effectively_full_rollout
        assert summary.has_targeting_conditions is has_targeting_conditions
        assert summary.max_rollout_percentage == max_rollout_percentage
        assert summary.is_multivariate is is_multivariate

    def test_handles_none_filters(self):
        flag = FeatureFlag.objects.create(team=self.team, key="none-filters", created_by=self.user)
        flag.filters = None
        summary = FeatureFlagStatusChecker(feature_flag=flag).get_rollout_summary(flag)
        assert summary.effectively_full_rollout is True
        assert summary.max_rollout_percentage is None
        assert summary.is_multivariate is False
