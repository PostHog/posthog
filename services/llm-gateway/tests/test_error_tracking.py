from unittest.mock import MagicMock, patch

import pytest

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
