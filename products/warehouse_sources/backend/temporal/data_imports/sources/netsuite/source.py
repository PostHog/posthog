from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.netsuite import (
    NetSuiteSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.netsuite import (
    AUTH_FAILED_MESSAGE,
    INVALID_ACCOUNT_ID_MESSAGE,
    OAUTH_REJECTED_PREFIX,
    RECORD_PERMISSION_MESSAGE,
    REST_PERMISSION_MESSAGE,
    NetSuiteClient,
    NetSuiteCredentials,
    NetSuiteError,
    NetSuiteOAuth2Credentials,
    NetSuiteResumeConfig,
    NetSuiteTBACredentials,
    netsuite_source,
    probe,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.settings import (
    ENDPOINT_CONFIGS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Every NetSuite account has currencies, so a role that can't read them is unusual and a cheap signal.
CREDENTIALS_PROBE_TABLE = "currency"


@SourceRegistry.register
class NetSuiteSource(ResumableSource[NetSuiteSourceConfig, NetSuiteResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # SuiteQL is served from the unversioned REST `query/v1` resource.
    api_docs_url = "https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_157909186990.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NETSUITE

    @property
    def connection_host_fields(self) -> list[str]:
        # The account ID picks the host that receives the stored secrets.
        return ["account_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": AUTH_FAILED_MESSAGE,
            "403 Client Error: Forbidden for url": REST_PERMISSION_MESSAGE,
            "Search error occurred: Record": RECORD_PERMISSION_MESSAGE,
            OAUTH_REJECTED_PREFIX: None,
            INVALID_ACCOUNT_ID_MESSAGE: None,
            "The private key isn't a valid PEM private key": None,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NETSUITE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="NetSuite",
            keywords=["oracle netsuite", "suiteql", "erp"],
            caption="""Connect NetSuite to sync records with SuiteQL over REST web services.

Create an integration record in NetSuite (Setup > Integration > Manage Integrations). Then give the role you connect with the **REST Web Services** permission, the login permission for your authentication method, and view permission for each record you want to sync.

- **OAuth 2.0 (recommended):** enable the client credentials flow on the integration record, then upload a certificate in Setup > Integration > OAuth 2.0 Client Credentials (M2M) Setup. Enter the integration's client ID, the certificate ID, and the certificate's private key.
- **Token-based authentication:** for an existing integration record that uses TBA. NetSuite stops new TBA integrations in release 2027.1.""",
            iconPath="/static/services/netsuite.png",
            docsUrl="https://posthog.com/docs/cdp/sources/netsuite",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="1234567 or 1234567_SB1",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication method",
                        required=True,
                        defaultValue="oauth2",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="OAuth 2.0 client credentials",
                                value="oauth2",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="client_id",
                                            label="Client ID",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="certificate_id",
                                            label="Certificate ID",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="private_key",
                                            label="Private key",
                                            type=SourceFieldInputConfigType.TEXTAREA,
                                            required=False,
                                            placeholder="-----BEGIN PRIVATE KEY-----",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Token-based authentication",
                                value="tba",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="consumer_key",
                                            label="Consumer key",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="consumer_secret",
                                            label="Consumer secret",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                        SourceFieldInputConfig(
                                            name="token_id",
                                            label="Token ID",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                        SourceFieldInputConfig(
                                            name="token_secret",
                                            label="Token secret",
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

    def _credentials(self, config: NetSuiteSourceConfig) -> NetSuiteCredentials:
        auth = config.auth_method
        if auth.selection == "tba":
            if not (auth.consumer_key and auth.consumer_secret and auth.token_id and auth.token_secret):
                raise NetSuiteError("Enter the consumer key, consumer secret, token ID, and token secret.")
            return NetSuiteTBACredentials(
                consumer_key=auth.consumer_key,
                consumer_secret=auth.consumer_secret,
                token_id=auth.token_id,
                token_secret=auth.token_secret,
            )
        if not (auth.client_id and auth.certificate_id and auth.private_key):
            raise NetSuiteError("Enter the client ID, certificate ID, and private key.")
        return NetSuiteOAuth2Credentials(
            client_id=auth.client_id, certificate_id=auth.certificate_id, private_key=auth.private_key
        )

    def get_schemas(
        self,
        config: NetSuiteSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: NetSuiteSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINT_CONFIGS:
            return False, f"NetSuite has no table named {schema_name}"
        try:
            client = NetSuiteClient(config.account_id, self._credentials(config))
        except NetSuiteError as error:
            return False, str(error)

        result = probe(client, schema_name or CREDENTIALS_PROBE_TABLE)
        # At create, a role that can't read the probe table still proved the credentials work.
        # Per-table access shows up in the schema picker instead.
        if result.error is None or (schema_name is None and result.record_denied):
            return True, None
        return False, result.error

    def get_endpoint_permissions(
        self, config: NetSuiteSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        try:
            client = NetSuiteClient(config.account_id, self._credentials(config))
        except NetSuiteError:
            return dict.fromkeys(endpoints)

        permissions: dict[str, str | None] = {}
        for endpoint in endpoints:
            result = probe(client, endpoint) if endpoint in ENDPOINT_CONFIGS else None
            permissions[endpoint] = result.error if result is not None and result.record_denied else None
        return permissions

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NetSuiteResumeConfig]:
        return ResumableSourceManager[NetSuiteResumeConfig](inputs, NetSuiteResumeConfig)

    def source_for_pipeline(
        self,
        config: NetSuiteSourceConfig,
        resumable_source_manager: ResumableSourceManager[NetSuiteResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return netsuite_source(
            account_id=config.account_id,
            credentials=self._credentials(config),
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
