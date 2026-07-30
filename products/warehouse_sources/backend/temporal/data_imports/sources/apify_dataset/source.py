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
from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.apify_dataset import (
    ApifyResumeConfig,
    apify_dataset_source,
    validate_credentials as validate_apify_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ApifyDatasetSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ApifyDatasetSource(ResumableSource[ApifyDatasetSourceConfig, ApifyResumeConfig]):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.apify.com/api/v2"

    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to render
    # in the public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APIFYDATASET

    @property
    def connection_host_fields(self) -> list[str]:
        # dataset_id selects which Apify dataset the stored token reads from; changing it must
        # require re-entering the secret so a preserved token can't be retargeted at another dataset.
        return ["dataset_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APIFY_DATASET,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Apify Dataset",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Apify API token and the ID of the dataset you want to import into the PostHog Data warehouse.

You can create an API token in your [Apify account settings](https://console.apify.com/settings/integrations), and find a dataset ID in the [Apify Console](https://console.apify.com/storage/datasets) (or use the `username~dataset-name` shorthand).

The token needs read access to the dataset's storage.""",
            iconPath="/static/services/apify_dataset.png",
            docsUrl="https://posthog.com/docs/cdp/sources/apify-dataset",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="apify_api_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="dataset_id",
                        label="Dataset ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="WkzbQMuFYuamGv3YF",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad/expired token or a token without access to the dataset surfaces as a requests
            # HTTPError when `_fetch_page` calls `raise_for_status()`. Retrying can't fix a credential
            # or addressing problem, so stop the sync. Match the stable status text + base host.
            "401 Client Error: Unauthorized for url: https://api.apify.com": "Your Apify API token is invalid or has expired. Create a new token in your Apify account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.apify.com": "Your Apify API token cannot access this dataset. Use a token with read access to the dataset's storage, then reconnect.",
            "404 Client Error: Not Found for url: https://api.apify.com": "The Apify dataset could not be found. Check that the dataset ID is correct and the token can access it.",
        }

    def get_schemas(
        self,
        config: ApifyDatasetSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=PRIMARY_KEYS.get(endpoint),
                description="The rows produced by the Apify dataset. Columns are defined by the Actor that produced them. Full refresh only — the whole dataset is re-imported on every sync.",
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ApifyDatasetSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_apify_credentials(config.api_token, config.dataset_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ApifyResumeConfig]:
        return ResumableSourceManager[ApifyResumeConfig](inputs, ApifyResumeConfig)

    def source_for_pipeline(
        self,
        config: ApifyDatasetSourceConfig,
        resumable_source_manager: ResumableSourceManager[ApifyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return apify_dataset_source(
            api_token=config.api_token,
            dataset_id=config.dataset_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
