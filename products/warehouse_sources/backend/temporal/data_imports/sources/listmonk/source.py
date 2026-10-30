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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.listmonk import (
    ListmonkSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.listmonk.listmonk import (
    ListmonkResumeConfig,
    hostname_of,
    listmonk_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.listmonk.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ListmonkSource(ResumableSource[ListmonkSourceConfig, ListmonkResumeConfig], ValidateDatabaseHostMixin):
    codebase_detection = detect(env=("^LISTMONK_",), go=("github.com/knadh/listmonk",))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://listmonk.app/docs/apis/apis/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LISTMONK

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API token is sent to `host`, so retargeting it must re-require the token.
        return ["host"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LISTMONK,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Listmonk",
            caption="""Sync subscribers, lists, campaigns, bounces and daily campaign analytics from your Listmonk instance.

Create an API user in Listmonk under **Admin > Users** and copy its token. Its role needs `subscribers:get_all`, `lists:get_all`, `campaigns:get_all`, `bounces:get` and `campaigns:get_analytics`. Incremental sync of subscribers also needs `subscribers:sql_query`.""",
            iconPath="/static/services/listmonk.png",
            docsUrl="https://posthog.com/docs/cdp/sources/listmonk",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://listmonk.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_user",
                        label="API user",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="posthog",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.listmonk.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Listmonk rejected the API user or token. Create a new token under Admin > Users, then reconnect the source.",
            "403 Client Error: Forbidden for url": "The Listmonk API user's role lacks a permission this table needs. Check the permissions listed in the source setup, grant the missing one, or deselect the table.",
            "internal or private IP address": "The Listmonk instance URL resolves to an internal or private IP address, which PostHog can't reach. Use your instance's public URL, then reconnect.",
            "Invalid Listmonk instance URL": "The Listmonk instance URL is not valid. Enter the address of your instance, such as https://listmonk.example.com.",
            "Listmonk instance URL must use https": "The Listmonk instance URL must use https. Update the URL, then reconnect the source.",
        }

    def get_schemas(
        self,
        config: ListmonkSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def _check_host(self, host: str, team_id: int) -> str | None:
        try:
            is_valid, error = self.is_database_host_valid(hostname_of(host), team_id)
        except ValueError as e:
            return str(e)
        if is_valid:
            return None
        if error and "internal or private IP address" in error:
            # The shared message suggests an SSH tunnel, which this source does not offer.
            return "The Listmonk instance URL resolves to an internal or private IP address, which PostHog can't reach. Use your instance's public URL."
        return error or "Invalid Listmonk instance URL"

    def validate_credentials(
        self,
        config: ListmonkSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        host_error = self._check_host(config.host, team_id)
        if host_error is not None:
            return False, host_error

        is_valid, status = probe_credentials(config.host, config.api_user, config.api_token)
        if is_valid:
            return True, None
        if status in (401, 403):
            return False, "Listmonk rejected the API user or token. Check both, and that the user can read lists."
        return False, "Couldn't reach your Listmonk instance. Check the instance URL, then try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ListmonkResumeConfig]:
        return ResumableSourceManager[ListmonkResumeConfig](inputs, ListmonkResumeConfig)

    def source_for_pipeline(
        self,
        config: ListmonkSourceConfig,
        resumable_source_manager: ResumableSourceManager[ListmonkResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host_error = self._check_host(config.host, inputs.team_id)
        if host_error is not None:
            raise ValueError(host_error)

        return listmonk_source(
            host=config.host,
            api_user=config.api_user,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
