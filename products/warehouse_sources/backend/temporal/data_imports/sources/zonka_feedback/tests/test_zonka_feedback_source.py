from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zonkafeedback import (
    ZonkaFeedbackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.source import ZonkaFeedbackSource


class TestZonkaFeedbackSource:
    def setup_method(self) -> None:
        self.source = ZonkaFeedbackSource()
        self.team_id = 123
        self.config = ZonkaFeedbackSourceConfig(auth_token="zonka-token", data_center="us1")

    @parameterized.expand(
        [
            (
                "surveys_403",
                "403 Client Error: Forbidden for url: https://e.apis.zonkafeedback.com/surveys?page=2&page_size=100",
            ),
            (
                "contacts_401",
                "401 Client Error: Unauthorized for url: https://in.apis.zonkafeedback.com/contacts?page=1&page_size=100",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.source.zonka_feedback_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "responses"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["auth_token"] == "zonka-token"
        assert kwargs["data_center"] == "us1"
        assert kwargs["endpoint"] == "responses"
        assert kwargs["resumable_source_manager"] is manager
