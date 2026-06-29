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
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.elasticemail import (
    ElasticEmailResumeConfig,
    elasticemail_source,
    validate_credentials as validate_elasticemail_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.settings import (
    ELASTICEMAIL_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ElasticemailSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ElasticemailSource(ResumableSource[ElasticemailSourceConfig, ElasticEmailResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ELASTICEMAIL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ELASTICEMAIL,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Elastic Email",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Elastic Email API key to pull your Elastic Email data into the PostHog Data warehouse.

You can create an API key in your [Elastic Email account settings](https://app.elasticemail.com/marketing/settings/new/manage-api).

Grant the key read access to the data you want to sync (Contacts, Campaigns, Templates, Reports, etc.).""",
            iconPath="/static/services/elasticemail.png",
            docsUrl="https://posthog.com/docs/cdp/sources/elasticemail",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Elastic Email rejects bad/expired/under-scoped keys with HTTP 400; `_fetch_page` raises an
            # ElasticEmailAuthError carrying this marker. Retrying can never fix a credential problem.
            "Elastic Email API authentication failed": "Your Elastic Email API key is invalid, expired, or missing the required read permissions. Create a new key in your Elastic Email account settings, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ElasticemailSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = ELASTICEMAIL_ENDPOINTS[endpoint]
            has_incremental_field = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                # Events are immutable, so they sync append-only via the server-side `from` filter. No
                # other list endpoint exposes a server-side timestamp filter, so they are full refresh only.
                supports_incremental=False,
                supports_append=has_incremental_field and endpoint_config.append_only,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ElasticemailSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # At source-create (schema_name=None) probe a cheap generic endpoint; for a specific schema, probe
        # that endpoint's path so we surface a per-endpoint permission problem early.
        if schema_name is not None and schema_name in ELASTICEMAIL_ENDPOINTS:
            endpoint_config = ELASTICEMAIL_ENDPOINTS[schema_name]
            valid = validate_elasticemail_credentials(
                config.api_key, endpoint_config.path, endpoint_config.extra_params
            )
        else:
            valid = validate_elasticemail_credentials(config.api_key)

        if valid:
            return True, None
        return False, "Invalid Elastic Email API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ElasticEmailResumeConfig]:
        return ResumableSourceManager[ElasticEmailResumeConfig](inputs, ElasticEmailResumeConfig)

    def source_for_pipeline(
        self,
        config: ElasticemailSourceConfig,
        resumable_source_manager: ResumableSourceManager[ElasticEmailResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return elasticemail_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
