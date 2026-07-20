from collections.abc import Iterator

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def enable_metrics_feature_flag() -> Iterator[None]:
    # MetricsViewSet is gated behind the `metrics` feature flag (private alpha), so every
    # endpoint test in this package would 403 without it. Enable only the metrics flag and
    # leave all others at their default (False), matching production for non-alpha teams.
    # The dedicated gate test overrides this to assert the 403.
    def _feature_enabled(flag_key: str, *args: object, **kwargs: object) -> bool:
        return flag_key == "metrics"

    with patch("posthoganalytics.feature_enabled", side_effect=_feature_enabled):
        yield
