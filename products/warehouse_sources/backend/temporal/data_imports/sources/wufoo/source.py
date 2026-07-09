from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WufooSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.wufoo import (
    SUBDOMAIN_REGEX,
    WufooResumeConfig,
    validate_credentials as validate_wufoo_credentials,
    wufoo_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WufooSource(ResumableSource[WufooSourceConfig, WufooResumeConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to
    # render in public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WUFOO

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to <subdomain>.wufoo.com, so retargeting the subdomain on an existing
        # source must force the key to be re-entered.
        return ["subdomain"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Auth failures surface as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the
            # sync. The host is subdomain-specific, so match the stable status text only.
            "401 Client Error: Unauthorized for url": "Your Wufoo API key is invalid, or the subdomain is wrong. Check both under Account → API Information and reconnect.",
            "403 Client Error: Forbidden for url": "Your Wufoo API key does not have permission for this resource. Check that API access is enabled for the account.",
        }

    def get_schemas(
        self,
        config: WufooSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Wufoo's account-level list endpoints expose no
        # server-side timestamp filter, so there is no incremental cursor to advance.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: WufooSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not SUBDOMAIN_REGEX.match(config.subdomain):
            return False, "Wufoo subdomain is invalid"

        status = validate_wufoo_credentials(config.api_key, config.subdomain)

        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid Wufoo credentials. Check your subdomain and API key under Account → API Information."
        return False, "Could not connect to Wufoo. Please check your subdomain and API key."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WufooResumeConfig]:
        return ResumableSourceManager[WufooResumeConfig](inputs, WufooResumeConfig)

    def source_for_pipeline(
        self,
        config: WufooSourceConfig,
        resumable_source_manager: ResumableSourceManager[WufooResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return wufoo_source(
            api_key=config.api_key,
            subdomain=config.subdomain,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WUFOO,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Wufoo",
            caption="""Enter your Wufoo subdomain and API key to pull your Wufoo form data into the PostHog Data warehouse.

Your **subdomain** is the account name in your Wufoo URL — e.g. `acme` for `acme.wufoo.com`.

Your **API key** is on the **API Information** page of any form (log in, open a form in the Form Manager, then click **API Information**). The same key works across every form on the account.""",
            iconPath="/static/services/wufoo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/wufoo",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
