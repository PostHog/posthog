from typing import Any

import pytest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.review_hog.backend.temporal.outcomes_activities import _scoped_capture_off_loop

_MOD = "products.review_hog.backend.temporal.outcomes_activities"


class _Scope:
    def __init__(self) -> None:
        self.exits = 0

    def __enter__(self) -> str:
        return "capture-handle"

    def __exit__(self, *exc: Any) -> None:
        self.exits += 1


class TestScopedCaptureOffLoop:
    # Leaving the scope is what flushes the buffered events, so it has to run on every path.
    # `ph_scoped_capture` states the contract it is preserving: "Flush even when the caller's block
    # raises — events already captured before the exception shouldn't be dropped with the buffer."
    # A sweep that dies mid-team is exactly when the outcomes decided so far still need delivering.
    @parameterized.expand([("body_succeeds", False), ("body_raises", True)])
    def test_scope_is_left_exactly_once(self, _name: str, body_raises: bool) -> None:
        scope = _Scope()

        async def body() -> object:
            async with _scoped_capture_off_loop() as capture:
                if body_raises:
                    raise RuntimeError("sweep died")
                return capture

        with patch(f"{_MOD}.ph_scoped_capture", return_value=scope):
            if body_raises:
                with pytest.raises(RuntimeError):
                    async_to_sync(body)()
            else:
                assert async_to_sync(body)() == "capture-handle"

        assert scope.exits == 1
