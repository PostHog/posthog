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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.coralogix import (
    CoralogixResumeConfig,
    coralogix_source,
    validate_credentials as validate_coralogix_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.settings import (
    CORALOGIX_ENDPOINTS,
    DEFAULT_LOOKBACK_DAYS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CoralogixSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CoralogixSource(ResumableSource[CoralogixSourceConfig, CoralogixResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CORALOGIX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CORALOGIX,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Coralogix",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["logs", "observability", "traces", "dataprime"],
            caption="""Enter a Coralogix API key to pull your logs and spans into the PostHog Data warehouse via the DataPrime query API.

Create a personal or team API key in Coralogix under **Settings** → **API keys** and grant it the **DataQuerying** permission preset.

Pick the domain that matches your Coralogix account (shown in your Coralogix URL) — querying the wrong cluster fails with a permission error.

The **Frequent search** tier queries your indexed retention and works out of the box. Choose **Archive** to query your S3 archive instead (requires archiving to be enabled on your Coralogix account).
""",
            iconPath="/static/services/coralogix.png",
            docsUrl="https://posthog.com/docs/cdp/sources/coralogix",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="domain",
                        label="Coralogix domain",
                        required=True,
                        defaultValue="coralogix.us",
                        options=[
                            SourceFieldSelectConfigOption(label="US1 (coralogix.us)", value="coralogix.us"),
                            SourceFieldSelectConfigOption(
                                label="US2 (cx498.coralogix.com)", value="cx498.coralogix.com"
                            ),
                            SourceFieldSelectConfigOption(label="EU1 (coralogix.com)", value="coralogix.com"),
                            SourceFieldSelectConfigOption(label="EU2 (eu2.coralogix.com)", value="eu2.coralogix.com"),
                            SourceFieldSelectConfigOption(label="AP1 (coralogix.in)", value="coralogix.in"),
                            SourceFieldSelectConfigOption(label="AP2 (coralogixsg.com)", value="coralogixsg.com"),
                            SourceFieldSelectConfigOption(label="AP3 (ap3.coralogix.com)", value="ap3.coralogix.com"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="tier",
                        label="Query tier",
                        required=True,
                        defaultValue="frequent_search",
                        options=[
                            SourceFieldSelectConfigOption(label="Frequent search", value="frequent_search"),
                            SourceFieldSelectConfigOption(label="Archive", value="archive"),
                        ],
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # `domain` selects the cluster the stored API key is sent to; retargeting it must
        # re-require the key.
        return ["domain"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid/revoked key, a key without the DataQuerying preset, or a key used against
            # the wrong regional cluster all surface as a requests HTTPError when `_run_query`
            # calls `raise_for_status()`. Retrying can never fix a credential problem. All of this
            # source's URLs start with `https://api.<coralogix domain>`, so matching on the stable
            # status text + URL prefix is precise within this source.
            "401 Client Error: Unauthorized for url: https://api.": "Your Coralogix API key is invalid or has been revoked. Create a new key with the DataQuerying permission preset, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.": "Coralogix rejected the API key. Check that the key has the DataQuerying permission preset and that the selected domain matches your Coralogix account, then reconnect.",
        }

    def get_schemas(
        self,
        config: CoralogixSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = CORALOGIX_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # Logs and spans are immutable telemetry with no server-side "updated" filter, so
                # append (advancing the timestamp watermark) is the only incremental mode —
                # merge-based incremental would pointlessly re-merge a huge immutable table.
                supports_incremental=False,
                supports_append=True,
                incremental_fields=INCREMENTAL_FIELDS[endpoint],
                detected_primary_keys=endpoint_config.primary_keys,
                description=(
                    f"Raw {endpoint} queried via DataPrime (`source {endpoint_config.dataprime_source}`). "
                    f"Only syncs the last {DEFAULT_LOOKBACK_DAYS} days on initial sync and full refresh."
                ),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: CoralogixSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_coralogix_credentials(config.api_key, config.domain):
            return True, None

        return (
            False,
            "Invalid Coralogix API key — check that the key has the DataQuerying permission preset "
            "and that the selected domain matches your Coralogix account",
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CoralogixResumeConfig]:
        return ResumableSourceManager[CoralogixResumeConfig](inputs, CoralogixResumeConfig)

    def source_for_pipeline(
        self,
        config: CoralogixSourceConfig,
        resumable_source_manager: ResumableSourceManager[CoralogixResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return coralogix_source(
            api_key=config.api_key,
            domain=config.domain,
            tier=config.tier,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
