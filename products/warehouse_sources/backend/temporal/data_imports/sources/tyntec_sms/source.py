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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tyntecsms import (
    TyntecSMSSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SHOULD_SYNC_DEFAULT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.tyntec_sms import (
    tyntec_sms_source,
    validate_credentials as validate_tyntec_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TyntecSMSSource(SimpleSource[TyntecSMSSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://api.tyntec.com/reference/sms/current.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TYNTECSMS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.tyntec.com": "tyntec authentication failed. Please check your API key.",
            "403 Client Error: Forbidden for url: https://api.tyntec.com": "tyntec rejected your API key. Please check the key and its permissions in the tyntec Business Center.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TyntecSMSSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions=ENDPOINT_DESCRIPTIONS,
            should_sync_default=SHOULD_SYNC_DEFAULT,
        )

    def validate_credentials(
        self,
        config: TyntecSMSSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.api_key:
            return False, "tyntec API key is required"

        if validate_tyntec_credentials(config.api_key):
            return True, None

        return False, "Invalid tyntec API key"

    def source_for_pipeline(self, config: TyntecSMSSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return tyntec_sms_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            request_ids=config.request_ids,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TYNTEC_SMS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Tyntec SMS",
            caption="Import SMS delivery statuses and BYON phone book data from tyntec. Get your API key from the [tyntec Business Center](https://my.tyntec.com/).",
            keywords=["sms", "cpaas"],
            docsUrl="https://posthog.com/docs/cdp/sources/tyntec-sms",
            iconPath="/static/services/tyntec_sms.png",
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
                    SourceFieldInputConfig(
                        name="request_ids",
                        label="SMS request IDs",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=False,
                        placeholder="e74db8d4-77ad-4671-8feb-9bc76b0df188, 57d2a198-cbdf-478c-8da0-c164b4ce5ac5",
                        secret=False,
                        caption="Request IDs of sent SMS messages to import statuses for, separated by commas or new lines. tyntec has no bulk message list, so the MessageStatus table only contains the messages listed here.",
                    ),
                ],
            ),
        )
