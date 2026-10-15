from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.blueshift.blueshift import (
    BlueshiftResumeConfig,
    blueshift_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.blueshift.settings import (
    DEFAULT_REGION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.blueshift import (
    BlueshiftSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BlueshiftSource(ResumableSource[BlueshiftSourceConfig, BlueshiftResumeConfig]):
    codebase_detection = detect(
        env=("^BLUESHIFT_",),
        script_hosts=("cdn.getblueshift.com",),
        npm=("blueshift-react-native", "blueshift-inbox-react-native", "blueshift-expo"),
        pypi=("blueshift-python",),
        cocoapods=("BlueShift-iOS-SDK",),
        maven=("com.blueshift:android-sdk",),
        pub=("blueshift_flutter_plugin",),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Content endpoints live under /api/v1 and the campaign list under /api/v2, so there is no
    # single version token to pin.
    api_docs_url = "https://developer.blueshift.com/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BLUESHIFT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BLUESHIFT,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Blueshift",
            caption="""Sync campaigns, daily campaign performance, templates, segments, subscription groups and tags from Blueshift.

Use a **user API key** from **Account settings > API keys** in Blueshift. Pick the region your account is hosted in.""",
            iconPath="/static/services/blueshift.png",
            docsUrl="https://posthog.com/docs/cdp/sources/blueshift",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="User API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue=DEFAULT_REGION,
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.getblueshift.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.getblueshift.com)", value="eu"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.blueshift.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Blueshift rejected the API key. Create a new user API key in Blueshift, then reconnect the source.",
            "403 Client Error: Forbidden for url": "The Blueshift API key can't read one of the tables you sync. Use a key with access to that data, or deselect the table.",
        }

    def get_schemas(
        self,
        config: BlueshiftSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BlueshiftSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, status = probe_credentials(config.region, config.api_key)
        if is_valid:
            return True, None
        if status == 401:
            return (
                False,
                "Blueshift rejected the API key. Check that you pasted a user API key for the selected region.",
            )
        if status == 403 and schema_name is None:
            # The key is genuine but cannot list segments; a table it cannot read fails at sync with a clear message.
            return True, None
        return False, "Couldn't reach Blueshift with these credentials. Check the API key and region, then try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BlueshiftResumeConfig]:
        return ResumableSourceManager[BlueshiftResumeConfig](inputs, BlueshiftResumeConfig)

    def source_for_pipeline(
        self,
        config: BlueshiftSourceConfig,
        resumable_source_manager: ResumableSourceManager[BlueshiftResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return blueshift_source(
            region=config.region,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
