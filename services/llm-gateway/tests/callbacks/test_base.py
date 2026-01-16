from unittest.mock import patch

import pytest

from llm_gateway.callbacks.base import InstrumentedCallback
from llm_gateway.metrics.prometheus import CALLBACK_ERRORS, CALLBACK_SUCCESS


class MockCallback(InstrumentedCallback):
    callback_name = "test"

    def __init__(self):
        super().__init__()
        self.on_success_called = False
        self.on_failure_called = False
        self.raise_on_success = False
        self.raise_on_failure = False

    async def _on_success(self, kwargs, response_obj, start_time, end_time) -> None:
        if self.raise_on_success:
            raise ValueError("Test error in success")
        self.on_success_called = True

    async def _on_failure(self, kwargs, response_obj, start_time, end_time) -> None:
        if self.raise_on_failure:
            raise ValueError("Test error in failure")
        self.on_failure_called = True


class TestInstrumentedCallback:
    @pytest.fixture
    def callback(self):
        return MockCallback()

    @pytest.mark.asyncio
    async def test_success_event_calls_on_success(self, callback: MockCallback) -> None:
        await callback.async_log_success_event({}, None, 0.0, 1.0)

        assert callback.on_success_called is True
        assert callback.on_failure_called is False

    @pytest.mark.asyncio
    async def test_failure_event_calls_on_failure(self, callback: MockCallback) -> None:
        await callback.async_log_failure_event({}, None, 0.0, 1.0)

        assert callback.on_failure_called is True
        assert callback.on_success_called is False

    @pytest.mark.asyncio
    async def test_success_event_increments_success_metric(self, callback: MockCallback) -> None:
        initial = CALLBACK_SUCCESS.labels(callback="test")._value.get()

        await callback.async_log_success_event({}, None, 0.0, 1.0)

        assert CALLBACK_SUCCESS.labels(callback="test")._value.get() == initial + 1

    @pytest.mark.asyncio
    async def test_failure_event_increments_success_metric(self, callback: MockCallback) -> None:
        initial = CALLBACK_SUCCESS.labels(callback="test")._value.get()

        await callback.async_log_failure_event({}, None, 0.0, 1.0)

        assert CALLBACK_SUCCESS.labels(callback="test")._value.get() == initial + 1

    @pytest.mark.asyncio
    async def test_error_in_success_increments_error_metric(self, callback: MockCallback) -> None:
        callback.raise_on_success = True
        initial = CALLBACK_ERRORS.labels(callback="test", error_type="ValueError")._value.get()

        await callback.async_log_success_event({}, None, 0.0, 1.0)

        assert CALLBACK_ERRORS.labels(callback="test", error_type="ValueError")._value.get() == initial + 1

    @pytest.mark.asyncio
    async def test_error_in_failure_increments_error_metric(self, callback: MockCallback) -> None:
        callback.raise_on_failure = True
        initial = CALLBACK_ERRORS.labels(callback="test", error_type="ValueError")._value.get()

        await callback.async_log_failure_event({}, None, 0.0, 1.0)

        assert CALLBACK_ERRORS.labels(callback="test", error_type="ValueError")._value.get() == initial + 1

    @pytest.mark.asyncio
    async def test_error_in_success_captures_exception(self, callback: MockCallback) -> None:
        callback.raise_on_success = True

        with patch("llm_gateway.callbacks.base.capture_exception") as mock_capture:
            await callback.async_log_success_event({}, None, 0.0, 1.0)

            mock_capture.assert_called_once()
            args = mock_capture.call_args
            assert isinstance(args[0][0], ValueError)
            assert args[0][1] == {"callback": "test", "event": "success"}

    @pytest.mark.asyncio
    async def test_error_in_failure_captures_exception(self, callback: MockCallback) -> None:
        callback.raise_on_failure = True

        with patch("llm_gateway.callbacks.base.capture_exception") as mock_capture:
            await callback.async_log_failure_event({}, None, 0.0, 1.0)

            mock_capture.assert_called_once()
            args = mock_capture.call_args
            assert isinstance(args[0][0], ValueError)
            assert args[0][1] == {"callback": "test", "event": "failure"}

    @pytest.mark.asyncio
    async def test_error_does_not_propagate(self, callback: MockCallback) -> None:
        callback.raise_on_success = True
        callback.raise_on_failure = True

        # Should not raise
        await callback.async_log_success_event({}, None, 0.0, 1.0)
        await callback.async_log_failure_event({}, None, 0.0, 1.0)

    @pytest.mark.asyncio
    async def test_kwargs_passed_to_on_success(self, callback: MockCallback) -> None:
        received_kwargs: dict[str, object] = {}

        async def capture_kwargs(self, kwargs, response_obj, start_time, end_time):
            received_kwargs.update(kwargs)

        test_kwargs = {"standard_logging_object": {"model": "test-model"}}

        with patch.object(MockCallback, "_on_success", capture_kwargs):
            await callback.async_log_success_event(test_kwargs, None, 0.0, 1.0)

        assert received_kwargs == test_kwargs
