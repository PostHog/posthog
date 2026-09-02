from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.flutterwave import (
    FlutterwaveResumeConfig,
    flutterwave_source,
    validate_credentials as validate_flutterwave_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flutterwave import (
    FlutterwaveSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FlutterwaveSource(ResumableSource[FlutterwaveSourceConfig, FlutterwaveResumeConfig]):
    # v3 is Flutterwave's generally available API and the version every request below calls (the
    # `/v3` base-URL segment). v4 exists but is still a public beta on a separate host with a
    # different OAuth flow, so it is not what a new source should land customers on.
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://developer.flutterwave.com/docs/versioning"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FLUTTERWAVE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FLUTTERWAVE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Flutterwave",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Flutterwave secret key to sync your payments data into the PostHog Data warehouse.

You can find your secret key under Settings > API in the [Flutterwave dashboard](https://app.flutterwave.com/dashboard/settings/apis). Test keys only return sandbox records, so use your live secret key to sync live data.""",
            iconPath="/static/services/flutterwave.png",
            docsUrl="https://posthog.com/docs/cdp/sources/flutterwave",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="FLWSECK-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.flutterwave.com": "Your Flutterwave secret key is invalid or has been rotated. Copy the current key from your Flutterwave dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.flutterwave.com": "Your Flutterwave secret key does not have access to this data. Check the key's permissions in your Flutterwave dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: FlutterwaveSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: FlutterwaveSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_flutterwave_credentials(config.secret_key, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FlutterwaveResumeConfig]:
        return ResumableSourceManager[FlutterwaveResumeConfig](inputs, FlutterwaveResumeConfig)

    def source_for_pipeline(
        self,
        config: FlutterwaveSourceConfig,
        resumable_source_manager: ResumableSourceManager[FlutterwaveResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return flutterwave_source(
            secret_key=config.secret_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
