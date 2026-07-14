from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.pulse.backend.sources.feature_flags import MAX_FLAGS, FeatureFlagRolloutSource


class TestFeatureFlagRolloutGather(BaseTest):
    def _flag(self, days_ago: float = 1, **kwargs: Any) -> FeatureFlag:
        defaults: dict[str, Any] = {
            "team": self.team,
            "created_by": self.user,
            "key": "new-onboarding",
            "created_at": timezone.now() - timedelta(days=days_ago),
        }
        defaults.update(kwargs)
        return FeatureFlag.objects.create(**defaults)

    def test_gather_returns_context_item_for_recent_flag(self) -> None:
        flag = self._flag()

        items = FeatureFlagRolloutSource().gather(self.team, None, period_days=7)

        assert len(items) == 1
        item = items[0]
        assert item.source == "feature_flags"
        assert item.kind == "context"
        assert "new-onboarding" in item.title
        assert item.evidence == [{"type": "flag", "ref": str(flag.pk), "label": "new-onboarding"}]
        assert item.fingerprint_hint == f"feature_flags:{flag.pk}"

    @parameterized.expand(
        [
            ("in_window", {}, 1),
            ("before_window", {"days_ago": 8}, 0),
            ("deleted", {"deleted": True}, 0),
            ("inactive", {"active": False}, 0),
        ]
    )
    def test_gather_filtering(self, _name: str, overrides: dict[str, Any], expected_count: int) -> None:
        self._flag(**overrides)

        items = FeatureFlagRolloutSource().gather(self.team, None, period_days=7)

        assert len(items) == expected_count

    def test_cap_keeps_newest(self) -> None:
        for index in range(MAX_FLAGS + 3):
            self._flag(days_ago=index / 24, key=f"flag-{index}")

        items = FeatureFlagRolloutSource().gather(self.team, None, period_days=7)

        assert len(items) == MAX_FLAGS
        assert "flag-0" in items[0].title
