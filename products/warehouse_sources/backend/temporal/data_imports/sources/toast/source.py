from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.toast import ToastSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.toast.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MERGE_ONLY_ENDPOINTS,
    TOAST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.toast.toast import (
    TOAST_LOGIN_FAILED_MESSAGE,
    ToastResumeConfig,
    toast_source,
    validate_credentials as validate_toast_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ToastSource(ResumableSource[ToastSourceConfig, ToastResumeConfig]):
    # Toast versions each of its APIs separately (`/orders/v2`, `/labor/v1`, `/config/v2`), so there
    # is no single version token a source instance could pin.
    api_docs_url = "https://doc.toasttab.com/doc/devguide/index.html"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TOAST

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        errors: dict[str, str | None] = {
            TOAST_LOGIN_FAILED_MESSAGE: "Toast accepted the login request but returned no access token. Check that your API client is a machine client with API access enabled.",
        }
        for host in ("https://ws-api.toasttab.com", "https://ws-sandbox-api.toasttab.com"):
            errors[f"401 Client Error: Unauthorized for url: {host}"] = (
                "Toast rejected your credentials. Check the client ID and secret, and that your API client can access every restaurant GUID you listed."
            )
            errors[f"403 Client Error: Forbidden for url: {host}"] = (
                "Toast denied access. Check that your API client has the scopes for this dataset and that the restaurant has approved your integration."
            )
        return errors

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TOAST,
            category=DataWarehouseSourceCategory.SALES,
            label="Toast",
            keywords=["pos", "restaurant", "toasttab"],
            caption="""Pull your Toast POS orders, labor, and cash management data into the PostHog Data warehouse.

Toast issues API credentials through its integration program. Once your API client is approved, enter its client ID and secret, then add the GUID of every restaurant you want to sync — the credential has to be authorized for each one. Orders and labor tables sync incrementally on their last-modified date.""",
            iconPath="/static/services/toast.png",
            docsUrl="https://posthog.com/docs/cdp/sources/toast",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="restaurant_guids",
                        label="Restaurant GUIDs",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="One GUID per line, or comma separated",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date (historical backfill)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="YYYY-MM-DD",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.toast.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ToastSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=MERGE_ONLY_ENDPOINTS)
        for schema in schemas:
            endpoint = TOAST_ENDPOINTS[schema.name]
            schema.detected_primary_keys = list(endpoint.primary_key)
            schema.default_incremental_lookback_seconds = endpoint.default_incremental_lookback_seconds
        return schemas

    def validate_credentials(
        self,
        config: ToastSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_toast_credentials(
            config.environment,
            config.client_id,
            config.client_secret,
            config.restaurant_guids,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ToastResumeConfig]:
        return ResumableSourceManager[ToastResumeConfig](inputs, ToastResumeConfig)

    def source_for_pipeline(
        self,
        config: ToastSourceConfig,
        resumable_source_manager: ResumableSourceManager[ToastResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return toast_source(
            environment=config.environment,
            client_id=config.client_id,
            client_secret=config.client_secret,
            restaurant_guids=config.restaurant_guids,
            start_date=config.start_date,
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
