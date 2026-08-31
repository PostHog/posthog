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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shipmail import (
    ShipmailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipmail.settings import SHIPMAIL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.shipmail.shipmail import (
    ShipmailResumeConfig,
    get_capabilities,
    shipmail_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ShipmailSource(ResumableSource[ShipmailSourceConfig, ShipmailResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://shipmail.to/docs/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHIPMAIL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SHIPMAIL,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Shipmail",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Shipmail API key to sync message analytics, mailboxes, domains, and suppressions into the PostHog Data warehouse.

Grant the key the read scopes for the tables you want to sync: `messages:read`, `mailboxes:read`, `domains:read`, and `suppressions:read`.""",
            iconPath="/static/services/shipmail.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Shipmail API key",
                        caption="Create a key in your [Shipmail API settings](https://shipmail.to/settings/api-keys).",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.shipmail.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://shipmail.to": "Your Shipmail API key is invalid or has been revoked. Create a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://shipmail.to": "Your Shipmail API key is missing the read scope required for this table.",
        }

    def get_schemas(
        self,
        config: ShipmailSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=bool(endpoint.incremental_fields),
                supports_append=bool(endpoint.incremental_fields),
                incremental_fields=endpoint.incremental_fields,
                detected_primary_keys=endpoint.primary_keys,
            )
            for name, endpoint in SHIPMAIL_ENDPOINTS.items()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: ShipmailSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        status, scopes = get_capabilities(config.api_key)
        if status == 200:
            if schema_name in SHIPMAIL_ENDPOINTS:
                required_scope = SHIPMAIL_ENDPOINTS[schema_name].required_scope
                if "*" not in scopes and required_scope not in scopes:
                    return False, f"Your Shipmail API key is missing the `{required_scope}` scope"
            return True, None
        if status == 401:
            return False, "Invalid Shipmail API key"
        if status == 403:
            return False, "Your Shipmail API key cannot access the capabilities endpoint"
        return False, "Could not validate Shipmail API key"

    def get_endpoint_permissions(
        self,
        config: ShipmailSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        status, scopes = get_capabilities(config.api_key)
        if status == 401:
            return dict.fromkeys(endpoints, "API key is invalid")
        if status != 200:
            return dict.fromkeys(endpoints)

        permissions: dict[str, str | None] = {}
        for endpoint in endpoints:
            endpoint_config = SHIPMAIL_ENDPOINTS.get(endpoint)
            if endpoint_config is None or "*" in scopes or endpoint_config.required_scope in scopes:
                permissions[endpoint] = None
            else:
                permissions[endpoint] = f"API key is missing the `{endpoint_config.required_scope}` scope"
        return permissions

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ShipmailResumeConfig]:
        return ResumableSourceManager[ShipmailResumeConfig](inputs, ShipmailResumeConfig)

    def source_for_pipeline(
        self,
        config: ShipmailSourceConfig,
        resumable_source_manager: ResumableSourceManager[ShipmailResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return shipmail_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
