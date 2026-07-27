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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shutterstock import (
    ShutterstockSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SHUTTERSTOCK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.shutterstock import (
    ShutterstockAuth,
    ShutterstockResumeConfig,
    check_endpoint_access,
    shutterstock_source,
    validate_credentials as validate_shutterstock_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _auth_from_config(config: ShutterstockSourceConfig) -> ShutterstockAuth:
    if config.auth_method.selection == "access_token":
        return ShutterstockAuth(access_token=config.auth_method.access_token)
    return ShutterstockAuth(
        consumer_key=config.auth_method.consumer_key,
        consumer_secret=config.auth_method.consumer_secret,
    )


@SourceRegistry.register
class ShutterstockSource(ResumableSource[ShutterstockSourceConfig, ShutterstockResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://api-reference.shutterstock.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHUTTERSTOCK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SHUTTERSTOCK,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Shutterstock",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["stock photos", "stock media"],
            caption="""Pull your Shutterstock media catalog and account data into the PostHog Data warehouse.

Authenticate with your app's consumer key and secret (from [your Shutterstock apps page](https://www.shutterstock.com/account/developers/apps)) to sync the catalog feeds: categories and recently updated images and videos.

To also sync account-level tables, use an OAuth access token instead. Collections need the `collections.view` scope, license history needs `licenses.view`, and subscriptions need `purchases.view`. Note that Shutterstock invalidates OAuth tokens when the account password changes, so you may need to reconnect after a password change.""",
            iconPath="/static/services/shutterstock.png",
            docsUrl="https://posthog.com/docs/cdp/sources/shutterstock",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication type",
                        required=True,
                        defaultValue="api_key",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Consumer key and secret",
                                value="api_key",
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
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="OAuth access token",
                                value="access_token",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="access_token",
                                            label="Access token",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Bad, revoked, or password-invalidated credentials surface as HTTPErrors from
            # `raise_for_status()`. Retrying can never fix a credential problem. Match the
            # stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.shutterstock.com": "Your Shutterstock credentials are invalid or expired. OAuth tokens are invalidated when the account password changes. Reconnect with fresh credentials.",
            "403 Client Error: Forbidden for url: https://api.shutterstock.com": "Your Shutterstock credentials do not have access to this data. Account-level tables (collections, licenses, subscriptions) need an OAuth access token with the matching scope.",
        }

    def get_schemas(
        self,
        config: ShutterstockSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ShutterstockSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        auth = _auth_from_config(config)
        if schema_name is not None and schema_name in SHUTTERSTOCK_ENDPOINTS:
            reason = check_endpoint_access(auth, schema_name)
            if reason is not None:
                return False, reason
            return True, None

        if validate_shutterstock_credentials(auth):
            return True, None

        return False, "Invalid Shutterstock credentials"

    def get_endpoint_permissions(
        self, config: ShutterstockSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        auth = _auth_from_config(config)
        return {
            endpoint: check_endpoint_access(auth, endpoint) if endpoint in SHUTTERSTOCK_ENDPOINTS else None
            for endpoint in endpoints
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ShutterstockResumeConfig]:
        return ResumableSourceManager[ShutterstockResumeConfig](inputs, ShutterstockResumeConfig)

    def source_for_pipeline(
        self,
        config: ShutterstockSourceConfig,
        resumable_source_manager: ResumableSourceManager[ShutterstockResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return shutterstock_source(
            auth=_auth_from_config(config),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
