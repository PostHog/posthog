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
from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.braintree import (
    BraintreeResumeConfig,
    braintree_source,
    validate_credentials as validate_braintree_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BraintreeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BraintreeSource(ResumableSource[BraintreeSourceConfig, BraintreeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("2019-01-01",)
    default_version = "2019-01-01"
    api_docs_url = "https://graphql.braintreepayments.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BRAINTREE

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://payments.braintree-api.com": "Braintree authentication failed. Please check your public and private keys.",
            "401 Client Error: Unauthorized for url: https://payments.sandbox.braintree-api.com": "Braintree authentication failed. Please check your public and private keys (and that they match the selected environment).",
            "Braintree GraphQL error": "Braintree rejected the request. Please check that your API keys have access to the requested data.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BRAINTREE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Braintree",
            caption="""Enter your Braintree API keys to pull your payments data into the PostHog Data warehouse.

You can find your public and private keys in the [Braintree control panel](https://www.braintreegateway.com/) under Settings > API Keys. Sandbox and production use separate keys — make sure the environment matches.""",
            iconPath="/static/services/braintree.png",
            docsUrl="https://posthog.com/docs/cdp/sources/braintree",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="public_key",
                        label="Public key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="private_key",
                        label="Private key",
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
        config: BraintreeSourceConfig,
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
        self, config: BraintreeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_braintree_credentials(config.environment, config.public_key, config.private_key):
            return True, None

        return False, "Invalid Braintree API keys"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BraintreeResumeConfig]:
        return ResumableSourceManager[BraintreeResumeConfig](inputs, BraintreeResumeConfig)

    def source_for_pipeline(
        self,
        config: BraintreeSourceConfig,
        resumable_source_manager: ResumableSourceManager[BraintreeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return braintree_source(
            environment=config.environment,
            public_key=config.public_key,
            private_key=config.private_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
