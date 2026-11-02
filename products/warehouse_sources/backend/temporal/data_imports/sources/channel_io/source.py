from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.channel_io.channel_io import (
    ChannelIOResumeConfig,
    channel_io_source,
    validate_credentials as validate_channel_io_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.channel_io.settings import (
    CHANNEL_IO_API_VERSION,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.channelio import (
    ChannelIOSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ChannelIOSource(ResumableSource[ChannelIOSourceConfig, ChannelIOResumeConfig]):
    codebase_detection = detect(
        script_hosts=("cdn.channel.io",),
        npm=("@channel.io/channel-web-sdk-loader", "@channel.io/react-native-channel-plugin"),
        cocoapods=("ChannelIOSDK",),
        maven=("io.channel:plugin-android",),
    )
    lists_tables_without_credentials = True
    supported_versions = (CHANNEL_IO_API_VERSION,)
    default_version = CHANNEL_IO_API_VERSION
    api_docs_url = "https://api-doc.channel.io/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHANNELIO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.channel.io": (
                "Channel.io rejected the access key and secret. Create a new credential in Channel.io, then reconnect the source."
            ),
            "403 Client Error: Forbidden for url: https://api.channel.io": (
                "This Channel.io credential can't read this data. Check the credential's permissions, then reconnect the source."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.channel_io.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ChannelIOSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # An incremental run reads each updated chat's new messages again, so append would duplicate them.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=("messages",))

    def validate_credentials(
        self,
        config: ChannelIOSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_channel_io_credentials(config, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ChannelIOResumeConfig]:
        return ResumableSourceManager[ChannelIOResumeConfig](inputs, ChannelIOResumeConfig)

    def source_for_pipeline(
        self,
        config: ChannelIOSourceConfig,
        resumable_source_manager: ResumableSourceManager[ChannelIOResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return channel_io_source(config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CHANNELIO,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Channel.io",
            keywords=["channel talk", "channeltalk", "채널톡"],
            caption=(
                "Import user chats, messages, managers and more from Channel.io. In the Channel desk, go to "
                "**Settings > API Key management**, create a new credential and paste the access key and "
                "access secret below."
            ),
            iconPath="/static/services/channel_io.png",
            docsUrl="https://posthog.com/docs/cdp/sources/channel-io",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_key",
                        label="Access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="access_secret",
                        label="Access secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
