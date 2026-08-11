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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gumroad import (
    GumroadSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.gumroad import (
    GumroadResumeConfig,
    check_endpoint_permission,
    gumroad_source,
    validate_credentials as validate_gumroad_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.settings import (
    ENDPOINTS,
    GUMROAD_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GumroadSource(ResumableSource[GumroadSourceConfig, GumroadResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://gumroad.com/api"

    # Deliberately not a `WebhookSource`: Gumroad's resource subscriptions are API-manageable, but
    # every delivery is sent as `application/x-www-form-urlencoded` (the JSON content type is only
    # assigned to zapier.com endpoints, and no API parameter overrides it) and the ping payload
    # names its fields differently from the REST sale object, so webhook rows could not merge into
    # the polled tables. Deltas come from the incremental `after` window instead.

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GUMROAD

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Gumroad rejected the access token. Generate a new one under Settings > Advanced > Applications and reconnect.",
            "403 Client Error: Forbidden for url": "The Gumroad access token is missing a scope required for this table. Reconnect with a token that has access to the tables you're syncing.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gumroad.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GumroadSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: GumroadSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_gumroad_credentials(config.access_token)

    def get_endpoint_permissions(
        self,
        config: GumroadSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        # Gumroad scopes are per-resource, so a token can read products while being refused sales
        # or payouts. Probe each distinct path once and reuse the verdict for the tables sharing it.
        results: dict[str, str | None] = {}
        probed: dict[str, bool] = {}
        for name in endpoints:
            endpoint_config = GUMROAD_ENDPOINTS.get(name)
            if endpoint_config is None:
                results[name] = None
                continue

            path = endpoint_config.permission_probe_path
            if path not in probed:
                probed[path] = check_endpoint_permission(config.access_token, path)

            results[name] = (
                None
                if probed[path]
                else f"Your Gumroad access token is missing the {endpoint_config.required_scope} scope."
            )
        return results

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GumroadResumeConfig]:
        return ResumableSourceManager[GumroadResumeConfig](inputs, GumroadResumeConfig)

    def source_for_pipeline(
        self,
        config: GumroadSourceConfig,
        resumable_source_manager: ResumableSourceManager[GumroadResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gumroad_source(
            access_token=config.access_token,
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

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GUMROAD,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Gumroad",
            caption=(
                "Import sales, products, payouts, subscribers, reviews, offer codes, versions, and "
                "custom fields from your Gumroad account.\n\n"
                "Create an application under Settings > Advanced > Applications, then generate an "
                "access token for it. The token needs the `view_sales`, `view_payouts`, and "
                "`view_public` scopes."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/gumroad",
            iconPath="/static/services/gumroad.png",
            keywords=["antiwork", "creator", "digital products"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
