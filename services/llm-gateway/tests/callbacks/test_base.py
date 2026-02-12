from unittest.mock import patch

import pytest

from llm_gateway.auth.models import AuthenticatedUser
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
        self.received_end_user_id: str | None = None

    async def _on_success(self, kwargs, response_obj, start_time, end_time, end_user_id) -> None:
        if self.raise_on_success:
            raise ValueError("Test error in success")
        self.on_success_called = True
        self.received_end_user_id = end_user_id

    async def _on_failure(self, kwargs, response_obj, start_time, end_time, end_user_id) -> None:
        if self.raise_on_failure:
            raise ValueError("Test error in failure")
        self.on_failure_called = True
        self.received_end_user_id = end_user_id


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

        async def capture_kwargs(self, kwargs, response_obj, start_time, end_time, end_user_id):
            received_kwargs.update(kwargs)

        test_kwargs = {"standard_logging_object": {"model": "test-model"}}

        with patch.object(MockCallback, "_on_success", capture_kwargs):
            await callback.async_log_success_event(test_kwargs, None, 0.0, 1.0)

        assert received_kwargs == test_kwargs


class TestExtractEndUserId:
    @pytest.fixture
    def callback(self) -> InstrumentedCallback:
        return MockCallback()

    @pytest.fixture
    def oauth_user(self) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=123,
            team_id=456,
            auth_method="oauth_access_token",
            distinct_id="user-distinct-id-123",
        )

    @pytest.fixture
    def api_key_user(self) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=123,
            team_id=456,
            auth_method="personal_api_key",
            distinct_id="user-distinct-id-123",
        )

    def test_oauth_returns_user_id(self, callback: InstrumentedCallback, oauth_user: AuthenticatedUser) -> None:
        with patch("llm_gateway.callbacks.base.get_auth_user", return_value=oauth_user):
            result = callback._extract_end_user_id({})
        assert result == "123"

    def test_oauth_ignores_end_user_in_request(
        self, callback: InstrumentedCallback, oauth_user: AuthenticatedUser
    ) -> None:
        kwargs = {"standard_logging_object": {"end_user": "request-user"}}
        with patch("llm_gateway.callbacks.base.get_auth_user", return_value=oauth_user):
            result = callback._extract_end_user_id(kwargs)
        assert result == "123"

    def test_api_key_uses_end_user_from_request(
        self, callback: InstrumentedCallback, api_key_user: AuthenticatedUser
    ) -> None:
        kwargs = {"standard_logging_object": {"end_user": "request-user"}}
        with patch("llm_gateway.callbacks.base.get_auth_user", return_value=api_key_user):
            result = callback._extract_end_user_id(kwargs)
        assert result == "request-user"

    def test_api_key_falls_back_to_metadata_user_id(
        self, callback: InstrumentedCallback, api_key_user: AuthenticatedUser
    ) -> None:
        kwargs = {"litellm_params": {"metadata": {"user_id": "anthropic-user"}}}
        with patch("llm_gateway.callbacks.base.get_auth_user", return_value=api_key_user):
            result = callback._extract_end_user_id(kwargs)
        assert result == "anthropic-user"

    def test_api_key_prefers_end_user_over_metadata(
        self, callback: InstrumentedCallback, api_key_user: AuthenticatedUser
    ) -> None:
        kwargs = {
            "standard_logging_object": {"end_user": "openai-user"},
            "litellm_params": {"metadata": {"user_id": "anthropic-user"}},
        }
        with patch("llm_gateway.callbacks.base.get_auth_user", return_value=api_key_user):
            result = callback._extract_end_user_id(kwargs)
        assert result == "openai-user"

    def test_api_key_returns_none_without_end_user(
        self, callback: InstrumentedCallback, api_key_user: AuthenticatedUser
    ) -> None:
        with patch("llm_gateway.callbacks.base.get_auth_user", return_value=api_key_user):
            result = callback._extract_end_user_id({})
        assert result is None

    def test_no_auth_user_uses_end_user(self, callback: InstrumentedCallback) -> None:
        kwargs = {"standard_logging_object": {"end_user": "request-user"}}
        with patch("llm_gateway.callbacks.base.get_auth_user", return_value=None):
            result = callback._extract_end_user_id(kwargs)
        assert result == "request-user"

    def test_no_auth_user_returns_none_without_end_user(self, callback: InstrumentedCallback) -> None:
        with patch("llm_gateway.callbacks.base.get_auth_user", return_value=None):
            result = callback._extract_end_user_id({})
        assert result is None
