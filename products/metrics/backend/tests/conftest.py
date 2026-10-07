from collections.abc import Iterator

import pytest
from unittest.mock import patch

from posthog.api.snuffle_proxy import SNUFFLE_API_FEATURE_FLAG


@pytest.fixture(autouse=True)
def enable_metrics_feature_flag() -> Iterator[None]:
    # Enable the flags needed by the metrics endpoint tests.
    # MetricsViewSet needs `metrics`.
    # The Prometheus proxy needs `SNUFFLE_API_FEATURE_FLAG`.
    # Gate tests set their flag to False.
    def _feature_enabled(flag_key: str, *args: object, **kwargs: object) -> bool:
        return flag_key in ("metrics", SNUFFLE_API_FEATURE_FLAG)

    with patch("posthoganalytics.feature_enabled", side_effect=_feature_enabled):
        yield
