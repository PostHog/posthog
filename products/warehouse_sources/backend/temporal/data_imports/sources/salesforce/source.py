from typing import cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    SourceConfig,
    SourceFieldOauthConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.salesforce import (
    SalesforceSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth import (
    INSTANCE_HOST_NOT_FOUND_ERROR,
    salesforce_refresh_access_token,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.salesforce import (
    SalesforceResumeConfig,
    salesforce_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SalesforceSource(ResumableSource[SalesforceSourceConfig, SalesforceResumeConfig], OAuthMixin):
    codebase_detection = detect(
        env=(
            "^SALESFORCE_",
            "^SF_ACCESS_TOKEN$",
            "^SF_ORG_INSTANCE_URL$",
            "^SFDX_",
            "^SF_TARGET_ORG$",
            "^SF_TARGET_DEV_HUB$",
            "^SF_ORG_API_VERSION$",
            "^SF_AUDIENCE_URL$",
            "^SF_LOGIN_URL$",
            "^SF_CONSUMER_KEY$",
            "^SF_CONSUMER_SECRET$",
            "^SF_CALLBACK_URI$",
            "^AUTH_SALESFORCE_(ID|SECRET)$",
            "^AIRFLOW_CONN_SALESFORCE",
            "^CUMULUSCI_",
        ),
        script_hosts=("service.force.com", "cdn.c360a.salesforce.com", "salesforceliveagent.com"),
        npm=(
            "jsforce",
            "@jsforce/jsforce-node",
            "@types/jsforce",
            "node-salesforce",
            "@salesforce/cli",
            "sfdx-cli",
            "@salesforce/core",
            "@salesforce/mcp",
            "@salesforce/agents",
            "@salesforce/canvas-js-sdk",
            "@salesforce/lightning-out",
            "@salesforce/platform-sdk",
            "@salesforce/ui-bundle",
            "@salesforce/scv-connector-base",
            "@salesforce/react-native-agentforce",
            "@salesforce/sfdx-lwc-jest",
            "forceios",
            "forcedroid",
            "forcereact",
            "forcehybrid",
            "react-native-force",
            "salesforce-mobilesdk-cordova-plugin",
            "salesforce-pubsub-api-client",
            "nforce",
            "passport-forcedotcom",
            "passport-salesforce",
        ),
        pypi=(
            "simple-salesforce",
            "salesforce-bulk",
            "cumulusci",
            "django-salesforce",
            "beatbox",
            "aiosfstream",
            "salesforce-cdp-connector",
            "apache-airflow-providers-salesforce",
        ),
        cargo=("rustforce",),
        cocoapods=("Messaging-InApp-UI", "Messaging-InApp-Core"),
        composer=(
            "omniphx/forrest",
            "developerforce/force.com-toolkit-for-php",
            "davispeixoto/force-dot-com-toolkit-for-php",
            "phpforce/soap-client",
            "stevenmaguire/oauth2-salesforce",
            "socialiteproviders/salesforce",
            "rob-lester-jr04/eloquent-sales-force",
        ),
        go=(
            "github.com/simpleforce/simpleforce",
            "github.com/k-capehart/go-salesforce",
            "github.com/nimajalali/go-force",
            "github.com/forcedotcom/go-soql",
            "github.com/tzmfreedom/go-soapforce",
        ),
        hex=("ex_force", "forcex"),
        maven=(
            "com.force.api:force-wsc",
            "com.force.api:force-partner-api",
            "com.force.api:force-metadata-api",
            "com.force.api:force-apex-api",
            "com.salesforce.mobilesdk:SalesforceSDK",
            "com.salesforce.mobilesdk:MobileSync",
            "com.salesforce.mobilesdk:SmartStore",
            "com.salesforce.mobilesdk:SalesforceHybrid",
            "com.salesforce.mobilesdk:SalesforceReact",
            "com.salesforce.mobilesdk:SalesforceAnalytics",
            "com.salesforce.service:messaging-inapp-ui",
            "com.salesforce.service:messaging-inapp-core",
            "com.salesforce.service:chat-ui",
            "com.salesforce.service:chat-core",
            "com.salesforce.service:knowledge-ui",
            "com.salesforce.service:knowledge-core",
            "com.salesforce.einsteinbot:einstein-bot-sdk-java",
            "com.salesforce.datacloud:jdbc",
            "com.frejo:force-rest-api",
            "org.apache.camel:camel-salesforce",
            "org.apache.camel.springboot:camel-salesforce-starter",
        ),
        rubygems=(
            "restforce",
            "databasedotcom",
            "omniauth-salesforce",
            "soapforce",
            "salesforce_bulk_api",
            "salesforce_bulk_query",
            "rforce",
            "metaforce",
        ),
        swiftpm=(
            "github.com/forcedotcom/salesforcemobilesdk-ios-spm",
            "github.com/salesforce-async-messaging/swift-package-inappmessaging",
            "github.com/salesforce/agentforcemobilesdk-ios",
        ),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Salesforce moves orgs onto a new release over several weeks, and an org still on the previous
    # release answers 404 to every path of the new version. New sources are pinned to the default, so
    # declare a release's version only once it has reached every production org.
    supported_versions = ("v61.0", "v67.0")
    default_version = "v67.0"
    api_docs_url = "https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/intro_rest.htm"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SALESFORCE

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "invalid_session_id": "Your Salesforce session has expired. Please reconnect the source.",
            "400 Client Error: Bad Request for url": None,
            "403 Client Error: Forbidden for url": None,
            # Salesforce answers 404 on every path of a release an org has not been moved to yet
            # (see `supported_versions` above), and on an object the org does not have. Both are
            # deterministic for the stored pin and the selected table, so retrying replays the same
            # rejection and the raw text echoes the org's instance URL and the SOQL query back to
            # the customer. Match the stable status text, not the volatile url that follows it.
            "404 Client Error: Not Found for url": (
                "Salesforce doesn't have this object, or your org doesn't support the API version "
                "this source uses. Remove the table from the source's selected tables, or contact "
                "support."
            ),
            "inactive organization": None,
            # Salesforce's OAuth token endpoint returns error_description "inactive user" when the
            # user that authorized the connection has been deactivated. Retrying can't fix it —
            # the user must be reactivated in Salesforce or the source reconnected with an active user.
            "inactive user": "The Salesforce user for this connection is inactive. Reactivate it in Salesforce or reconnect the source with an active user.",
            # OAuthMixin.get_oauth_integration raises "Integration not found: <id>" when the
            # linked Salesforce integration has been deleted/disconnected. The source still
            # references the stale id, so retrying never recovers — reconnecting is the only fix.
            "Integration not found": "The linked Salesforce integration no longer exists. Please reconnect the source.",
            # SalesforceAuthRequestError.raise_from_response formats token-refresh failures as
            # "<code> Client Error: <reason>: <error_description>", so the "... for url" patterns
            # above never match it. Key off the stable error_description returned by Salesforce
            # when the refresh token is expired/revoked — reconnecting is the only fix.
            "expired access/refresh token": "Your Salesforce connection has expired or been revoked. Please reconnect the source.",
            INSTANCE_HOST_NOT_FOUND_ERROR: (
                "Your Salesforce org's address no longer exists, so the org may be deleted or its My Domain "
                "renamed. Reconnect your Salesforce account, then re-enable the sync."
            ),
        }

    def get_schemas(
        self,
        config: SalesforceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SALESFORCE,
            category=DataWarehouseSourceCategory.CRM,
            keywords=["sfdc"],
            caption="Select an existing Salesforce account to link to PostHog or create a new connection",
            iconPath="/static/services/salesforce.png",
            docsUrl="https://posthog.com/docs/cdp/sources/salesforce",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="salesforce_integration_id", label="Salesforce account", required=True, kind="salesforce"
                    )
                ],
            ),
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SalesforceResumeConfig]:
        return ResumableSourceManager[SalesforceResumeConfig](inputs, SalesforceResumeConfig)

    def source_for_pipeline(
        self,
        config: SalesforceSourceConfig,
        resumable_source_manager: ResumableSourceManager[SalesforceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration = self.get_oauth_integration(config.salesforce_integration_id, inputs.team_id)

        salesforce_refresh_token = integration.refresh_token

        if not salesforce_refresh_token:
            raise ValueError(f"Salesforce refresh token not found for job {inputs.job_id}")

        salesforce_access_token = integration.access_token
        salesforce_instance_url = cast(str, integration.config.get("instance_url"))

        if not salesforce_access_token:
            salesforce_access_token = salesforce_refresh_access_token(salesforce_refresh_token, salesforce_instance_url)

        resource = salesforce_source(
            instance_url=salesforce_instance_url,
            access_token=salesforce_access_token,
            refresh_token=salesforce_refresh_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=["id"] if inputs.should_use_incremental_field else None,
            column_hints=resource.column_hints,
        )
