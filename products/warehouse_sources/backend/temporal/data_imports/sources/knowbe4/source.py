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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.knowbe4 import (
    Knowbe4SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.knowbe4 import (
    knowbe4_source,
    validate_credentials as validate_knowbe4_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Knowbe4Source(SimpleSource[Knowbe4SourceConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to
    # render in public docs without credentials.
    lists_tables_without_credentials = True
    api_docs_url = "https://developer.knowbe4.com/rest/reporting"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KNOWBE4

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` selects which regional host the stored API key is sent to; retargeting it
        # must re-require the key (KnowBe4 keys are only valid against the region they were
        # generated in anyway).
        return ["region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        message = (
            "Your KnowBe4 API key is invalid or expired. Generate a new key in Account Settings > API and reconnect."
        )
        return {
            "401 Client Error: Unauthorized": message,
            "Invalid KnowBe4 API key": message,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: Knowbe4SourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: Knowbe4SourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_knowbe4_credentials(
            api_key=config.api_key,
            region=config.region,
            schema_name=schema_name,
        )

    def source_for_pipeline(self, config: Knowbe4SourceConfig, inputs: SourceInputs) -> SourceResponse:
        return knowbe4_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KNOWBE4,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="KnowBe4",
            keywords=["security awareness training", "phishing simulation"],
            caption=(
                "Enter your KnowBe4 Reporting API key to pull your security awareness training and "
                "phishing simulation data into the PostHog Data warehouse.\n\n"
                "Generate a key as an account admin under **Account Settings > API**. Reporting API "
                "keys are account-wide (no scopes to grant) but are only valid against the region "
                "your console runs on.\n\n"
                "Pick the **region** matching the URL you sign in to."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/knowbe4",
            iconPath="/static/services/knowbe4.png",
            releaseStatus=ReleaseStatus.ALPHA,
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
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (us.api.knowbe4.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (eu.api.knowbe4.com)", value="eu"),
                            SourceFieldSelectConfigOption(label="CA (ca.api.knowbe4.com)", value="ca"),
                            SourceFieldSelectConfigOption(label="UK (uk.api.knowbe4.com)", value="uk"),
                            SourceFieldSelectConfigOption(label="DE (de.api.knowbe4.com)", value="de"),
                        ],
                    ),
                ],
            ),
        )
