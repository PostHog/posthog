from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.source import EmailOctopusSource


def _config() -> Any:
    config = MagicMock()
    config.api_key = "eo_key"
    return config


class TestEmailOctopusGetSchemas:
    @parameterized.expand(
        [
            ("lists", False),
            ("campaigns", False),
            ("contacts", True),
            ("campaign_reports", False),
            ("campaign_report_summaries", False),
            ("campaign_report_links", False),
            ("list_tags", False),
        ]
    )
    def test_incremental_support(self, endpoint: str, supports_incremental: bool) -> None:
        schemas = {s.name: s for s in EmailOctopusSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].supports_incremental is supports_incremental

    def test_names_filter(self) -> None:
        schemas = EmailOctopusSource().get_schemas(_config(), team_id=1, names=["contacts"])
        assert [s.name for s in schemas] == ["contacts"]


class TestEmailOctopusValidateCredentials:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_validate(self, _name: str, is_valid: bool) -> None:
        with patch.object(source_module, "validate_emailoctopus_credentials", return_value=is_valid):
            ok, message = EmailOctopusSource().validate_credentials(_config(), team_id=1)
        assert ok is is_valid
        assert (message is None) is is_valid


class TestEmailOctopusNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.emailoctopus.com/lists?limit=1"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.emailoctopus.com/campaigns"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = EmailOctopusSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.emailoctopus.com/lists"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.emailoctopus.com/lists"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = EmailOctopusSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestEmailOctopusResumableAndPipeline:
    def _inputs(self, schema_name: str) -> SourceInputs:
        return SourceInputs(
            schema_name=schema_name,
            schema_id="schema-1",
            source_id="source-1",
            team_id=1,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            incremental_field=None,
            incremental_field_type=None,
            job_id="job-1",
            logger=MagicMock(),
            reset_pipeline=False,
        )

    def test_source_for_pipeline_plumbs_endpoint(self) -> None:
        inputs = self._inputs("contacts")
        manager = EmailOctopusSource().get_resumable_source_manager(inputs)
        response = EmailOctopusSource().source_for_pipeline(_config(), manager, inputs)
        assert response.name == "contacts"
        assert response.primary_keys == ["list_id", "id"]


class TestEmailOctopusSourceVersions:
    @parameterized.expand([("v1",), ("v2",)])
    def test_existing_pin_is_honored(self, version: str) -> None:
        # Pinned rows — including the legacy "v1" default existing sources carry — keep their
        # version after the default bump, so their syncs are unaffected.
        source = EmailOctopusSource()
        assert version in source.supported_versions
        assert source.resolve_api_version(version) == version
