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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tinyemail import (
    TinyemailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.tinyemail import (
    tinyemail_source,
    validate_credentials as validate_tinyemail_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TinyemailSource(SimpleSource[TinyemailSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.tinyemail.com/docs/tiny-email/tinyemail"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TINYEMAIL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TINYEMAIL,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="tinyEmail",
            keywords=["tiny email"],
            docsUrl="https://posthog.com/docs/cdp/sources/tinyemail",
            iconPath="/static/services/tinyemail.png",
            caption="""Enter a tinyEmail API key to sync campaigns, contact lists, contact members, and sender details.

You can generate an API key in tinyEmail under **My account → API keys**. Note that tinyEmail API access requires an Enterprise plan.
""",
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
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your tinyEmail API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error": "Your tinyEmail API key does not have access to this resource. Note that tinyEmail API access requires an Enterprise plan.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TinyemailSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: TinyemailSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_tinyemail_credentials(api_key=config.api_key)

    def source_for_pipeline(self, config: TinyemailSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return tinyemail_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )
