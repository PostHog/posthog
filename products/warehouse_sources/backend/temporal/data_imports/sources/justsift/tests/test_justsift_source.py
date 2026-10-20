from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.justsift import (
    JustSiftSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.source import JustSiftSource


class TestJustSiftSource:
    def setup_method(self) -> None:
        self.source = JustSiftSource()
        self.team_id = 123
        self.config = JustSiftSourceConfig(api_key="sift-token")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.justsift.com/v1/search/people?page=1&pageSize=100",),
            ("403 Client Error: Forbidden for url: https://api.justsift.com/v1/fields?page=1&pageSize=100",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.justsift.com/v1/search/people",),
            ("HTTPSConnectionPool(host='api.justsift.com', port=443): Read timed out.",),
            ("429 Client Error: Too Many Requests for url: https://api.justsift.com/v1/fields",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            (200, True, None),
        ]
    )
    def test_validate_credentials(
        self,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        answer = ConnectionError("boom") if status == 0 else ScriptedResponse(status=status)
        with scripted_network(always(answer)) as network:
            is_valid, returned = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert returned == expected_message
        assert {request.path for request in network.requests_log} == {"/v1/search/people"}

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.justsift.source.justsift_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_justsift_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "people"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_justsift_source.assert_called_once()
        kwargs = mock_justsift_source.call_args.kwargs
        assert kwargs["api_key"] == "sift-token"
        assert kwargs["endpoint"] == "people"
        assert kwargs["resumable_source_manager"] is manager
