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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twilio import TwilioSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SHOULD_SYNC_DEFAULT,
    TWILIO_API_HOST,
    TWILIO_VERIFY_HOST,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.twilio import (
    TwilioAuth,
    TwilioResumeConfig,
    check_endpoint_permissions as check_twilio_endpoint_permissions,
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

Your **Account SID** is on the [Twilio Console dashboard](https://console.twilio.com). For credentials we recommend creating a [Standard API key](https://console.twilio.com/us1/account/keys-credentials/api-keys) (SID + Secret) since it can be revoked independently. You can also use your Account SID and Auth Token.

Create the key in the same Twilio account as the Account SID above, in Twilio's default us1 region. A Standard key can read every table except `keys`, which needs your Auth Token or a Main API key.""",
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
        # Each pattern is scoped to a Twilio host so an unrelated 401 elsewhere in the same job can't
        # false-match. The catalog spans two hosts, so both need covering.
        unauthorized = (
            # Twilio returns 401 both for a bad secret and for a valid credential that isn't allowed to
            # read the resource (error 20003), and the two are indistinguishable from the status alone,
            # so this message has to cover both rather than asserting the credentials are invalid.
            "Twilio rejected these credentials for this table. Either the Account SID and secret are wrong, "
            "or the credential can't read this resource. A Restricted API key needs read access granted for "
            "it, and the keys table needs your Auth token or a Main API key. Fix the credential, then "
            "reconnect the source."
        )
        forbidden = (
            "Your Twilio credentials lack permission for this resource. Please check the credential's "
            "permissions and try again."
        )
        errors: dict[str, str | None] = {}
        for host in (TWILIO_API_HOST, TWILIO_VERIFY_HOST):
            errors[f"401 Client Error: Unauthorized for url: {host}"] = unauthorized
            errors[f"403 Client Error: Forbidden for url: {host}"] = forbidden
        return errors

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
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, should_sync_default=SHOULD_SYNC_DEFAULT)

    def validate_credentials(
        self,
        config: TwilioSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            auth = self._get_auth(config)
        except ValueError as e:
            return False, str(e)
        return validate_twilio_credentials(auth, config.account_sid, schema_name)

    def get_endpoint_permissions(
        self, config: TwilioSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        try:
            auth = self._get_auth(config)
        except ValueError:
            # validate_credentials already reports a missing secret, so treat every table as available
            # rather than blocking the picker on a condition the caller has surfaced.
            return dict.fromkeys(endpoints)
        return check_twilio_endpoint_permissions(auth, config.account_sid, endpoints)

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
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
