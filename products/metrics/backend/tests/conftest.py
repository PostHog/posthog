from collections.abc import Iterator

import pytest
from unittest.mock import patch

from django.conf import settings

from posthog.api.snuffle_proxy import SNUFFLE_API_FEATURE_FLAG
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.metrics import METRICS2_AGG_TABLE_SQL, METRICS2_FLAT_VIEW_SQL, METRICS2_INPUT_TO_METRICS_AGG_MV

from products.metrics.backend.facade.contracts import METRICS_FUNDAMENTALS_FEATURE_FLAG


@pytest.fixture(autouse=True)
def enable_metrics_feature_flag() -> Iterator[None]:
    # Enable the flags needed by the metrics endpoint tests.
    # MetricsViewSet needs `metrics`.
    # The explain action needs `METRICS_FUNDAMENTALS_FEATURE_FLAG`.
    # The Prometheus proxy needs `SNUFFLE_API_FEATURE_FLAG`.
    # Gate tests set their flag to False.
    def _feature_enabled(flag_key: str, *args: object, **kwargs: object) -> bool:
        return flag_key in ("metrics", METRICS_FUNDAMENTALS_FEATURE_FLAG, SNUFFLE_API_FEATURE_FLAG)

    with patch("posthoganalytics.feature_enabled", side_effect=_feature_enabled):
        yield


@pytest.fixture(scope="session", autouse=True)
def create_metrics_array_view_schema() -> None:
    # The spike objects are not in `schema.py`, so the test database lacks them.
    # Create them here when the readers are switched to a flat view.
    if not settings.METRICS_ARRAY_VIEW:
        return
    for sql in (METRICS2_AGG_TABLE_SQL(), METRICS2_INPUT_TO_METRICS_AGG_MV(), METRICS2_FLAT_VIEW_SQL()):
        sync_execute(sql)
