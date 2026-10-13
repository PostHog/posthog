from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.oncehub import (
    OncehubSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.source import OncehubSource


class TestOncehubSource:
    def setup_method(self) -> None:
        self.source = OncehubSource()
        self.team_id = 123
        self.config = OncehubSourceConfig(api_key="oncehub-key")

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["bookings"])
        assert len(schemas) == 1
        assert schemas[0].name == "bookings"

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.oncehub.com/v2/bookings?limit=100",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.oncehub.com/v2/contacts?limit=100"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.oncehub.com/v2/bookings",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.oncehub.com/v2/contacts",
            ),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    def test_validate_credentials_delegates_with_api_key(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]) as network:
            result = self.source.validate_credentials(self.config, self.team_id)

        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["api-key"] == "oncehub-key"
        assert result == (False, "Invalid OnceHub API key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.source.oncehub_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bookings"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "oncehub-key"
        assert kwargs["endpoint"] == "bookings"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        result = SourceDriver(self.source, self.config).run("not_a_table", [])

        assert isinstance(result.raised, ValueError)
        assert str(result.raised) == "Unknown OnceHub schema 'not_a_table'"
