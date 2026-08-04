from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.flutterwave import (
    FlutterwaveResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.source import FlutterwaveSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.source.flutterwave_source"
)


def _source_inputs(**overrides: Any) -> MagicMock:
    inputs = MagicMock()
    inputs.schema_name = overrides.get("schema_name", "transactions")
    inputs.team_id = overrides.get("team_id", 1)
    inputs.job_id = overrides.get("job_id", "job-1")
    inputs.api_version = overrides.get("api_version", None)
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", True)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", "2024-01-15 00:00:00")
    return inputs


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert FlutterwaveSource().source_type == ExternalDataSourceType.FLUTTERWAVE

    def test_config_identity_and_release_contract(self) -> None:
        config = FlutterwaveSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.FLUTTERWAVE
        # Alpha but released: the finished source must be reachable, so unreleasedSource stays off.
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        # The doc slug is derived from this URL; a mismatch 404s the docs page.
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/flutterwave"

    def test_secret_key_is_a_required_secret_field(self) -> None:
        fields = FlutterwaveSource().get_source_config.fields
        secret_fields = [f for f in fields if isinstance(f, SourceFieldInputConfig) and f.name == "secret_key"]
        assert len(secret_fields) == 1
        field = secret_fields[0]
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_pins_the_generally_available_api_version(self) -> None:
        # The request layer builds its base URL from this pin, so a drift here silently retargets
        # every customer's sync at a different API surface.
        source = FlutterwaveSource()
        assert source.supported_versions == ("v3",)
        assert source.default_version == "v3"
        assert source.resolve_api_version(None) == "v3"


class TestGetSchemas:
    @parameterized.expand(
        [
            # Only endpoints with a real server-side `from`/`to` filter can sync incrementally.
            ("transactions", True),
            ("settlements", True),
            ("refunds", True),
            ("transfers", True),
            ("chargebacks", True),
            ("payment_plans", True),
            ("subscriptions", False),
            ("subaccounts", False),
            ("beneficiaries", False),
        ]
    )
    def test_incremental_support_per_endpoint(self, endpoint: str, expected_incremental: bool) -> None:
        schemas = {s.name: s for s in FlutterwaveSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas[endpoint].supports_incremental is expected_incremental
        assert schemas[endpoint].supports_append is expected_incremental

    def test_incremental_endpoints_advertise_created_at(self) -> None:
        schemas = {s.name: s for s in FlutterwaveSource().get_schemas(MagicMock(), team_id=1)}
        assert [f["field"] for f in schemas["transactions"].incremental_fields] == ["created_at"]

    def test_names_filter(self) -> None:
        schemas = FlutterwaveSource().get_schemas(MagicMock(), team_id=1, names=["refunds"])
        assert [s.name for s in schemas] == ["refunds"]


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.flutterwave.com/v3/transactions?page=1",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.flutterwave.com/v3/settlements"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        assert any(key in observed for key in FlutterwaveSource().get_non_retryable_errors())

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.flutterwave.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.flutterwave.com/v3/transactions",
            ),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.flutterwave.com/v3/transfers"),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, observed: str) -> None:
        assert not any(key in observed for key in FlutterwaveSource().get_non_retryable_errors())


class TestSourceForPipeline:
    def test_passes_credentials_endpoint_and_watermark(self) -> None:
        with patch(SOURCE_MODULE_PATCH) as mock_source:
            FlutterwaveSource().source_for_pipeline(
                config=MagicMock(secret_key="FLWSECK-test"),
                resumable_source_manager=MagicMock(),
                inputs=_source_inputs(schema_name="transactions", should_use_incremental_field=True),
            )
        kwargs = mock_source.call_args.kwargs
        assert kwargs["secret_key"] == "FLWSECK-test"
        assert kwargs["endpoint"] == "transactions"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-15 00:00:00"
        # An unset pin must resolve to default_version, not fall through as None and break the URL.
        assert kwargs["api_version"] == "v3"

    def test_watermark_dropped_on_full_refresh(self) -> None:
        # On a full-refresh run the stored watermark must not leak into the query, or an unwanted
        # `from` filter would silently truncate the pull.
        with patch(SOURCE_MODULE_PATCH) as mock_source:
            FlutterwaveSource().source_for_pipeline(
                config=MagicMock(secret_key="FLWSECK-test"),
                resumable_source_manager=MagicMock(),
                inputs=_source_inputs(schema_name="subaccounts", should_use_incremental_field=False),
            )
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None


class TestValidateCredentials:
    @parameterized.expand([("valid", (True, None), True), ("invalid", (False, "nope"), False)])
    def test_delegates_to_the_transport_probe(
        self, _name: str, probe_result: tuple[bool, str | None], expected: bool
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.source.validate_flutterwave_credentials",
            return_value=probe_result,
        ) as probe:
            valid, _message = FlutterwaveSource().validate_credentials(MagicMock(secret_key="FLWSECK-test"), team_id=1)
        assert valid is expected
        assert probe.call_args.args == ("FLWSECK-test", "v3")


class TestResumableManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        manager = FlutterwaveSource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FlutterwaveResumeConfig


class TestDocumentedTables:
    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O), so the public docs Supported tables section renders.
        source = FlutterwaveSource()
        assert source.lists_tables_without_credentials is True
        assert {t["name"] for t in source.get_documented_tables()} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(FlutterwaveSource().get_canonical_descriptions().keys()) == set(ENDPOINTS)
