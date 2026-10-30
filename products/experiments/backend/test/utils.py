from contextlib import AbstractContextManager
from typing import Any

from unittest.mock import patch

from products.experiments.backend.hogql_queries.exposure_query_logic import EXPERIMENT_EXPOSURE_EVENT_FLAG


def patch_exposure_event_flag(*, enabled: bool) -> AbstractContextManager[Any]:
    """Patch posthoganalytics.feature_enabled to return `enabled` for EXPERIMENT_EXPOSURE_EVENT_FLAG.

    Every other flag returns False. A blanket True would also turn on unrelated flag-gated
    behavior, such as HogQL query modifiers, and change what the test exercises.
    """

    def fake_feature_enabled(flag_key: str, *args: Any, **kwargs: Any) -> bool:
        return enabled and flag_key == EXPERIMENT_EXPOSURE_EVENT_FLAG

    return patch("posthoganalytics.feature_enabled", side_effect=fake_feature_enabled)
