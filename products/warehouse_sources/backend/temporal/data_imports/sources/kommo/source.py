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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kommo import KommoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.kommo import (
    KommoResumeConfig,
    kommo_source,
    normalize_subdomain,
    validate_credentials as validate_kommo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.settings import (
    ENDPOINT_CONFIG,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SUBDOMAIN_ERROR = (
    "Enter just the subdomain of your Kommo account, for example mycompany for https://mycompany.kommo.com"
)


@SourceRegistry.register
class KommoSource(ResumableSource[KommoSourceConfig, KommoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v4",)
    default_version = "v4"
    api_docs_url = "https://developers.kommo.com/reference/kommo-api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KOMMO

    @property
    def connection_host_fields(self) -> list[str]:
        # `subdomain` picks the host the access token is sent to, so retargeting it must
        # re-require the token instead of reusing the stored one.
        return ["subdomain"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Kommo rejected the access token. Generate a new long-lived token and reconnect.",
            "403 Client Error: Forbidden for url": "This Kommo token cannot access the requested data. Check the integration's scopes and the token owner's user rights.",
            "402 Client Error: Payment Required for url": "This Kommo account is not paid up, so its API is unavailable.",
            "404 Client Error: Not Found for url": "No Kommo account found at this subdomain. Check the account subdomain and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: KommoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: KommoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        subdomain = normalize_subdomain(config.subdomain)
        if subdomain is None:
            return False, SUBDOMAIN_ERROR

        return validate_kommo_credentials(config.api_key, subdomain)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KommoResumeConfig]:
        return ResumableSourceManager[KommoResumeConfig](inputs, KommoResumeConfig)

    def source_for_pipeline(
        self,
        config: KommoSourceConfig,
        resumable_source_manager: ResumableSourceManager[KommoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        subdomain = normalize_subdomain(config.subdomain)
        if subdomain is None:
            raise ValueError(SUBDOMAIN_ERROR)

        endpoint = ENDPOINT_CONFIG[inputs.schema_name]
        should_use_incremental_field = inputs.should_use_incremental_field and endpoint.incremental_param is not None

        resource = kommo_source(
            api_key=config.api_key,
            subdomain=subdomain,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if should_use_incremental_field
            else None,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=endpoint.primary_key,
            column_hints=resource.column_hints,
            # Incremental endpoints are requested with `order[updated_at]=asc`, the same order
            # the watermark advances in.
            sort_mode="asc",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KOMMO,
            category=DataWarehouseSourceCategory.CRM,
            label="Kommo",
            caption=(
                "In Kommo, go to Settings > Integrations and create a private integration, then open "
                "**Keys and scopes** and generate a long-lived token. The token inherits the rights of "
                "the user who created it, so create it as an admin if you want to sync users and "
                "account-wide lists."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/kommo",
            iconPath="/static/services/kommo.png",
            keywords=["amocrm", "crm"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Account subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mycompany",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Long-lived access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
