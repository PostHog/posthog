from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.dataforseo import MAX_KEYWORDS
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.source import DataForSEOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dataforseo import (
    DataForSEOSourceConfig,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.source"


def _make_config(
    api_login: str = "login",
    api_password: str = "password",
    targets: str = "example.com, posthog.com",
    keywords: str | None = None,
    location_name: str | None = None,
    language_name: str | None = None,
) -> Any:
    config = MagicMock()
    config.api_login = api_login
    config.api_password = api_password
    config.targets = targets
    config.keywords = keywords
    config.location_name = location_name
    config.language_name = language_name
    return config


def _driver(
    targets: str = "example.com, posthog.com",
    keywords: str | None = None,
    location_name: str | None = None,
    language_name: str | None = None,
) -> SourceDriver:
    return SourceDriver(
        DataForSEOSource(),
        DataForSEOSourceConfig(
            api_login="login",
            api_password="password",
            targets=targets,
            keywords=keywords,
            location_name=location_name,
            language_name=language_name,
        ),
    )


class TestDataForSEOSource:
    def test_connection_host_fields_cover_every_spend_field(self) -> None:
        # targets and keywords both select what the stored credential spends paid requests on,
        # so changing either must force re-entry of the secret.
        assert DataForSEOSource().connection_host_fields == ["targets", "keywords"]

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render tables.
        assert DataForSEOSource.lists_tables_without_credentials is True

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

    def test_validate_credentials_rejects_too_many_keywords(self) -> None:
        # The SERP table spends a request per keyword per sync, so an oversized list is reported
        # at setup rather than on the first bill.
        config = _make_config(keywords=",".join(f"kw{i}" for i in range(MAX_KEYWORDS + 1)))
        with patch(f"{MODULE}.validate_dataforseo_credentials", return_value=True) as probe:
            ok, message = DataForSEOSource().validate_credentials(config, team_id=1)
        assert ok is False
        assert message is not None
        assert str(MAX_KEYWORDS) in message
        probe.assert_not_called()

    def test_source_for_pipeline_plumbs_config(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "ranked_keywords"
        inputs.logger = MagicMock()
        manager = MagicMock()
        config = _make_config(
            targets="https://www.Example.com/, posthog.com",
            keywords="Product   Analytics, product analytics",
        )
        with patch(f"{MODULE}.dataforseo_source") as source_fn:
            DataForSEOSource().source_for_pipeline(config, manager, inputs)
        kwargs = source_fn.call_args.kwargs
        assert kwargs["api_login"] == "login"
        assert kwargs["api_password"] == "password"
        # Targets and keywords are normalized (scheme/www stripped, lower-cased, de-duplicated)
        # before handing off.
        assert kwargs["targets"] == ["example.com", "posthog.com"]
        assert kwargs["keywords"] == ["product analytics"]
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
        result = _driver(location_name=location_name, language_name=language_name).run(
            "domain_rank_overview", [ScriptedResponse(json={"tasks": []}) for _ in range(2)]
        )
        assert result.raised is None
        payload = result.requests[0].json()[0]
        assert payload["location_name"] == expected_location
        assert payload["language_name"] == expected_language

    def test_source_for_pipeline_rejects_bad_targets(self) -> None:
        # A previously-saved bad config must fail the run instead of fanning out into a runaway sync.
        result = _driver(targets=",".join(f"site{i}.com" for i in range(26))).run("ranked_keywords", [])
        assert isinstance(result.raised, ValueError)
        assert "Too many target domains" in str(result.raised)
        assert result.requests == []

    @parameterized.expand([("historical_search_volume",), ("serp_organic",)])
    def test_source_for_pipeline_rejects_keyword_table_without_keywords(self, schema_name: str) -> None:
        # A keyword-scoped table has nothing to request without keywords, so it must fail with a
        # message naming the fix rather than syncing an empty table.
        result = _driver(keywords=" , ").run(schema_name, [])
        assert isinstance(result.raised, ValueError)
        assert "Add at least one keyword" in str(result.raised)
        assert result.requests == []
        assert error_message_matches(str(result.raised), DataForSEOSource().get_non_retryable_errors().keys())

    def test_source_for_pipeline_allows_missing_keywords_for_target_tables(self) -> None:
        # Only the keyword-scoped tables need keywords; a domain table must still sync without them.
        inputs = MagicMock()
        inputs.schema_name = "ranked_keywords"
        inputs.logger = MagicMock()
        with patch(f"{MODULE}.dataforseo_source") as source_fn:
            DataForSEOSource().source_for_pipeline(_make_config(keywords=None), MagicMock(), inputs)
        assert source_fn.call_args.kwargs["keywords"] == []

    @parameterized.expand(
        [
            ("http_402", "402 Client Error: Payment Required for url: https://api.dataforseo.com"),
            ("body_auth", "DataForSEO API error [40100]"),
            ("body_funds", "DataForSEO API error [40200]"),
            ("body_low_balance", "DataForSEO API error [40210]"),
            ("body_blocked", "DataForSEO API error [40201]"),
            ("body_daily_limit", "DataForSEO API error [40203]"),
            ("body_invalid_language", "Invalid Field: 'language_name'"),
        ]
    )
    def test_non_retryable_errors_cover_permanent_failures(self, _name: str, expected_key: str) -> None:
        errors = DataForSEOSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]

    @parameterized.expand(
        [
            ("http_status", "DataForSEO API error (retryable): status=500, url=https://api.dataforseo.com/v3/x"),
            ("body_rate_limit", "DataForSEO API error (retryable) [40202]: rate limit exceeded"),
            ("body_server_error", "DataForSEO API error (retryable) [50000]: internal error"),
        ]
    )
    def test_transient_api_errors_are_retryable(self, _name: str, error_msg: str) -> None:
        # `_post_task` already exhausted its own tenacity retry before this reaches us, so it
        # must stay retryable (and out of the non-retryable set), so that a self-recovering
        # blip is retried by Temporal instead of reported as an unclassified error.
        source = DataForSEOSource()
        assert error_message_matches(error_msg, source.get_retryable_errors())
        assert not error_message_matches(error_msg, source.get_non_retryable_errors().keys())
