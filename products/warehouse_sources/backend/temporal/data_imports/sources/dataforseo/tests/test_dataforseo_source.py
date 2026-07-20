from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.dataforseo import (
    DataForSEOResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.source import DataForSEOSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.source"


def _make_config(
    api_login: str = "login",
    api_password: str = "password",
    targets: str = "example.com, posthog.com",
    location_name: str | None = None,
    language_name: str | None = None,
) -> Any:
    config = MagicMock()
    config.api_login = api_login
    config.api_password = api_password
    config.targets = targets
    config.location_name = location_name
    config.language_name = language_name
    return config


class TestDataForSEOSource:
    def test_source_type(self) -> None:
        assert DataForSEOSource().source_type == ExternalDataSourceType.DATAFORSEO

    def test_source_config_fields(self) -> None:
        config = DataForSEOSource().get_source_config
        assert [f.name for f in config.fields] == [
            "api_login",
            "api_password",
            "targets",
            "location_name",
            "language_name",
        ]
        fields = {f.name: f for f in config.fields}
        password_field = fields["api_password"]
        assert isinstance(password_field, SourceFieldInputConfig)
        # The API password is a secret credential, so it must render as a password input.
        assert password_field.type == "password"
        assert password_field.secret is True
        assert password_field.required is True
        assert fields["api_login"].required is True
        assert fields["targets"].required is True
        # Location and language fall back to defaults in the transport when left blank.
        assert fields["location_name"].required is False
        assert fields["language_name"].required is False

    def test_source_config_is_released_alpha(self) -> None:
        config = DataForSEOSource().get_source_config
        assert config.releaseStatus == "alpha"
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/dataforseo"

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render tables.
        assert DataForSEOSource.lists_tables_without_credentials is True

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = DataForSEOSource().get_schemas(_make_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No DataForSEO live endpoint has a server-side updated-since filter.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    def test_get_schemas_exposes_primary_keys(self) -> None:
        schemas = {s.name: s for s in DataForSEOSource().get_schemas(_make_config(), team_id=1)}
        assert schemas["ranked_keywords"].detected_primary_keys == ["target", "keyword", "item_type", "rank_absolute"]
        assert schemas["historical_rank_overview"].detected_primary_keys == ["target", "year", "month"]
        assert schemas["competitors_domain"].detected_primary_keys == ["target", "domain"]

    def test_backlinks_summary_is_off_by_default(self) -> None:
        # Backlinks requires a separate paid DataForSEO subscription, so it must not be part of
        # the default selection that one-shot setup enables.
        schemas = {s.name: s for s in DataForSEOSource().get_schemas(_make_config(), team_id=1)}
        assert schemas["backlinks_summary"].should_sync_default is False
        assert all(s.should_sync_default is True for name, s in schemas.items() if name != "backlinks_summary")

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = DataForSEOSource().get_schemas(_make_config(), team_id=1, names=["ranked_keywords"])
        assert {s.name for s in schemas} == {"ranked_keywords"}

    @parameterized.expand(
        [
            ("valid", "example.com", True, True, None),
            ("invalid_credentials", "example.com", False, False, "Invalid DataForSEO API credentials"),
            ("no_targets", "  ", True, False, "Enter at least one target domain (e.g. example.com)"),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        targets: str,
        probe_result: bool,
        expected_ok: bool,
        expected_message: str | None,
    ) -> None:
        with patch(f"{MODULE}.validate_dataforseo_credentials", return_value=probe_result):
            ok, message = DataForSEOSource().validate_credentials(_make_config(targets=targets), team_id=1)
        assert ok is expected_ok
        assert message == expected_message

    def test_validate_credentials_skips_probe_without_targets(self) -> None:
        with patch(f"{MODULE}.validate_dataforseo_credentials") as probe:
            ok, _ = DataForSEOSource().validate_credentials(_make_config(targets=""), team_id=1)
        assert ok is False
        probe.assert_not_called()

    def test_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = DataForSEOSource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DataForSEOResumeConfig

    def test_source_for_pipeline_plumbs_config(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "ranked_keywords"
        inputs.logger = MagicMock()
        manager = MagicMock()
        config = _make_config(targets="https://www.Example.com/, posthog.com")
        with patch(f"{MODULE}.dataforseo_source") as source_fn:
            DataForSEOSource().source_for_pipeline(config, manager, inputs)
        kwargs = source_fn.call_args.kwargs
        assert kwargs["api_login"] == "login"
        assert kwargs["api_password"] == "password"
        # Targets are normalized (scheme/www stripped, lower-cased) before handing off.
        assert kwargs["targets"] == ["example.com", "posthog.com"]
        assert kwargs["endpoint"] == "ranked_keywords"
        assert kwargs["resumable_source_manager"] is manager

    @parameterized.expand(
        [
            ("defaults", None, None, "United States", "English"),
            ("blank_strings", "  ", "", "United States", "English"),
            ("custom", "United Kingdom", "German", "United Kingdom", "German"),
        ]
    )
    def test_source_for_pipeline_location_language_defaults(
        self,
        _name: str,
        location_name: str | None,
        language_name: str | None,
        expected_location: str,
        expected_language: str,
    ) -> None:
        inputs = MagicMock()
        inputs.schema_name = "domain_rank_overview"
        inputs.logger = MagicMock()
        config = _make_config(location_name=location_name, language_name=language_name)
        with patch(f"{MODULE}.dataforseo_source") as source_fn:
            DataForSEOSource().source_for_pipeline(config, MagicMock(), inputs)
        kwargs = source_fn.call_args.kwargs
        assert kwargs["location_name"] == expected_location
        assert kwargs["language_name"] == expected_language

    def test_source_for_pipeline_rejects_bad_targets(self) -> None:
        # A previously-saved bad config must fail the run instead of fanning out into a runaway sync.
        inputs = MagicMock()
        inputs.schema_name = "ranked_keywords"
        inputs.logger = MagicMock()
        oversized = _make_config(targets=",".join(f"site{i}.com" for i in range(26)))
        with patch(f"{MODULE}.dataforseo_source") as source_fn:
            with pytest.raises(ValueError, match="Too many target domains"):
                DataForSEOSource().source_for_pipeline(oversized, MagicMock(), inputs)
        source_fn.assert_not_called()

    @parameterized.expand(
        [
            ("http_401", "401 Client Error: Unauthorized for url: https://api.dataforseo.com"),
            ("http_402", "402 Client Error: Payment Required for url: https://api.dataforseo.com"),
            ("body_auth", "DataForSEO API error [40100]"),
            ("body_funds", "DataForSEO API error [40200]"),
            ("body_low_balance", "DataForSEO API error [40210]"),
            ("body_blocked", "DataForSEO API error [40201]"),
            ("body_daily_limit", "DataForSEO API error [40203]"),
        ]
    )
    def test_non_retryable_errors_cover_permanent_failures(self, _name: str, expected_key: str) -> None:
        errors = DataForSEOSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]

    def test_canonical_descriptions_keyed_by_endpoint(self) -> None:
        descriptions = DataForSEOSource().get_canonical_descriptions()
        # Every documented entry must map to a real endpoint or the docs render orphaned tables.
        assert set(descriptions.keys()) <= set(ENDPOINTS)
        assert "ranked_keywords" in descriptions
        assert "backlinks_summary" in descriptions
