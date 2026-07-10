import re
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import VitallySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vitally.settings import (
    CUSTOM_OBJECT_SCHEMA_PREFIX,
    ENDPOINTS as VITALLY_ENDPOINTS,
    INCREMENTAL_FIELDS as VITALLY_INCREMENTAL_FIELDS,
    UPDATED_AT_INCREMENTAL_FIELD,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.vitally.vitally import (
    list_custom_object_definitions,
    validate_credentials as validate_vitally_credentials,
    vitally_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VitallySource(SimpleSource[VitallySourceConfig]):
    api_docs_url = "https://docs.vitally.io"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VITALLY

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.vitally.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: VitallySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas: list[SourceSchema] = [
            SourceSchema(
                name=endpoint,
                supports_incremental=VITALLY_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=VITALLY_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=VITALLY_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in VITALLY_ENDPOINTS
        ]

        # Discover custom objects and expose one schema per object so users can sync the
        # underlying records. The static `Custom_Objects` endpoint only returns the
        # definitions; instances live at `/resources/customObjects/:id/instances`.
        # Skip the outbound request when the caller only wants static schemas, and never
        # let a discovery failure take down the static endpoints that need no network call.
        # The credential-free documentation catalog calls this with a placeholder config whose
        # `region` is an empty string rather than a `VitallyRegionConfig`; without a token there
        # is nothing to discover, so bail out before touching `config.region`.
        wants_custom_objects = names is None or any(name.startswith(CUSTOM_OBJECT_SCHEMA_PREFIX) for name in names)
        if wants_custom_objects and config.secret_token:
            try:
                definitions = list_custom_object_definitions(
                    config.secret_token, config.region.selection, config.region.subdomain
                )
            except Exception as e:
                # A 401/403 here is a customer credential problem (invalid/revoked token), not a bug
                # we can fix — the per-schema sync path already surfaces it and disables the source.
                # Skip capturing those to avoid spamming error tracking on every discovery run, but
                # still capture genuinely unexpected discovery failures.
                if not any(pattern in str(e) for pattern in self.get_non_retryable_errors()):
                    capture_exception(e)
                definitions = []

            for definition in definitions:
                machine_name = definition.get("name")
                if not machine_name:
                    continue
                schema_name = f"{CUSTOM_OBJECT_SCHEMA_PREFIX}{machine_name}"
                if schema_name in VITALLY_ENDPOINTS:
                    continue
                schemas.append(
                    SourceSchema(
                        name=schema_name,
                        label=definition.get("label") or machine_name,
                        supports_incremental=True,
                        supports_append=True,
                        incremental_fields=[UPDATED_AT_INCREMENTAL_FIELD],
                    )
                )

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: VitallySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        subdomain_regex = re.compile("^[a-zA-Z-]+$")
        if config.region.selection == "US" and not subdomain_regex.match(config.region.subdomain):
            return False, "Vitally subdomain is incorrect"

        if validate_vitally_credentials(config.secret_token, config.region.selection, config.region.subdomain):
            return True, None

        return False, "Invalid credentials"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The Vitally host is per-customer on US (`<subdomain>.rest.vitally.io`), so match on the
        # stable status text rather than a fixed URL prefix.
        return {
            "401 Client Error: Unauthorized for url": "Your Vitally secret token is invalid or has been revoked. Please check your token and reconnect.",
            "403 Client Error: Forbidden for url": "Your Vitally secret token does not have permission to access this data. Please check the token's permissions and reconnect.",
        }

    def source_for_pipeline(self, config: VitallySourceConfig, inputs: SourceInputs) -> SourceResponse:
        items = vitally_source(
            secret_token=config.secret_token,
            region=config.region.selection,
            subdomain=config.region.subdomain,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            logger=inputs.logger,
        )

        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: items,
            primary_keys=["id"],
            partition_count=1,  # this enables partitioning
            partition_size=1,  # this enables partitioning
            partition_mode="datetime",
            partition_format="week",
            partition_keys=["created_at"],
            sort_mode="desc" if inputs.schema_name == "Messages" else "asc",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.VITALLY,
            category=DataWarehouseSourceCategory.CRM,
            iconPath="/static/services/vitally.png",
            docsUrl="https://posthog.com/docs/cdp/sources/vitally",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="secret_token",
                        label="Secret token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_live_...",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Vitally region",
                        required=True,
                        defaultValue="EU",
                        options=[
                            SourceFieldSelectConfigOption(label="EU", value="EU"),
                            SourceFieldSelectConfigOption(
                                label="US",
                                value="US",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="subdomain",
                                            label="Vitally subdomain",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="",
                                            secret=False,
                                        )
                                    ],
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        )
