import re
from typing import Optional, cast

from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    required_parents_from_endpoint_configs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    SortMode,
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zendesk import (
    ZendeskSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.settings import (
    BASE_ENDPOINTS,
    INCREMENTAL_FIELDS as ZENDESK_INCREMENTAL_FIELDS,
    PARTITION_FIELDS,
    SUPPORT_ENDPOINTS,
    ZENDESK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.zendesk import (
    ZendeskResumeConfig,
    normalize_subdomain,
    validate_credentials,
    zendesk_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZendeskSource(ResumableSource[ZendeskSourceConfig, ZendeskResumeConfig]):
    codebase_detection = detect(
        env=("^ZENDESK_",),
        script_hosts=("static.zdassets.com", "ekr.zdassets.com", "v2.zopim.com", "assets.zendesk.com", "cdn.smooch.io"),
        npm=(
            "node-zendesk",
            "zendesk_app_framework_sdk",
            "@zendesk/zcli",
            "react-zendesk",
            "react-native-zendesk-messaging",
            "@types/zendesk-web-widget",
            "smooch",
            "sunshine-conversations-client",
            "passport-zendesk",
            "@zendesk/connector-sdk",
            "@zendesk/zendesk-app-scripts",
        ),
        pypi=("zenpy", "sunshine-conversations-client"),
        cocoapods=(
            "ZendeskSupportSDK",
            "ZendeskSDKMessaging",
            "ZendeskChatSDK",
            "ZendeskChatProvidersSDK",
            "ZendeskAnswerBotSDK",
            "ZendeskAnswerBotProvidersSDK",
            "ZendeskSupportProvidersSDK",
            "ZendeskCoreSDK",
            "ZendeskCommonUISDK",
            "ZendeskMessagingSDK",
            "ZendeskMessagingAPISDK",
            "ZendeskSDK",
            "ZendeskSDKConfigurationsSDK",
            "ZendeskSDKGuideKit",
            "ZendeskSDKConversationKit",
            "ZendeskSDKCoreUtilities",
            "ZendeskSDKUIComponents",
            "ZendeskTalkSDK",
            "ZDCChat",
            "Smooch",
        ),
        composer=("zendesk/zendesk_api_client_php", "huddledigital/zendesk-laravel"),
        go=("github.com/nukosuke/go-zendesk",),
        maven=(
            "zendesk.messaging:messaging-android",
            "zendesk.guidekit:guidekit-android",
            "zendesk.talk:talk-android",
            "zendesk.conversationkit:conversationkit-android",
            "zendesk.ui:ui-android",
            "com.zendesk:support",
            "com.zendesk:support-providers",
            "com.zendesk:chat",
            "com.zendesk:chat-providers",
            "com.zendesk:answerbot",
            "com.zendesk:answerbot-providers",
            "com.zendesk:messaging",
            "com.zendesk:messaging-api",
            "com.zendesk:core",
            "com.zendesk:common-ui",
            "com.zendesk:guide",
            "com.zendesk:guide-providers",
            "com.zendesk:sdk",
            "com.zendesk:sdk-providers",
            "com.zendesk:sdk-configurations",
            "com.zopim.android:sdk",
            "io.smooch:core",
            "io.smooch:ui",
            "com.zendesk:sunshine-conversations-client",
            "io.smooch:api",
            "com.cloudbees.thirdparty:zendesk-java-client",
        ),
        pub=("zendesk_messaging",),
        rubygems=(
            "zendesk_api",
            "zendesk_apps_tools",
            "zendesk_apps_support",
            "sunshine-conversations-client",
            "smooch-api",
        ),
        swiftpm=(
            "github.com/zendesk/sdk_messaging_ios",
            "github.com/zendesk/support_sdk_ios",
            "github.com/zendesk/support_providers_sdk_ios",
            "github.com/zendesk/chat_sdk_ios",
            "github.com/zendesk/chat_providers_sdk_ios",
            "github.com/zendesk/answer_bot_sdk_ios",
            "github.com/zendesk/answer_bot_providers_sdk_ios",
            "github.com/zendesk/core_sdk_ios",
            "github.com/zendesk/commonui_sdk_ios",
            "github.com/zendesk/messaging_sdk_ios",
            "github.com/zendesk/messagingapi_sdk_ios",
            "github.com/zendesk/sdk_zendesk_ios",
            "github.com/zendesk/sdkconfigurations_sdk_ios",
            "github.com/zendesk/talk_sdk_ios",
            "github.com/zendesk/sdk_guide_kit_ios",
            "github.com/zendesk/sdk_conversation_kit_ios",
            "github.com/zendesk/sdk_core_utilities_ios",
            "github.com/zendesk/sdk_ui_components_ios",
            "github.com/zendesk/sunshine-conversations-ios",
        ),
        alternative_to=(ProductKey.CONVERSATIONS,),
    )
    setup_requires_ui = True

    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.zendesk.com/api-reference"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    has_managed_hogql_schema = True  # canonical Zendesk schema in external_table_definitions

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZENDESK

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "404 Client Error: Not Found for url": "Zendesk authentication failed. Please check your API token and subdomain.",
            "403 Client Error: Forbidden for url": "Zendesk authentication failed. Please check your API token and subdomain.",
            "401 Client Error": "Zendesk authentication failed. Please check your API token and subdomain.",
        }

    def resume_covers_run(
        self,
        *,
        incremental_or_append: bool,
        schema_name: str | None = None,
    ) -> bool:
        endpoint = ZENDESK_ENDPOINTS.get(schema_name or "")
        return endpoint is None or endpoint.fanout is None

    def get_required_parent_schemas(self, schema_name: str) -> list[str]:
        return required_parents_from_endpoint_configs(ZENDESK_ENDPOINTS, schema_name)

    def get_schemas(
        self,
        config: ZendeskSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=ZENDESK_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=ZENDESK_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=ZENDESK_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(BASE_ENDPOINTS)
            + [resource for resource, endpoint_url, data_key, cursor_paginated in SUPPORT_ENDPOINTS]
        ]
        schemas += [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=bool(endpoint_config.incremental_fields),
                supports_append=bool(endpoint_config.incremental_fields),
                incremental_fields=endpoint_config.incremental_fields,
            )
            for endpoint_config in ZENDESK_ENDPOINTS.values()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: ZendeskSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        subdomain = normalize_subdomain(config.subdomain)
        subdomain_regex = re.compile("^[a-zA-Z0-9-]+$")
        if not subdomain_regex.match(subdomain):
            return False, "Zendesk subdomain is incorrect"

        if validate_credentials(subdomain, config.api_key, config.email_address):
            return True, None

        return (
            False,
            "Zendesk rejected the credentials. Check the subdomain, email address, and API token are correct, "
            "and that token access is enabled for your account.",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZENDESK,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            caption="Enter your Zendesk API key to automatically pull your Zendesk support data into the PostHog Data warehouse.",
            iconPath="/static/services/zendesk.png",
            iconClassName="rounded dark:bg-white p-[2px]",
            docsUrl="https://posthog.com/docs/cdp/sources/zendesk",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Zendesk subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="email_address",
                        label="Zendesk email address",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZendeskResumeConfig]:
        return ResumableSourceManager[ZendeskResumeConfig](inputs, ZendeskResumeConfig)

    def source_for_pipeline(
        self,
        config: ZendeskSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZendeskResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint_config = ZENDESK_ENDPOINTS.get(inputs.schema_name)
        is_fanout = endpoint_config is not None and endpoint_config.fanout is not None
        resource = zendesk_source(
            subdomain=config.subdomain,
            api_key=config.api_key,
            email_address=config.email_address,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field_name=inputs.incremental_field,
            source_id=inputs.source_id,
            use_warehouse_parent=inputs.fanout_warehouse_reuse,
            resumable_source_manager=resumable_source_manager,
        )
        # The original nine endpoints aren't in the declarative catalog; they keep the `id`
        # primary key. The time-ordered incremental exports give them an ascending sort, except
        # `tickets`: its cursor export states no order for `generated_timestamp`.
        legacy_sort_mode: SortMode | None = None if inputs.schema_name == "tickets" else "asc"
        response = SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=endpoint_config.primary_key if endpoint_config else ["id"],
            column_hints=resource.column_hints,
            sort_mode=endpoint_config.sort_mode if endpoint_config else legacy_sort_mode,
            # The fan-out saves no checkpoint (see `zendesk_source`), so a shutdown must not hand it
            # to another worker expecting one.
            supports_resume=not is_fanout,
        )

        partition_key = PARTITION_FIELDS.get(inputs.schema_name, None)
        if partition_key is None and endpoint_config is not None:
            partition_key = endpoint_config.partition_key

        # All partition keys are datetime
        if partition_key:
            response.partition_count = 1
            response.partition_size = 1
            response.partition_mode = "datetime"
            response.partition_format = "week"
            response.partition_keys = [partition_key]

        return response
