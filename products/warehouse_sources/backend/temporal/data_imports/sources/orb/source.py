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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OrbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.orb import (
    OrbResumeConfig,
    orb_source,
    validate_credentials as validate_orb_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OrbSource(ResumableSource[OrbSourceConfig, OrbResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ORB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ORB,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Orb",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Orb API key to automatically pull your Orb billing data into the PostHog Data warehouse.

You can create an API key in your [Orb account settings](https://app.withorb.com/settings). A read-only key is sufficient.""",
            iconPath="/static/services/orb.png",
            docsUrl="https://posthog.com/docs/cdp/sources/orb",
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
            unreleasedSource=True,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked key surfaces as an HTTPError when the REST client calls
            # raise_for_status(). Retrying can never satisfy a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://api.withorb.com": "Your Orb API key is invalid or has been revoked. Create a new API key in your Orb account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.withorb.com": "Your Orb API key does not have permission to read this data. Check the key's permissions in your Orb account settings, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.orb.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OrbSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=endpoint in INCREMENTAL_FIELDS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: OrbSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_orb_credentials(config.api_key):
            return True, None

        return False, "Invalid Orb API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OrbResumeConfig]:
        return ResumableSourceManager[OrbResumeConfig](inputs, OrbResumeConfig)

    def source_for_pipeline(
        self,
        config: OrbSourceConfig,
        resumable_source_manager: ResumableSourceManager[OrbResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return orb_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
