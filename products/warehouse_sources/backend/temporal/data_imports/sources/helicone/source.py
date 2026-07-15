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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HeliconeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.helicone import (
    HeliconeResumeConfig,
    helicone_source,
    validate_credentials as validate_helicone_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.settings import (
    HELICONE_ENDPOINTS,
    REQUESTS_DEFAULT_LOOKBACK_DAYS,
    REQUESTS_ENDPOINT,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HeliconeSource(ResumableSource[HeliconeSourceConfig, HeliconeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HELICONE

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` picks the host the stored API key is sent to. Retargeting it must re-require the
        # secret so a preserved key can't be aimed at a different regional endpoint without re-entry.
        return ["region"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HELICONE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Helicone",
            caption=(
                "Connect Helicone to sync your logged LLM requests, sessions, per-user usage, and prompts "
                "into the PostHog Data warehouse.\n\n"
                "Generate an API key in your [Helicone dashboard](https://us.helicone.ai/settings/api-keys) "
                "(Settings → API Keys). Pick the region that matches where your Helicone organization lives."
            ),
            iconPath="/static/services/helicone.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/helicone",
            keywords=["llm", "observability", "ai gateway", "helicone"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk-helicone-...",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.helicone.ai)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (eu.api.helicone.ai)", value="eu"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        invalid_key_message = (
            "Your Helicone API key is invalid or has been revoked, or the selected region doesn't match your "
            "Helicone organization. Generate a new key in your Helicone dashboard (Settings → API Keys) and "
            "reconnect."
        )
        # A bad key surfaces as a requests HTTPError when the transport calls raise_for_status().
        # Match the stable status text and both regional hosts, not the per-request path.
        return {
            "401 Client Error: Unauthorized for url: https://api.helicone.ai": invalid_key_message,
            "401 Client Error: Unauthorized for url: https://eu.api.helicone.ai": invalid_key_message,
            "403 Client Error: Forbidden for url: https://api.helicone.ai": invalid_key_message,
            "403 Client Error: Forbidden for url: https://eu.api.helicone.ai": invalid_key_message,
        }

    def get_schemas(
        self,
        config: HeliconeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == REQUESTS_ENDPOINT:
                return f"Only syncs the last {REQUESTS_DEFAULT_LOOKBACK_DAYS} days on initial incremental sync"
            return None

        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=endpoint.supports_incremental,
                supports_append=endpoint.supports_append,
                incremental_fields=endpoint.incremental_fields,
                description=_description(endpoint.name),
            )
            for endpoint in HELICONE_ENDPOINTS.values()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: HeliconeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_helicone_credentials(config.api_key, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HeliconeResumeConfig]:
        return ResumableSourceManager[HeliconeResumeConfig](inputs, HeliconeResumeConfig)

    def source_for_pipeline(
        self,
        config: HeliconeSourceConfig,
        resumable_source_manager: ResumableSourceManager[HeliconeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return helicone_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
