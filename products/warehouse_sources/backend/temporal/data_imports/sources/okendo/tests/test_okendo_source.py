from base64 import b64encode

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.okendo import OkendoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.source import OkendoSource


class TestOkendoSource:
    def setup_method(self):
        self.source = OkendoSource()
        self.team_id = 123
        self.config = OkendoSourceConfig(user_id="user-1", api_key="key-1")

    @parameterized.expand(
        [
            ("other_vendor", "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers"),
        ]
    )
    def test_non_retryable_errors_do_not_match_unrelated(self, _name, other_error):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("valid", (True, 200), None, True, None),
            ("bad_key", (False, 401), None, False, "Invalid Okendo user ID or API key"),
            ("unreachable", (False, None), None, False, "Invalid Okendo user ID or API key"),
            # 403 at connect time is a real key without review access — the user may only want the
            # loyalty tables, so blocking source creation on it would lock them out.
            ("forbidden_at_connect", (False, 403), None, True, None),
            ("forbidden_for_schema", (False, 403), "reviews", False, "Your Okendo API key does not have access"),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        probe_result: tuple[bool, int | None],
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        status_code = probe_result[1]
        script = (
            [ScriptedResponse(status=status_code)]
            if status_code is not None
            else always(ConnectionError("probe unavailable"))
        )
        with scripted_network(script) as network:
            is_valid, error_message = self.source.validate_credentials(
                self.config, self.team_id, schema_name=schema_name
            )

        assert is_valid is expected_valid
        if expected_message is None:
            assert error_message is None
        else:
            assert error_message is not None and expected_message in error_message
        assert network.requests_log
        assert all(request.path == "/enterprise/reviews" for request in network.requests_log)
        assert all(request.param("limit") == "1" for request in network.requests_log)
        assert all(request.headers["okendo-api-version"] == "2025-02-01" for request in network.requests_log)
        expected_auth = "Basic " + b64encode(b"user-1:key-1").decode()
        assert all(request.headers["authorization"] == expected_auth for request in network.requests_log)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.okendo.source.okendo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_okendo_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "reviews"
        inputs.team_id = 7
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_okendo_source.call_args.kwargs
        assert kwargs["user_id"] == "user-1"
        assert kwargs["api_key"] == "key-1"
        assert kwargs["endpoint"] == "reviews"
        assert kwargs["resumable_source_manager"] is manager
        # An unpinned source must still send a version header, or every request is rejected.
        assert kwargs["api_version"] == "2025-02-01"
