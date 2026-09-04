from unittest.mock import MagicMock, patch

import httpx
import pytest
from litellm.exceptions import AuthenticationError

import llm_gateway.observability.error_tracking as error_tracking_module


@pytest.fixture(autouse=True)
def _reset_initialized():
    error_tracking_module._initialized = False
    yield
    error_tracking_module._initialized = False


def _make_settings(**overrides):
    settings = MagicMock()
    settings.posthog_project_token = overrides.get("posthog_project_token", "test-token")
    return settings


class _ProviderError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str | None = None,
        error_type: str | None = None,
        response: httpx.Response | None = None,
    ) -> None:
        super().__init__("provider rejected the request")
        self.status_code = status_code
        self.code = code
        self.type = error_type
        self.response = response


def _capture_properties(error: Exception, additional_properties: dict) -> dict:
    with (
        patch.object(error_tracking_module, "get_settings", return_value=_make_settings()),
        patch.object(error_tracking_module, "posthoganalytics") as mock_ph,
    ):
        error_tracking_module.capture_exception(error, additional_properties=additional_properties)
        return mock_ph.capture_exception.call_args[1]["properties"]


def _fingerprint(error: Exception, provider: str) -> str:
    return _capture_properties(error, {"provider": provider})["$exception_fingerprint"]


def _litellm_authentication_error(provider: str, code: str) -> AuthenticationError:
    response = httpx.Response(
        401,
        request=httpx.Request("GET", "https://example.com/v1/models"),
        json={"error": {"code": code}},
    )
    return AuthenticationError(
        "provider rejected the request",
        llm_provider=provider,
        model="test-model",
        response=response,
    )


class TestCaptureException:
    def test_uses_sdk_capture_exception(self):
        with (
            patch.object(error_tracking_module, "get_settings", return_value=_make_settings()),
            patch.object(error_tracking_module, "posthoganalytics") as mock_ph,
        ):
            error = ValueError("test")
            error_tracking_module.capture_exception(error)

            mock_ph.capture_exception.assert_called_once()
            mock_ph.capture.assert_not_called()

    @pytest.mark.parametrize(
        "first,second",
        [
            (
                (_ProviderError(400, code="unsupported_value"), "openai"),
                (_ProviderError(401, code="invalid_organization"), "openai"),
            ),
            (
                (_ProviderError(429, code="rate_limit_exceeded"), "openai"),
                (_ProviderError(429, code="rate_limit_exceeded"), "anthropic"),
            ),
        ],
    )
    def test_separates_provider_errors_that_share_a_stack(self, first, second):
        assert _fingerprint(*first) != _fingerprint(*second)

    def test_uses_litellm_upstream_provider(self) -> None:
        openai_error = _litellm_authentication_error("openai", "invalid_api_key")
        openrouter_error = _litellm_authentication_error("openrouter", "invalid_api_key")

        assert _fingerprint(openai_error, "openai") != _fingerprint(openrouter_error, "openai")
        assert ":openrouter:" in _fingerprint(openrouter_error, "openai")

    @pytest.mark.parametrize("backend", ["baseten", "cloudflare", "modal"])
    def test_names_the_gateway_backend_behind_the_openai_prefix(self, backend: str) -> None:
        error = _litellm_authentication_error("openai", "invalid_api_key")

        assert f":{backend}:" in _fingerprint(error, backend)
        assert _fingerprint(error, backend) != _fingerprint(error, "openai")

    def test_keeps_one_failure_in_one_issue_across_models(self):
        error = _ProviderError(401, code="invalid_organization")

        gpt_5_mini = _capture_properties(error, {"provider": "openai", "model": "gpt-5-mini"})
        gpt_5 = _capture_properties(error, {"provider": "openai", "model": "gpt-5"})

        assert gpt_5_mini["$exception_fingerprint"] == gpt_5["$exception_fingerprint"]

    @pytest.mark.parametrize(
        "error,expected",
        [
            (_ProviderError(400, code="unsupported_value"), ":400:unsupported_value"),
            (_ProviderError(400, error_type="invalid_request_error"), ":400:invalid_request_error"),
            (
                _litellm_authentication_error("openai", "invalid_organization"),
                ":401:invalid_organization",
            ),
            (_ProviderError(500), ":500:unknown"),
        ],
    )
    def test_reads_the_code_wherever_litellm_leaves_it(self, error, expected):
        assert _fingerprint(error, "openai").endswith(expected)

    def test_buckets_unrecognized_provider_codes(self) -> None:
        first = _ProviderError(400, code="request-1")
        second = _ProviderError(400, code="request-2")

        assert _fingerprint(first, "openai") == _fingerprint(second, "openai")
        assert _fingerprint(first, "openai").endswith(":unknown")

    @pytest.mark.parametrize(
        "error,properties",
        [
            (ValueError("test"), {"provider": "openai"}),
            (_ProviderError(500), {"callback": "posthog", "event": "failure"}),
        ],
    )
    def test_leaves_grouping_alone_for_a_failure_outside_a_provider_call(self, error, properties):
        assert "$exception_fingerprint" not in _capture_properties(error, properties)

    def test_passes_properties(self):
        with (
            patch.object(error_tracking_module, "get_settings", return_value=_make_settings()),
            patch.object(error_tracking_module, "posthoganalytics") as mock_ph,
        ):
            error = ValueError("test")
            error_tracking_module.capture_exception(error, additional_properties={"key": "value"})

            call_kwargs = mock_ph.capture_exception.call_args
            assert call_kwargs[1]["properties"] == {"key": "value"}

    def test_preserves_distinct_id(self):
        with (
            patch.object(error_tracking_module, "get_settings", return_value=_make_settings()),
            patch.object(error_tracking_module, "posthoganalytics") as mock_ph,
        ):
            error_tracking_module.capture_exception(ValueError("test"))

            call_kwargs = mock_ph.capture_exception.call_args
            assert call_kwargs[1]["distinct_id"] == "llm-gateway-service"

    def test_skips_when_not_initialized(self):
        with (
            patch.object(
                error_tracking_module, "get_settings", return_value=_make_settings(posthog_project_token=None)
            ),
            patch.object(error_tracking_module, "posthoganalytics") as mock_ph,
        ):
            error_tracking_module.capture_exception(ValueError("test"))

            mock_ph.capture_exception.assert_not_called()
            mock_ph.capture.assert_not_called()
