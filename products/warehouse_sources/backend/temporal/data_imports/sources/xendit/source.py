from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xendit import XenditSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SHOULD_SYNC_DEFAULT,
    XENDIT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.xendit import (
    XenditResumeConfig,
    validate_credentials as validate_xendit_credentials,
    xendit_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

TRANSACTIONS_ENDPOINT = "transactions"


@SourceRegistry.register
class XenditSource(ResumableSource[XenditSourceConfig, XenditResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Xendit has no account-wide API version: the endpoints this source calls take no version
    # header or version query param, and the `/v2` path segment on the accounts endpoint is part of
    # that endpoint's path rather than a version the caller picks. So the unversioned default stands.
    api_docs_url = "https://docs.xendit.co/api-reference/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.XENDIT

    @property
    def connection_host_fields(self) -> list[str]:
        # `sub_account_user_id` picks which xenPlatform sub-account the stored key reads via the
        # `for-user-id` header, so retargeting it must re-require the key.
        return ["sub_account_user_id"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Xendit API key is invalid or has been revoked. Create a new secret key in the Xendit dashboard and reconnect.",
            "403 Client Error: Forbidden for url": "Your Xendit API key is missing the permission this table needs. Update the key's permissions in the Xendit dashboard and try again.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.XENDIT,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Xendit",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Xendit secret API key to sync your Xendit data into the PostHog Data warehouse.

Create a key in the Xendit dashboard under **Settings > Developers > API keys**. Give it the **Transaction Read** permission to sync transactions, and **Accounts Read** if you also want to sync xenPlatform sub-accounts.""",
            iconPath="/static/services/xendit.png",
            docsUrl="https://posthog.com/docs/cdp/sources/xendit",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="sub_account_user_id",
                        label="Sub-account user ID (xenPlatform only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: XenditSourceConfig,
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
            should_sync_default=SHOULD_SYNC_DEFAULT,
        )

    def validate_credentials(
        self,
        config: XenditSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        endpoint = XENDIT_ENDPOINTS.get(schema_name or TRANSACTIONS_ENDPOINT, XENDIT_ENDPOINTS[TRANSACTIONS_ENDPOINT])
        _reachable, status = validate_xendit_credentials(config.api_key, endpoint.path, config.sub_account_user_id)

        if status == 200:
            return True, None
        # A 403 means the key is genuine but lacks that endpoint's permission. At source creation
        # that's fine, since a user may only grant the permissions for the tables they want, so
        # reject it only when a specific table is being checked.
        if status == 403:
            if schema_name is None:
                return True, None
            return False, f"Your Xendit API key is missing the {endpoint.permission} permission"

        return False, "Invalid Xendit API key"

    def get_endpoint_permissions(
        self,
        config: XenditSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        permissions: dict[str, str | None] = {}
        for name in endpoints:
            endpoint = XENDIT_ENDPOINTS.get(name)
            if endpoint is None:
                permissions[name] = None
                continue
            _reachable, status = validate_xendit_credentials(config.api_key, endpoint.path, config.sub_account_user_id)
            # Only an outright denial counts as a missing permission; a throttle, a 5xx or a
            # network blip does not, so those leave the table selectable.
            permissions[name] = (
                f"Your Xendit API key is missing the {endpoint.permission} permission" if status == 403 else None
            )
        return permissions

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[XenditResumeConfig]:
        return ResumableSourceManager[XenditResumeConfig](inputs, XenditResumeConfig)

    def source_for_pipeline(
        self,
        config: XenditSourceConfig,
        resumable_source_manager: ResumableSourceManager[XenditResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return xendit_source(
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
            for_user_id=config.sub_account_user_id,
        )
