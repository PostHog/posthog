import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zonkafeedback import (
    ZonkaFeedbackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.source import ZonkaFeedbackSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.zonka_feedback import (
    ZONKA_API_VERSION_V1,
    ZONKA_API_VERSION_V2_1,
)


class TestZonkaFeedbackSource:
    def setup_method(self) -> None:
        self.source = ZonkaFeedbackSource()
        self.team_id = 123
        self.config = ZonkaFeedbackSourceConfig(auth_token="zonka-token", data_center="us1")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Zonka Feedback"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/zonka-feedback"

        input_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        select_names = [f.name for f in config.fields if isinstance(f, SourceFieldSelectConfig)]
        assert input_names == ["auth_token"]
        assert select_names == ["data_center"]

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

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.source.check_access")
    def test_validate_credentials_probes_the_auth_token(self, mock_check: mock.MagicMock) -> None:
        # The auth token is account-wide, so validation probes the token, not a per-schema scope.
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="surveys")
        mock_check.assert_called_once_with("zonka-token", "us1")

    def test_version_declaration_defaults_to_v2_1(self) -> None:
        # New/unpinned sources must resolve to v2.1; an existing pin is honored verbatim so sources
        # pinned to v1 keep syncing against the version they were created on.
        assert self.source.supported_versions == (ZONKA_API_VERSION_V1, ZONKA_API_VERSION_V2_1)
        assert self.source.default_version == ZONKA_API_VERSION_V2_1
        assert self.source.resolve_api_version(None) == ZONKA_API_VERSION_V2_1
        assert self.source.resolve_api_version(ZONKA_API_VERSION_V1) == ZONKA_API_VERSION_V1

    def test_v1_is_deprecated_without_sunset_and_v2_1_is_not(self) -> None:
        # Zonka published no sunset date for its older API generation, so the legacy v1 label is
        # flagged deprecated with sunset_at=None; the default v2.1 must never be deprecated.
        deprecation = self.source.get_version_deprecation(ZONKA_API_VERSION_V1)
        assert deprecation is not None
        assert deprecation.sunset_at is None
        assert self.source.get_version_deprecation(ZONKA_API_VERSION_V2_1) is None

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
