from typing import Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.medusa import MedusaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.medusa.medusa import (
    HTTPS_REQUIRED_ERROR,
    INVALID_URL_ERROR,
    PAGINATION_LIMIT_ERROR,
    MedusaResumeConfig,
    hostname_of,
    medusa_source,
    validate_credentials as validate_medusa_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.medusa.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MEDUSA_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

CAPTION = """Sync orders, products, customers and more from your self-hosted Medusa server into the PostHog Data warehouse.

Requires Medusa v2. Create a secret API key in your Medusa Admin dashboard under **Settings > Secret API Keys**, then enter it here with your server's URL. Publishable API keys only work with the Store API and will not work here."""

REJECTED_KEY_MESSAGE = "Medusa rejected the API key. Check that you're using a secret API key from a Medusa v2 server, not a publishable key."


@SourceRegistry.register
class MedusaSource(ResumableSource[MedusaSourceConfig, MedusaResumeConfig], ValidateDatabaseHostMixin):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs

    # The v2 Admin API carries no version token on the wire (no version path segment, header,
    # or param); v2 names the Medusa platform generation whose route shapes and `[$gte]` filter
    # syntax this source targets. Medusa v1 servers use different routes and auth, and the
    # credential probe fails against them.
    api_docs_url = "https://docs.medusajs.com/api/admin"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MEDUSA

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored secret API key is sent to `base_url`; retargeting it must re-require the
        # key so an editor can't exfiltrate it to a host they control.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MEDUSA,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Medusa",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=CAPTION,
            iconPath="/static/services/medusa.png",
            docsUrl="https://posthog.com/docs/cdp/sources/medusa",
            keywords=["commerce", "ecommerce", "medusajs"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Medusa server URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://store.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The URL carries the merchant's own host, so match on the status prefix only.
        return {
            "401 Client Error": f"{REJECTED_KEY_MESSAGE} Then reconnect.",
            "403 Client Error": "The API key does not have access to this data. Check the key in your Medusa Admin dashboard, then reconnect.",
            HTTPS_REQUIRED_ERROR: "The Medusa server URL must use HTTPS so your API key is not sent in the clear. Update the server URL and reconnect.",
            INVALID_URL_ERROR: "The Medusa server URL is invalid. Enter your server's public URL, e.g. https://store.example.com, and reconnect.",
            PAGINATION_LIMIT_ERROR: "Medusa kept returning pages without reaching the total it reported. Check that the server URL points at your Medusa server.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.medusa.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MedusaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Commerce rows are rewritten in place (an order's status advances, a product's price
        # changes), so append mode would duplicate them; merge is the only incremental mode.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self,
        config: MedusaSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            hostname = hostname_of(config.base_url)
        except ValueError as e:
            return False, str(e)

        host_valid, host_error = self.is_database_host_valid(hostname, team_id)
        if not host_valid:
            return False, host_error

        ok, status = validate_medusa_credentials(config.base_url, config.api_key)
        if ok:
            return True, None
        # Secret API keys act as the admin user they belong to, so 403 at create still means
        # the key can't read the store's data; there are no per-endpoint scopes to defer to.
        if status in (401, 403):
            return False, REJECTED_KEY_MESSAGE
        return (
            False,
            "Couldn't connect to the Medusa server. Check the server URL and that the server is reachable, then try again.",
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MedusaResumeConfig]:
        return ResumableSourceManager[MedusaResumeConfig](inputs, MedusaResumeConfig)

    def source_for_pipeline(
        self,
        config: MedusaSourceConfig,
        resumable_source_manager: ResumableSourceManager[MedusaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in MEDUSA_ENDPOINTS:
            raise ValueError(f"Unknown Medusa schema '{inputs.schema_name}'")

        return medusa_source(
            base_url=config.base_url,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field_name=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
