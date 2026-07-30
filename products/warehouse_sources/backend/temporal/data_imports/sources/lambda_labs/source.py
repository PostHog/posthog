from typing import Optional, cast

import requests

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LambdaLabsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.lambda_labs import (
    LambdaLabsResumeConfig,
    lambda_labs_source,
    validate_credentials as validate_lambda_labs_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.settings import LAMBDA_LABS_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LambdaLabsSource(ResumableSource[LambdaLabsSourceConfig, LambdaLabsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://cloud.lambda.ai/api/v1/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LAMBDALABS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad/revoked key surfaces as an HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can't fix a credential problem, so stop the sync. Match the stable status text
            # and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://cloud.lambda.ai": "Your Lambda API key is invalid or has been revoked. Create a new API key in your Lambda dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://cloud.lambda.ai": "Your Lambda API key does not have permission to access this data. Check the key in your Lambda dashboard, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LambdaLabsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=endpoint.supports_incremental,
                supports_append=endpoint.supports_incremental,
                incremental_fields=endpoint.incremental_fields,
            )
            for endpoint in LAMBDA_LABS_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: LambdaLabsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            if validate_lambda_labs_credentials(config.api_key):
                return True, None
            return False, "Invalid Lambda API key"
        except requests.RequestException:
            # A network blip, timeout, or 5xx isn't a bad key — don't mislabel it as invalid.
            return (
                False,
                "Could not reach Lambda to validate the API key. This may be a temporary network or service issue — please try again.",
            )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LambdaLabsResumeConfig]:
        return ResumableSourceManager[LambdaLabsResumeConfig](inputs, LambdaLabsResumeConfig)

    def source_for_pipeline(
        self,
        config: LambdaLabsSourceConfig,
        resumable_source_manager: ResumableSourceManager[LambdaLabsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return lambda_labs_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LAMBDA_LABS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Lambda",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Lambda API key to pull your Lambda (Lambda Labs) GPU cloud data into the PostHog Data warehouse.

You can create an API key in the [API keys section](https://cloud.lambda.ai/api-keys) of your Lambda dashboard. The key has account-wide access.""",
            iconPath="/static/services/lambda_labs.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/lambda-labs",
            keywords=["gpu", "cloud", "compute", "infrastructure", "lambda labs"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="secret_...",
                        secret=True,
                    ),
                ],
            ),
        )
