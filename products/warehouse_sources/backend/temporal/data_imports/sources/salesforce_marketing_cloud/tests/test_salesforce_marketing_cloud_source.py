from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.salesforcemarketingcloud import (
    SalesforceMarketingCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.salesforce_marketing_cloud import (
    AUTH_FAILURE_MESSAGE,
    SalesforceMarketingCloudResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.settings import (
    ENDPOINTS,
    SALESFORCE_MARKETING_CLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.source import (
    SalesforceMarketingCloudSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_TRANSPORT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.source"


def _config(account_id: str | None = None) -> SalesforceMarketingCloudSourceConfig:
    return SalesforceMarketingCloudSourceConfig(
        subdomain="tenant123", client_id="cid", client_secret="csecret", account_id=account_id
    )


def _inputs(schema_name: str = "open_events", **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestSalesforceMarketingCloudSource:
    def test_source_type(self) -> None:
        assert SalesforceMarketingCloudSource().source_type == ExternalDataSourceType.SALESFORCEMARKETINGCLOUD

    def test_source_config_is_released_as_alpha(self) -> None:
        config = SalesforceMarketingCloudSource().get_source_config

        assert config.name == SchemaExternalDataSourceType.SALESFORCE_MARKETING_CLOUD
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource

    def test_credential_fields_match_the_installed_package_flow(self) -> None:
        fields = SalesforceMarketingCloudSource().get_source_config.fields
        by_name = {f.name: f for f in fields if isinstance(f, SourceFieldInputConfig)}

        assert set(by_name) == {"subdomain", "client_id", "client_secret", "account_id"}
        assert by_name["client_secret"].type == SourceFieldInputConfigType.PASSWORD
        assert by_name["client_secret"].secret is True
        # The MID is only needed on multi-business-unit accounts.
        assert by_name["account_id"].required is False
        assert by_name["subdomain"].required is True

    def test_all_endpoints_are_discoverable(self) -> None:
        schemas = SalesforceMarketingCloudSource().get_schemas(_config(), team_id=1)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = SalesforceMarketingCloudSource().get_schemas(_config(), team_id=1, names=["open_events", "assets"])

        assert {schema.name for schema in schemas} == {"open_events", "assets"}

    @parameterized.expand(sorted(SALESFORCE_MARKETING_CLOUD_ENDPOINTS))
    def test_schema_incremental_support_matches_the_endpoint_catalog(self, endpoint: str) -> None:
        config = SALESFORCE_MARKETING_CLOUD_ENDPOINTS[endpoint]
        schema = next(
            s for s in SalesforceMarketingCloudSource().get_schemas(_config(), team_id=1) if s.name == endpoint
        )

        assert schema.supports_incremental is bool(config.incremental_fields)
        assert schema.incremental_fields == config.incremental_fields
        assert schema.detected_primary_keys == config.primary_keys

    def test_only_soap_endpoints_advertise_incremental(self) -> None:
        # The REST collections have no usable server-side timestamp filter, so they must stay full
        # refresh rather than paging everything and pretending to be incremental.
        schemas = {s.name: s for s in SalesforceMarketingCloudSource().get_schemas(_config(), team_id=1)}

        assert schemas["assets"].supports_incremental is False
        assert schemas["journeys"].supports_incremental is False
        assert schemas["campaigns"].supports_incremental is False
        assert schemas["open_events"].supports_incremental is True

    def test_tables_are_listed_for_public_docs(self) -> None:
        source = SalesforceMarketingCloudSource()

        assert source.lists_tables_without_credentials is True
        assert {table["name"] for table in source.get_documented_tables()} == set(ENDPOINTS)

    def test_every_endpoint_has_canonical_descriptions(self) -> None:
        descriptions = SalesforceMarketingCloudSource().get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)

    def test_permanent_auth_errors_stop_retrying(self) -> None:
        errors = SalesforceMarketingCloudSource().get_non_retryable_errors()

        assert AUTH_FAILURE_MESSAGE in errors
        assert "401 Client Error: Unauthorized" in errors
        assert "403 Client Error: Forbidden" in errors

    def test_validate_credentials_delegates_to_the_transport(self) -> None:
        with patch(f"{_TRANSPORT_MODULE}.validate_salesforce_marketing_cloud_credentials", return_value=(True, None)):
            assert SalesforceMarketingCloudSource().validate_credentials(_config("7654321"), team_id=1) == (True, None)

    def test_validate_credentials_surfaces_the_transport_error(self) -> None:
        with patch(
            f"{_TRANSPORT_MODULE}.validate_salesforce_marketing_cloud_credentials", return_value=(False, "nope")
        ) as mocked:
            ok, message = SalesforceMarketingCloudSource().validate_credentials(_config(), team_id=1)

        assert (ok, message) == (False, "nope")
        assert mocked.call_args.args == ("tenant123", "cid", "csecret", None)

    def test_resumable_manager_is_bound_to_the_resume_dataclass(self) -> None:
        manager = SalesforceMarketingCloudSource().get_resumable_source_manager(_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SalesforceMarketingCloudResumeConfig

    def test_source_for_pipeline_rejects_unknown_endpoints(self) -> None:
        manager: ResumableSourceManager[SalesforceMarketingCloudResumeConfig] = ResumableSourceManager(
            _inputs("nope"), SalesforceMarketingCloudResumeConfig
        )

        try:
            SalesforceMarketingCloudSource().source_for_pipeline(_config(), manager, _inputs("nope"))
        except ValueError as exc:
            assert "nope" in str(exc)
        else:
            raise AssertionError("expected a ValueError for an unknown endpoint")

    def test_source_for_pipeline_passes_credentials_and_incremental_state(self) -> None:
        manager: ResumableSourceManager[SalesforceMarketingCloudResumeConfig] = ResumableSourceManager(
            _inputs(), SalesforceMarketingCloudResumeConfig
        )
        inputs = _inputs(
            should_use_incremental_field=True,
            incremental_field="EventDate",
            db_incremental_field_last_value="2024-03-01T00:00:00",
        )

        with patch(f"{_TRANSPORT_MODULE}.salesforce_marketing_cloud_source") as mocked:
            SalesforceMarketingCloudSource().source_for_pipeline(_config("7654321"), manager, inputs)

        kwargs = mocked.call_args.kwargs
        assert kwargs["subdomain"] == "tenant123"
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "csecret"
        assert kwargs["account_id"] == "7654321"
        assert kwargs["endpoint"] == "open_events"
        assert kwargs["incremental_field"] == "EventDate"
        assert kwargs["db_incremental_field_last_value"] == "2024-03-01T00:00:00"

    def test_each_endpoint_gets_its_own_resume_slot(self) -> None:
        # SOAP continuation tokens and REST page numbers are different cursor shapes; a shared slot
        # would let a retry replay one endpoint's cursor against the other's API.
        manager: ResumableSourceManager[SalesforceMarketingCloudResumeConfig] = ResumableSourceManager(
            _inputs("assets"), SalesforceMarketingCloudResumeConfig
        )

        with patch(f"{_TRANSPORT_MODULE}.salesforce_marketing_cloud_source") as mocked:
            SalesforceMarketingCloudSource().source_for_pipeline(_config(), manager, _inputs("assets"))

        assert mocked.call_args.kwargs["resumable_source_manager"]._namespace == "assets"
