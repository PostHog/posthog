import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.crossref.source import CrossrefSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crossref import (
    CrossrefSourceConfig,
)


class TestCrossrefSource:
    def setup_method(self):
        self.source = CrossrefSource()
        self.team_id = 123
        self.config = CrossrefSourceConfig()

    @parameterized.expand(
        [
            ("member_scoped", "301", None, None, True),
            ("funder_scoped", None, "100000001", None, True),
            ("issn_scoped", None, None, "1932-6203", True),
            ("unscoped", None, None, None, False),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crossref.source.validate_crossref_credentials"
    )
    def test_validate_credentials_works_requires_scope(
        self, _name, member_id, funder_id, issn, expected_valid, mock_validate
    ):
        mock_validate.return_value = True
        config = CrossrefSourceConfig(member_id=member_id, funder_id=funder_id, issn=issn)

        is_valid, message = self.source.validate_credentials(config, self.team_id, schema_name="Works")

        assert is_valid is expected_valid
        if not expected_valid:
            assert "member ID, funder ID, or journal ISSN" in (message or "")

    @pytest.mark.parametrize("schema_name", [None, "Members", "Funders", "Types", "Licenses"])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crossref.source.validate_crossref_credentials"
    )
    def test_validate_credentials_unscoped_endpoints_ignore_scope(self, mock_validate, schema_name):
        mock_validate.return_value = True

        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is True
        assert message is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crossref.source.validate_crossref_credentials"
    )
    def test_validate_credentials_unreachable_api(self, mock_validate):
        mock_validate.return_value = False

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message == "Couldn't reach the Crossref API. Please try again."

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crossref.source.validate_crossref_credentials"
    )
    def test_validate_credentials_passes_mailto(self, mock_validate):
        mock_validate.return_value = True
        config = CrossrefSourceConfig(mailto="me@example.com")

        self.source.validate_credentials(config, self.team_id)

        mock_validate.assert_called_once_with("me@example.com")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://api.crossref.org/works?filter=member:abc (Integer specified as abc but must be a positive integer. )",
        ],
    )
    def test_non_retryable_errors_match_invalid_scope(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.crossref.org/works",
            "500 Server Error: Internal Server Error for url: https://api.crossref.org/works",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.crossref.source.crossref_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_crossref_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Works"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00"
        inputs.incremental_field = "indexed_date"
        manager = mock.MagicMock()
        config = CrossrefSourceConfig(mailto="me@example.com", member_id="301")

        self.source.source_for_pipeline(config, manager, inputs)

        mock_crossref_source.assert_called_once()
        kwargs = mock_crossref_source.call_args.kwargs
        assert kwargs["endpoint"] == "Works"
        assert kwargs["mailto"] == "me@example.com"
        assert kwargs["member_id"] == "301"
        assert kwargs["funder_id"] is None
        assert kwargs["issn"] is None
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00"
        assert kwargs["incremental_field"] == "indexed_date"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.crossref.source.crossref_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_crossref_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Members"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_crossref_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.crossref.source.crossref_source")
    def test_source_for_pipeline_rejects_unscoped_works_even_if_stored_config_lost_its_scope(
        self, mock_crossref_source
    ):
        # Setup-time validation can't stop a scope from being cleared after Works is already
        # enabled, so source_for_pipeline must re-check it on every run before an unscoped sync
        # of the full 160M+ row Works registry can happen.
        inputs = mock.MagicMock()
        inputs.schema_name = "Works"
        config = CrossrefSourceConfig()  # no member_id/funder_id/issn

        with pytest.raises(ValueError, match="Set a member ID, funder ID, or journal ISSN"):
            self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        mock_crossref_source.assert_not_called()
