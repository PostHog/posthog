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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OpenFDASourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.openfda import (
    OpenFDAResumeConfig,
    openfda_source,
    validate_credentials as validate_openfda_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OPENFDA_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpenFDASource(ResumableSource[OpenFDASourceConfig, OpenFDAResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENFDA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPEN_FDA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="openFDA",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Pull U.S. FDA drug, device, and food data — adverse event reports, recalls, drug labeling, 510(k) clearances, and the NDC directory — into the PostHog Data warehouse.

An API key is optional but recommended. Without one, openFDA limits you to 1,000 requests/day per IP; with one, 120,000 requests/day. Get a free key from the [openFDA API basics page](https://open.fda.gov/apis/authentication/).""",
            iconPath="/static/services/openfda.png",
            docsUrl="https://posthog.com/docs/cdp/sources/openfda",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key (optional)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="Your openFDA API key",
                        secret=True,
                    ),
                ],
            ),
            keywords=["fda", "openfda", "drug", "device", "food"],
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # openFDA returns 401/403 only for an invalid or over-quota API key. Retrying can't satisfy
            # a credential/quota problem, so stop the sync. Match the stable status text and base host.
            "401 Client Error: Unauthorized for url: https://api.fda.gov": "Your openFDA API key is invalid. Generate a new key from the openFDA developer portal and reconnect, or remove it to use the unauthenticated tier.",
            "403 Client Error: Forbidden for url: https://api.fda.gov": "Your openFDA API key is invalid or has exceeded its daily request quota. Check the key, wait for the quota to reset, then reconnect.",
        }

    def get_schemas(
        self,
        config: OpenFDASourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = OPENFDA_ENDPOINTS[endpoint]
            has_incremental = endpoint_config.incremental_field is not None
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                detected_primary_keys=endpoint_config.primary_keys,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: OpenFDASourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_openfda_credentials(config.api_key):
            return True, None

        return False, "Could not reach the openFDA API. Check your API key (if provided) and try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OpenFDAResumeConfig]:
        return ResumableSourceManager[OpenFDAResumeConfig](inputs, OpenFDAResumeConfig)

    def source_for_pipeline(
        self,
        config: OpenFDASourceConfig,
        resumable_source_manager: ResumableSourceManager[OpenFDAResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return openfda_source(
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
