from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.luma import LumaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.luma.source import LumaSource


class TestLumaSource:
    def setup_method(self) -> None:
        self.source = LumaSource()
        self.team_id = 123
        self.config = LumaSourceConfig(api_key="luma-key")

    @parameterized.expand(
        [
            ("rate_limited", "Luma API error (retryable): status=429, path=/public/v1/calendar/list-events"),
            ("server_error", "Luma API error (retryable): status=500, path=/public/v1/event/get-guests"),
        ]
    )
    def test_retryable_errors_match_exhausted_backoff(self, _name: str, observed_error: str) -> None:
        # `_fetch_page` already retries these in-process; once that budget exhausts, Temporal's own
        # activity retry recovers it, so it shouldn't reach error tracking as a tracked exception.
        retryable = self.source.get_retryable_errors()
        assert any(key in observed_error for key in retryable)

    def test_retryable_errors_ignore_unexpected_payload(self) -> None:
        # A malformed payload shape is a potential bug worth seeing in error tracking, not a
        # self-healing rate-limit/5xx condition.
        unrelated_error = "Luma returned an unexpected payload for /public/v1/calendar/list-events: list"
        retryable = self.source.get_retryable_errors()
        assert not any(key in unrelated_error for key in retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.luma.source.luma_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "luma-key"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager

    @parameterized.expand(
        [
            ("calendar_key_rejected", 403, "Requires a Luma organization API key"),
            ("calendar_key_bad_request", 400, "Requires a Luma organization API key"),
            ("organization_key", 200, None),
            ("transient_failure", 500, None),
        ]
    )
    def test_endpoint_permissions_probe_organization_endpoints(
        self, _name: str, status: int, expected_reason_prefix: str | None
    ) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.luma.source.check_access",
            return_value=(status, None),
        ) as mock_check:
            permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["calendars", "events"])

        mock_check.assert_called_once_with("luma-key", "/v1/organizations/calendars/list")
        assert permissions["events"] is None
        reason = permissions["calendars"]
        if expected_reason_prefix is None:
            assert reason is None
        else:
            assert reason is not None and reason.startswith(expected_reason_prefix)
