import pytest
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
                "responses_401",
                "401 Client Error: Unauthorized for url: https://us1.apis.zonkafeedback.com/responses?page=1&page_size=100",
            ),
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

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://us1.apis.zonkafeedback.com/responses",
            ),
            ("read_timeout", "HTTPSConnectionPool(host='us1.apis.zonkafeedback.com', port=443): Read timed out."),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://e.apis.zonkafeedback.com/surveys"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            ("reachable", 200, True, None),
            ("unauthorized", 401, False, "Invalid Zonka Feedback auth token"),
            ("forbidden", 403, False, "Invalid Zonka Feedback auth token"),
            ("server_error", 500, False, "Zonka Feedback returned HTTP 500"),
            ("connection_error", 0, False, "Could not connect to Zonka Feedback: boom"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.source.check_access")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_check: mock.MagicMock,
    ) -> None:
        message = (
            "Zonka Feedback returned HTTP 500"
            if status == 500
            else ("Could not connect to Zonka Feedback: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

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

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Zonka Feedback schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
