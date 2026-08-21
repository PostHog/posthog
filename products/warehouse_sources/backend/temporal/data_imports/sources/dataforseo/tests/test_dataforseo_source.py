from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.source import DataForSEOSource

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
    def test_backlinks_summary_is_off_by_default(self) -> None:
        # Backlinks requires a separate paid DataForSEO subscription, so it must not be part of
        # the default selection that one-shot setup enables.
        schemas = {s.name: s for s in DataForSEOSource().get_schemas(_make_config(), team_id=1)}
        assert schemas["backlinks_summary"].should_sync_default is False
        assert all(s.should_sync_default is True for name, s in schemas.items() if name != "backlinks_summary")

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
