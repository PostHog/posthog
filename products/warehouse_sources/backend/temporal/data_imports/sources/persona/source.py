from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PersonaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.persona.persona import (
    PersonaResumeConfig,
    persona_source,
    validate_credentials as validate_persona_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.persona.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PERSONA_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PersonaSource(ResumableSource[PersonaSourceConfig, PersonaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PERSONA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PERSONA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Persona",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Persona API key to automatically pull your Persona data into the PostHog Data warehouse.

Create an API key in your Persona dashboard under **Settings → API Keys**. The key needs read access to the resources you want to sync (inquiries, accounts, cases, transactions, events).

Sandbox and production environments use separate API keys — use the one for the environment whose data you want to import.
""",
            iconPath="/static/services/persona.png",
            docsUrl="https://posthog.com/docs/cdp/sources/persona",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="persona_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.persona.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A revoked or invalid key surfaces as an HTTPError when `_fetch_page` raises for status.
            # Retrying can't fix a credential problem, so fail the sync. Match the stable status text
            # and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.withpersona.com": "Your Persona API key is invalid or has been revoked. Create a new API key in your Persona dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.withpersona.com": "Your Persona API key is missing the read permissions needed to sync this data. Grant the required access in your Persona dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: PersonaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = PERSONA_ENDPOINTS[endpoint]
            has_incremental = endpoint_config.supports_incremental and bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                # Events are an immutable audit log — append-only, never merged.
                supports_incremental=has_incremental and not endpoint_config.append_only,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PersonaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        status = validate_persona_credentials(config.api_key)
        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid Persona API key"
        # A 403 means the key is genuine but lacks a scope. At source-create (schema_name is None) we
        # accept it — the user may only intend to grant scopes for the tables they sync. Per-table
        # scope problems surface later as non-retryable sync errors.
        if status == 403:
            if schema_name is None:
                return True, None
            return False, "Your Persona API key is missing permissions for this resource"
        if status == 0:
            return False, "Could not reach Persona to validate your API key. Please try again."
        return False, f"Could not validate Persona credentials (HTTP {status})"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PersonaResumeConfig]:
        return ResumableSourceManager[PersonaResumeConfig](inputs, PersonaResumeConfig)

    def source_for_pipeline(
        self,
        config: PersonaSourceConfig,
        resumable_source_manager: ResumableSourceManager[PersonaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return persona_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
