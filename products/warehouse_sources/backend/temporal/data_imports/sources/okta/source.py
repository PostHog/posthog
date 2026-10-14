from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.okta import OktaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.okta import (
    HOST_NOT_ALLOWED_ERROR,
    OktaResumeConfig,
    okta_source,
    validate_credentials as validate_okta_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OktaSource(ResumableSource[OktaSourceConfig, OktaResumeConfig]):
    codebase_detection = detect(
        env=(
            "^OKTA_",
            "^REACT_APP_OKTA_",
            "^VITE_OKTA_",
            "^NEXT_PUBLIC_OKTA_",
            "^VUE_APP_OKTA_",
            "^EXPO_PUBLIC_OKTA_",
            "^AUTH_OKTA_ID$",
            "^AUTH_OKTA_SECRET$",
            "^AUTH_OKTA_ISSUER$",
        ),
        script_hosts=("global.oktacdn.com", "ok1static.oktacdn.com"),
        npm=(
            "@okta/okta-sdk-nodejs",
            "@okta/okta-auth-js",
            "@okta/okta-react",
            "@okta/okta-signin-widget",
            "@okta/okta-vue",
            "@okta/okta-angular",
            "@okta/jwt-verifier",
            "@okta/okta-react-native",
            "@okta/oidc-middleware",
            "@okta/auth-foundation",
            "@okta/spa-platform",
            "@okta/oauth2-flows",
            "@okta/react-native-platform",
            "@okta/react-native-webcrypto-bridge",
            "@okta/okta-idx-js",
            "@okta/vdc-sdk-node",
        ),
        pypi=("okta", "okta-jwt-verifier", "okta-client-python", "okta-mcp-server"),
        cargo=("okta", "okta-jwt-verifier"),
        cocoapods=(
            "OktaOidc",
            "OktaClient",
            "OktaAuthFoundation",
            "OktaOAuth2",
            "OktaDirectAuth",
            "OktaIdxAuth",
            "OktaWebAuthenticationUI",
            "OktaIdx",
            "OktaAuthSdk",
            "OktaJWT",
            "DeviceAuthenticator",
        ),
        composer=("okta/sdk", "okta/jwt-verifier", "socialiteproviders/okta", "foxworth42/oauth2-okta"),
        go=(
            "github.com/okta/okta-sdk-golang",
            "github.com/okta/okta-jwt-verifier-golang",
            "github.com/okta/okta-idx-golang",
            "github.com/okta/okta-governance-sdk-golang",
        ),
        hex=("ueberauth_okta",),
        maven=(
            "com.okta.sdk:okta-sdk-api",
            "com.okta.spring:okta-spring-boot-starter",
            "com.okta.jwt:okta-jwt-verifier",
            "com.okta.android:okta-oidc-android",
            "com.okta.sdk:okta-sdk-impl",
            "com.okta.sdk:okta-sdk-httpclient",
            "com.okta.sdk:okta-sdk-okhttp",
            "com.okta.spring:okta-spring-sdk",
            "com.okta.spring:okta-spring-security-starter",
            "com.okta.jwt:okta-jwt-verifier-impl",
            "com.okta.authn.sdk:okta-authn-sdk-api",
            "com.okta.authn.sdk:okta-authn-sdk-impl",
            "com.okta.idx.sdk:okta-idx-java-api",
            "com.okta.hooks.sdk:okta-hooks",
            "com.okta.shiro:okta-shiro-plugin",
            "com.okta.android:library",
            "com.okta.android:okta-idx-kotlin",
            "com.okta.android:idx-kotlin",
            "com.okta.kotlin:bom",
            "com.okta.kotlin:auth-foundation",
            "com.okta.kotlin:auth-foundation-bootstrap",
            "com.okta.kotlin:oauth2",
            "com.okta.kotlin:okta-direct-auth",
            "com.okta.kotlin:okta-idx-kotlin",
            "com.okta.kotlin:web-authentication-ui",
            "com.okta.kotlin:legacy-token-migration",
            "com.okta.devices:devices-authenticator",
            "com.okta.devices:devices-push",
        ),
        rubygems=("omniauth-okta", "omniauth-oktaoauth", "oktakit"),
        swiftpm=(
            "github.com/okta/okta-mobile-swift",
            "github.com/okta/okta-oidc-ios",
            "github.com/okta/okta-auth-swift",
            "github.com/okta/okta-idx-swift",
            "github.com/okta/okta-ios-jwt",
            "github.com/okta/okta-devices-swift",
            "github.com/okta/okta-sdk-swift",
        ),
    )

    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developer.okta.com/docs/reference/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OKTA

    @property
    def connection_host_fields(self) -> list[str]:
        # `okta_domain` is where the stored API token is sent; retargeting it must re-require the token.
        return ["okta_domain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OKTA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Okta",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter your Okta org domain and an API token to pull your Okta data into the PostHog Data warehouse.

You can create an API token in the Okta Admin Console under **Security > API > Tokens**.

The token's user should have read access to the resources you want to sync, for example:
- `okta.users.read`
- `okta.groups.read`
- `okta.apps.read`
- `okta.logs.read`
""",
            iconPath="/static/services/okta.png",
            docsUrl="https://posthog.com/docs/cdp/sources/okta",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="okta_domain",
                        label="Okta domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-org.okta.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Okta API token. Please generate a new token and reconnect.",
            "403 Client Error": "Your Okta API token lacks the required permissions. Please check the token's scopes and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Okta domain is not allowed. Please use your organization's Okta domain.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.okta.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OktaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description="Only syncs the last 90 days on initial sync" if endpoint == "logs" else None,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: OktaSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_okta_credentials(config.okta_domain, config.api_key, schema_name, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OktaResumeConfig]:
        return ResumableSourceManager[OktaResumeConfig](inputs, OktaResumeConfig)

    def source_for_pipeline(
        self,
        config: OktaSourceConfig,
        resumable_source_manager: ResumableSourceManager[OktaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return okta_source(
            domain=config.okta_domain,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
