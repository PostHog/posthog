import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import ExternalDataSourceType as SchemaExternalDataSourceType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pylon import PylonSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon import source as pylon_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.pylon import (
    PYLON_EU_BASE_URL,
    PYLON_US_BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.source import PylonSource


def _config(api_token: str = "token") -> PylonSourceConfig:
    return PylonSourceConfig.from_dict({"api_token": api_token})


class TestPylonSourceConfig:
    def test_get_source_config_basics(self) -> None:
        config = PylonSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.PYLON
        assert config.label == "Pylon"
        # A finished-but-new source ships visible (no unreleasedSource) and labelled alpha.
        assert config.unreleasedSource is None
        assert config.releaseStatus == "alpha"


class TestPylonGetSchemas:
    def test_returns_all_endpoints(self) -> None:
        schemas = PylonSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_issues_supports_incremental(self) -> None:
        schemas = PylonSource().get_schemas(_config(), team_id=1)
        incremental = {s.name for s in schemas if s.supports_incremental}
        assert incremental == {"issues"}

    def test_filters_by_names(self) -> None:
        schemas = PylonSource().get_schemas(_config(), team_id=1, names=["issues", "accounts"])
        assert {s.name for s in schemas} == {"issues", "accounts"}

    def test_issues_advertises_created_at_incremental_field(self) -> None:
        schemas = PylonSource().get_schemas(_config(), team_id=1, names=["issues"])
        fields = schemas[0].incremental_fields
        assert [f["field"] for f in fields] == ["created_at"]


class TestPylonValidateCredentials:
    def test_valid_token(self) -> None:
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon_source_module, "validate_pylon_credentials", lambda token: True)
            assert PylonSource().validate_credentials(_config(), team_id=1) == (True, None)

    @parameterized.expand(
        [
            ("eu_token", "pylon_api_eu_abc123", PYLON_EU_BASE_URL),
            ("us_token", "pylon_api_abc123", PYLON_US_BASE_URL),
        ]
    )
    def test_failure_names_the_host_that_was_checked(self, _name: str, api_token: str, expected_host: str) -> None:
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon_source_module, "validate_pylon_credentials", lambda token: False)
            ok, message = PylonSource().validate_credentials(_config(api_token), team_id=1)
        assert ok is False
        assert message is not None
        assert expected_host in message


class TestPylonNonRetryableErrors:
    @parameterized.expand([("us", PYLON_US_BASE_URL), ("eu", PYLON_EU_BASE_URL)])
    def test_covers_both_regional_hosts(self, _name: str, base_url: str) -> None:
        errors = PylonSource().get_non_retryable_errors()
        assert f"401 Client Error: Unauthorized for url: {base_url}" in errors
        assert f"403 Client Error: Forbidden for url: {base_url}" in errors


class TestPylonSourceForPipeline:
    def test_plumbs_args_into_pylon_source(self) -> None:
        captured: dict = {}

        def _fake_pylon_source(**kwargs: object):
            captured.update(kwargs)
            return MagicMock()

        inputs = MagicMock()
        inputs.schema_name = "issues"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-06-01T00:00:00Z"
        inputs.incremental_field = "created_at"
        manager = MagicMock()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon_source_module, "pylon_source", _fake_pylon_source)
            PylonSource().source_for_pipeline(_config("secret"), manager, inputs)

        assert captured["api_token"] == "secret"
        assert captured["endpoint"] == "issues"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-06-01T00:00:00Z"
        assert captured["resumable_source_manager"] is manager

    def test_passes_none_last_value_when_not_incremental(self) -> None:
        captured: dict = {}

        def _fake_pylon_source(**kwargs: object):
            captured.update(kwargs)
            return MagicMock()

        inputs = MagicMock()
        inputs.schema_name = "accounts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon_source_module, "pylon_source", _fake_pylon_source)
            PylonSource().source_for_pipeline(_config(), MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
