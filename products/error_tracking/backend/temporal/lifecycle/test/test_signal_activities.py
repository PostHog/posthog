from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import OperationalError

from products.error_tracking.backend.temporal.lifecycle.issue_created.activities import (
    emit_issue_created_signal_activity,
)
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.activities import (
    emit_issue_reopened_signal_activity,
)
from products.error_tracking.backend.temporal.lifecycle.issue_spiking.activities import (
    emit_issue_spiking_signal_activity,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "signal_activity",
    [emit_issue_created_signal_activity, emit_issue_reopened_signal_activity, emit_issue_spiking_signal_activity],
)
async def test_signal_activity_leaves_exception_capture_to_the_interceptor(
    signal_activity: Callable[[Any], Awaitable[None]],
) -> None:
    inputs = MagicMock(computed_baseline=1.0, current_bucket_value=5.0)
    dropped_connection = OperationalError("server closed the connection unexpectedly")

    with (
        patch(
            f"{signal_activity.__module__}.emit_issue_lifecycle_signal",
            new=AsyncMock(side_effect=dropped_connection),
        ),
        patch("posthoganalytics.capture_exception") as capture_exception,
    ):
        with pytest.raises(OperationalError):
            await signal_activity(inputs)

    capture_exception.assert_not_called()
