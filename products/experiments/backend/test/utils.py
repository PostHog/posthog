from contextlib import AbstractContextManager
from typing import Any

from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from products.experiments.backend.hogql_queries.exposure_query_logic import EXPERIMENT_EXPOSURE_EVENT_FLAG

WORKFLOW_NOT_FOUND = RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")


def patch_exposure_event_flag(*, enabled: bool) -> AbstractContextManager[Any]:
    """Patch posthoganalytics.feature_enabled to return `enabled` for EXPERIMENT_EXPOSURE_EVENT_FLAG.

    Every other flag returns False. A blanket True would also turn on unrelated flag-gated
    behavior, such as HogQL query modifiers, and change what the test exercises.
    """

    def fake_feature_enabled(flag_key: str, *args: Any, **kwargs: Any) -> bool:
        return enabled and flag_key == EXPERIMENT_EXPOSURE_EVENT_FLAG

    return patch("posthoganalytics.feature_enabled", side_effect=fake_feature_enabled)


def patch_recalculation_workflow_status(state: WorkflowExecutionStatus | Exception) -> AbstractContextManager[Any]:
    """Patch the Temporal describe call that decides whether a recalculation row past the staleness threshold
    is still active. An exception is raised from the describe call."""
    handle = MagicMock()
    if isinstance(state, Exception):
        handle.describe = AsyncMock(side_effect=state)
    else:
        handle.describe = AsyncMock(return_value=MagicMock(status=state))
    return patch(
        "products.experiments.backend.recalculation.async_connect",
        new=AsyncMock(return_value=MagicMock(get_workflow_handle=MagicMock(return_value=handle))),
    )
