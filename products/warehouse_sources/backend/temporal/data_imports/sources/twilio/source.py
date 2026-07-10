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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TwilioSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.twilio import (
    TwilioAuth,
    TwilioResumeConfig,
    twilio_source,
    validate_credentials as validate_twilio_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TwilioSource(ResumableSource[TwilioSourceConfig, TwilioResumeConfig]):
    supported_versions = ("2010-04-01",)
    default_version = "2010-04-01"
    api_docs_url = "https://www.twilio.com/docs/usage/api"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TWILIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TWILIO,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Twilio",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Twilio credentials to pull your Twilio data into the PostHog Data warehouse.

Your **Account SID** is on the [Twilio Console dashboard](https://console.twilio.com). For credentials we recommend creating a [Standard API key](https://console.twilio.com/us1/account/keys-credentials/api-keys) (SID + Secret) since it can be revoked independently — alternatively you can use your Account SID and Auth Token.""",
            iconPath="/static/services/twilio.png",
            docsUrl="https://posthog.com/docs/cdp/sources/twilio",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_sid",
                        label="Account SID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="AC...",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication method",
                        required=True,
                        defaultValue="api_key",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="API key (SID + secret)",
                                value="api_key",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="api_key_sid",
                                            label="API key SID",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="SK...",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="api_key_secret",
                                            label="API key secret",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Auth token",
                                value="auth_token",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="auth_token",
                                            label="Auth token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.twilio.com": "Invalid Twilio credentials. Please check your Account SID and Auth Token (or API key SID and secret) and reconnect.",
            "403 Client Error: Forbidden for url: https://api.twilio.com": "Your Twilio credentials lack permission for this resource. Please check the credential's permissions and try again.",
        }

    def _get_auth(self, config: TwilioSourceConfig) -> TwilioAuth:
        if config.auth_method.selection == "auth_token":
            if not config.auth_method.auth_token:
                raise ValueError("Missing Twilio auth token")
            return config.account_sid, config.auth_method.auth_token

        if not config.auth_method.api_key_sid or not config.auth_method.api_key_secret:
            raise ValueError("Missing Twilio API key SID or secret")
        return config.auth_method.api_key_sid, config.auth_method.api_key_secret

    def get_schemas(
        self,
        config: TwilioSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TwilioSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            auth = self._get_auth(config)
        except ValueError as e:
            return False, str(e)
        return validate_twilio_credentials(auth, config.account_sid, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TwilioResumeConfig]:
        return ResumableSourceManager[TwilioResumeConfig](inputs, TwilioResumeConfig)

    def source_for_pipeline(
        self,
        config: TwilioSourceConfig,
        resumable_source_manager: ResumableSourceManager[TwilioResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return twilio_source(
            auth=self._get_auth(config),
            account_sid=config.account_sid,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
