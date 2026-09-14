from collections.abc import Iterator

import pytest
from unittest.mock import patch

from products.metrics.backend.facade.contracts import METRICS_FUNDAMENTALS_FEATURE_FLAG


@pytest.fixture(autouse=True)
def enable_metrics_feature_flag() -> Iterator[None]:
    # MetricsViewSet is gated behind the `metrics` feature flag (private alpha), so every
    # endpoint test in this package would 403 without it. The explain action carries a
    # second flag on top. Enable both and leave all others at their default (False),
    # matching production for alpha teams. The dedicated gate tests override this to
    # assert the 403.
    def _feature_enabled(flag_key: str, *args: object, **kwargs: object) -> bool:
        return flag_key in ("metrics", METRICS_FUNDAMENTALS_FEATURE_FLAG)

    with patch("posthoganalytics.feature_enabled", side_effect=_feature_enabled):
        yield
