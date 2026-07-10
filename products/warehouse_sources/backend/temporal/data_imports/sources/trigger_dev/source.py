from typing import Optional, cast
from urllib.parse import urlsplit

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TriggerDevSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TRIGGER_DEV_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev.trigger_dev import (
    TriggerDevResumeConfig,
    resolve_base_url,
    trigger_dev_source,
    validate_base_url,
    validate_credentials as validate_trigger_dev_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TriggerDevSource(ResumableSource[TriggerDevSourceConfig, TriggerDevResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRIGGERDEV

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to whatever `base_url` points at, so retargeting it must re-require the
        # secret — otherwise the preserved key could be exfiltrated to an attacker-controlled host.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TRIGGER_DEV,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Trigger.dev",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Trigger.dev secret API key to sync your task run history into the PostHog Data warehouse.

API keys are per environment (dev / staging / prod), so one connection syncs one environment. Copy the secret key for the environment you want from your [Trigger.dev project's API keys page](https://trigger.dev/docs/apikeys).
""",
            iconPath="/static/services/trigger_dev.png",
            docsUrl="https://posthog.com/docs/cdp/sources/trigger-dev",
            keywords=["background jobs", "workflows", "task runs", "queues"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="tr_prod_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="base_url",
                        label="API URL (self-hosted only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://api.trigger.dev",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid, revoked, or wrong-environment secret key surfaces as a requests HTTPError
            # when `_fetch_page` calls `raise_for_status()`. Retrying can never satisfy a credential
            # problem, so stop the sync. The base host varies for self-hosted instances, so match on
            # the stable status text only.
            "401 Client Error": "Your Trigger.dev API key is invalid or has been revoked. Copy a valid secret key from your Trigger.dev project settings, then reconnect.",
            "403 Client Error": "Your Trigger.dev API key does not have access to this data. Check the key's environment and permissions, then reconnect.",
            "Invalid API key": "Your Trigger.dev API key is invalid or has been revoked. Copy a valid secret key from your Trigger.dev project settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: TriggerDevSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=TRIGGER_DEV_ENDPOINTS[endpoint].should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TriggerDevSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        base_url = resolve_base_url(config.base_url)
        url_error = validate_base_url(base_url)
        if url_error:
            return False, url_error
        host = urlsplit(base_url).hostname or ""
        host_ok, host_error = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_error
        return validate_trigger_dev_credentials(config.api_key, base_url)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TriggerDevResumeConfig]:
        return ResumableSourceManager[TriggerDevResumeConfig](inputs, TriggerDevResumeConfig)

    def source_for_pipeline(
        self,
        config: TriggerDevSourceConfig,
        resumable_source_manager: ResumableSourceManager[TriggerDevResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        base_url = resolve_base_url(config.base_url)
        url_error = validate_base_url(base_url)
        if url_error:
            raise ValueError(url_error)
        host = urlsplit(base_url).hostname or ""
        host_ok, host_error = _is_host_safe(host, inputs.team_id)
        if not host_ok:
            raise ValueError(host_error or "Trigger.dev host is not allowed")

        return trigger_dev_source(
            api_key=config.api_key,
            base_url=base_url,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
