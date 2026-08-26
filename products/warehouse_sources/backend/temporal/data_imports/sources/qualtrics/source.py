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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qualtrics import (
    QualtricsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics.qualtrics import (
    EXPORT_FAILED_ERROR,
    HOST_NOT_ALLOWED_ERROR,
    INCOMPLETE_CREDENTIALS_ERROR,
    QualtricsCredentials,
    QualtricsResumeConfig,
    qualtrics_source,
    validate_credentials as validate_qualtrics_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    QUALTRICS_API_VERSION,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _credentials_from_config(config: QualtricsSourceConfig) -> QualtricsCredentials:
    auth = config.auth_method
    if auth.selection == "oauth_client_credentials":
        return QualtricsCredentials(
            method="oauth_client_credentials",
            client_id=auth.client_id,
            client_secret=auth.client_secret,
        )
    return QualtricsCredentials(method="api_token", api_token=auth.api_token)


@SourceRegistry.register
class QualtricsSource(ResumableSource[QualtricsSourceConfig, QualtricsResumeConfig]):
    supported_versions = (QUALTRICS_API_VERSION,)
    default_version = QUALTRICS_API_VERSION
    api_docs_url = "https://api.qualtrics.com/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QUALTRICS

    @property
    def connection_host_fields(self) -> list[str]:
        # `datacenter_id` decides which host the stored credentials are sent to, so retargeting
        # it must re-require them.
        return ["datacenter_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.QUALTRICS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Qualtrics",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["surveys", "xm", "experience management"],
            caption="""Enter your Qualtrics datacenter ID and credentials to pull surveys, responses and account metadata into the PostHog Data warehouse.

Find your datacenter ID under **Account settings > Qualtrics IDs**. It looks like `iad1` or `fra1`. If your brand uses a custom domain, paste the full hostname instead.

The quickest way to connect is an API token from **Account settings > Qualtrics IDs**. The Qualtrics user needs the "Access API" permission plus read access to the surveys, users, groups, divisions and distributions you want to sync.

You can also connect with an OAuth client: create one under **Account settings > Qualtrics IDs**, pick the client credentials grant, and give it read access to surveys, survey responses, survey definitions, users, groups, divisions and distributions.

Survey responses sync incrementally on `recordedDate`. Every other table is a full refresh, because Qualtrics has no modified-since filter on its collection endpoints.
""",
            iconPath="/static/services/qualtrics.png",
            docsUrl="https://posthog.com/docs/cdp/sources/qualtrics",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="datacenter_id",
                        label="Datacenter ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="iad1",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication method",
                        required=True,
                        defaultValue="api_token",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="API token",
                                value="api_token",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="api_token",
                                            label="API token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="OAuth client credentials",
                                value="oauth_client_credentials",
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
                                            name="client_secret",
                                            label="Client secret",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid or expired Qualtrics credentials. Please re-enter them and reconnect.",
            "403 Client Error": "Your Qualtrics credentials lack permission for this data. Grant the user or OAuth client read access and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Qualtrics host is not allowed. Please use your brand's datacenter ID.",
            INCOMPLETE_CREDENTIALS_ERROR: "Qualtrics credentials are incomplete. Please re-enter them and reconnect.",
            EXPORT_FAILED_ERROR: "Qualtrics could not build the response export. Please check the survey and try again.",
        }

    def get_schemas(
        self,
        config: QualtricsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            # A response can be restated (a partial response finished later is re-exported
            # under the same id), so merge is the only safe incremental mode.
            merge_only=("survey_responses",),
        )

    def validate_credentials(
        self,
        config: QualtricsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_qualtrics_credentials(
            datacenter_id=config.datacenter_id,
            credentials=_credentials_from_config(config),
            api_version=self.resolve_api_version(api_version),
            schema_name=schema_name,
            team_id=team_id,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[QualtricsResumeConfig]:
        return ResumableSourceManager[QualtricsResumeConfig](inputs, QualtricsResumeConfig)

    def source_for_pipeline(
        self,
        config: QualtricsSourceConfig,
        resumable_source_manager: ResumableSourceManager[QualtricsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return qualtrics_source(
            datacenter_id=config.datacenter_id,
            credentials=_credentials_from_config(config),
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
