from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.propertyware import (
    PropertywareSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.propertyware import (
    PropertywareResumeConfig,
    endpoint_probe_path,
    propertyware_source,
    validate_credentials as validate_propertyware_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.settings import (
    ENDPOINT_PATHS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PRIMARY_KEY,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PropertywareSource(ResumableSource[PropertywareSourceConfig, PropertywareResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Propertyware uses a single major version with no version token in the URL or headers
    # (docs: "Propertyware uses only a major version nomenclature to manage changes").
    api_docs_url = "https://app.propertyware.com/apidocs/index.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PROPERTYWARE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PROPERTYWARE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Propertyware (RealPage)",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["property management", "rentals", "realpage"],
            caption="""Enter your Propertyware API credentials to sync property, lease, and accounting data into the PostHog Data warehouse.

Find your **client ID**, **client secret**, and **organization ID** in Propertyware under **Administration Setup > API Keys** (you'll need an administrator role to access this page). The client secret is shown only once when the key is created, so store it somewhere safe before closing the dialog.""",
            docsUrl="https://posthog.com/docs/cdp/sources/propertyware",
            iconPath="/static/services/propertyware.png",
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
                        name="system_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Propertyware authentication failed. Check your client ID, client secret, and organization ID.",
            "403 Client Error": "This Propertyware API key doesn't have permission to access this data. Check the key's access in Administration Setup > API Keys.",
        }

    def get_schemas(
        self,
        config: PropertywareSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)
        for schema in schemas:
            schema.detected_primary_keys = [PRIMARY_KEY]
        return schemas

    def validate_credentials(
        self,
        config: PropertywareSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # A key may legitimately be restricted to specific Propertyware entities, so validating a
        # chosen schema probes that endpoint directly rather than the account-wide `/health` check.
        path = endpoint_probe_path(schema_name) if schema_name in ENDPOINT_PATHS else "/health"
        status = validate_propertyware_credentials(config.client_id, config.client_secret, config.system_id, path)

        if status is not None and 200 <= status < 300:
            return True, None
        # Accept 403 at source-create (schema_name is None) — users may only grant a key access
        # to some entities — and only reject it when validating a specific schema.
        if status == 403 and schema_name is None:
            return True, None
        if status in (401, 403):
            return False, "Invalid Propertyware credentials, or this API key doesn't have access to this data."
        return False, "Could not validate Propertyware credentials."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PropertywareResumeConfig]:
        return ResumableSourceManager[PropertywareResumeConfig](inputs, PropertywareResumeConfig)

    def source_for_pipeline(
        self,
        config: PropertywareSourceConfig,
        resumable_source_manager: ResumableSourceManager[PropertywareResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return propertyware_source(
            client_id=config.client_id,
            client_secret=config.client_secret,
            system_id=config.system_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
