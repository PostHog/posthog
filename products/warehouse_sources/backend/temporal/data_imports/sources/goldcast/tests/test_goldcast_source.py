from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.settings import (
    ENDPOINTS,
    GOLDCAST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.source import GoldcastSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(access_key: str = "tok") -> Any:
    config = MagicMock()
    config.access_key = access_key
    return config


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert GoldcastSource().source_type == ExternalDataSourceType.GOLDCAST

    def test_config_is_alpha_and_unreleased(self) -> None:
        config = GoldcastSource().get_source_config
        # The task ships Goldcast behind unreleasedSource=True at alpha while it's still unproven.
        assert config.unreleasedSource is True
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/goldcast"

    def test_single_secret_token_field(self) -> None:
        fields = {f.name: f for f in GoldcastSource().get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"access_key"}
        assert fields["access_key"].required is True
        # The token is a credential, so it must be stored as a secret password field.
        assert fields["access_key"].secret is True


class TestGetSchemas:
    def test_lists_every_endpoint_as_full_refresh(self) -> None:
        schemas = GoldcastSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Goldcast exposes no server-side timestamp filter, so nothing is incremental/append.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_detected_primary_keys_match_settings(self) -> None:
        schemas = {s.name: s for s in GoldcastSource().get_schemas(_config(), team_id=1)}
        for name, config in GOLDCAST_ENDPOINTS.items():
            assert schemas[name].detected_primary_keys == config.primary_keys

    def test_names_filter_restricts_output(self) -> None:
        schemas = GoldcastSource().get_schemas(_config(), team_id=1, names=["events", "webinars"])
        assert {s.name for s in schemas} == {"events", "webinars"}


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://customapi.goldcast.io/event/",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://customapi.goldcast.io/core/organization/",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = GoldcastSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='customapi.goldcast.io', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://customapi.goldcast.io/event/"),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = GoldcastSource().get_non_retryable_errors()
        assert not any(key in observed_error for key in non_retryable)


class TestValidateCredentials:
    def test_valid_token_passes(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.source.validate_goldcast_credentials",
            return_value=True,
        ):
            assert GoldcastSource().validate_credentials(_config(), team_id=1) == (True, None)

    def test_invalid_token_surfaces_message(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.source.validate_goldcast_credentials",
            return_value=False,
        ):
            valid, message = GoldcastSource().validate_credentials(_config(), team_id=1)
        assert valid is False
        assert message == "Invalid Goldcast API token"


class TestSourceForPipeline:
    def test_plumbs_access_key_and_endpoint_through(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "webinars"
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.source.goldcast_source"
        ) as mock_source:
            GoldcastSource().source_for_pipeline(_config(access_key="secret"), inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["access_key"] == "secret"
        assert kwargs["endpoint"] == "webinars"


class TestDocumentedTables:
    def test_static_catalog_is_published_for_public_docs(self) -> None:
        source = GoldcastSource()
        # A static, no-I/O catalog opts into public docs so the Supported tables section renders.
        assert source.lists_tables_without_credentials is True
        tables = source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        # Full refresh must be advertised for every endpoint (no server-side cursor).
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    def test_canonical_descriptions_key_on_endpoint_names(self) -> None:
        # Canonical descriptions must key on schema/endpoint names so enrichment applies them.
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))
