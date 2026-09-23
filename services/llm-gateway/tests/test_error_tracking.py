from unittest.mock import MagicMock, patch

import pytest

import llm_gateway.observability.error_tracking as error_tracking_module
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.products.config import SIGNALS_DEV_APP_ID
from llm_gateway.request_context import RequestContext, auth_user_var, request_context_var


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
    @pytest.mark.parametrize("private_scout", [False, True])
    def test_uses_sdk_capture_exception(self, private_scout: bool) -> None:
        scopes = ["internal_run:read"]
        if private_scout:
            scopes.append("scout_experiment_internal:read")
        user_token = auth_user_var.set(
            AuthenticatedUser(
                user_id=1,
                team_id=1,
                auth_method="oauth_access_token",
                distinct_id="test-user",
                application_id=SIGNALS_DEV_APP_ID,
                sandbox_task_id="test-task",
                scopes=scopes,
            )
        )
        context_token = request_context_var.set(RequestContext(request_id="test-request", product="signals"))
        with (
            patch.object(error_tracking_module, "get_settings", return_value=_make_settings()),
            patch.object(error_tracking_module, "posthoganalytics") as mock_ph,
        ):
            try:
                error_tracking_module.capture_exception(ValueError("test"))
            finally:
                auth_user_var.reset(user_token)
                request_context_var.reset(context_token)

            assert mock_ph.capture_exception.call_count == (0 if private_scout else 1)
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
