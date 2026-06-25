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
from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools import (
    CommercetoolsResumeConfig,
    commercetools_source,
    validate_credentials as validate_commercetools_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CommercetoolsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CommercetoolsSource(ResumableSource[CommercetoolsSourceConfig, CommercetoolsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COMMERCETOOLS

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` picks the host and `project_key` the project the stored client secret (and
        # minted bearer token) are sent to; retargeting either must re-require the secret so it
        # can't be aimed at a different commercetools project or region.
        return ["region", "project_key"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://auth.": "commercetools authentication failed. Please check your client ID and client secret.",
            "400 Client Error: Bad Request for url: https://auth.": "commercetools authentication failed. Please check your client ID and client secret.",
            "403 Client Error: Forbidden for url: https://api.": "commercetools denied access. Please check that your API client has the required view scope for this dataset.",
            "404 Client Error: Not Found for url: https://api.": "commercetools project not found. Please check your project key and region.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COMMERCETOOLS,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="commercetools",
            caption="""Enter your commercetools API client credentials to pull your commerce data into the PostHog Data warehouse.

Create an API client in the Merchant Center under Settings > Developer settings with the view scopes for the datasets you want to sync (`view_orders`, `view_customers`, `view_payments`, `view_products`, `view_categories`, `view_discount_codes`). Your project key and region are shown alongside the generated credentials.""",
            iconPath="/static/services/commercetools.png",
            docsUrl="https://posthog.com/docs/cdp/sources/commercetools",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us-central1.gcp",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="North America (GCP, us-central1)", value="us-central1.gcp"
                            ),
                            SourceFieldSelectConfigOption(
                                label="North America (AWS, us-east-2)", value="us-east-2.aws"
                            ),
                            SourceFieldSelectConfigOption(label="Europe (GCP, europe-west1)", value="europe-west1.gcp"),
                            SourceFieldSelectConfigOption(label="Europe (AWS, eu-central-1)", value="eu-central-1.aws"),
                            SourceFieldSelectConfigOption(
                                label="Australia (GCP, australia-southeast1)", value="australia-southeast1.gcp"
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="project_key",
                        label="Project key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-project",
                        secret=False,
                    ),
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
                ],
            ),
        )

    def get_schemas(
        self,
        config: CommercetoolsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CommercetoolsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_commercetools_credentials(
            config.region, config.project_key, config.client_id, config.client_secret
        ):
            return True, None

        return False, "Invalid commercetools API client credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CommercetoolsResumeConfig]:
        return ResumableSourceManager[CommercetoolsResumeConfig](inputs, CommercetoolsResumeConfig)

    def source_for_pipeline(
        self,
        config: CommercetoolsSourceConfig,
        resumable_source_manager: ResumableSourceManager[CommercetoolsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return commercetools_source(
            region=config.region,
            project_key=config.project_key,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
