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
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.devin_ai import (
    DevinAIResumeConfig,
    devin_ai_source,
    validate_credentials as validate_devin_ai_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.settings import (
    DEVIN_AI_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DevinAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DevinAISource(ResumableSource[DevinAISourceConfig, DevinAIResumeConfig]):
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://docs.devin.ai/api-reference"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEVINAI

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API key is sent against whatever `org_id` is configured, so changing it retargets
        # the saved credential at a different Devin organization — force secret re-entry on a change.
        return ["org_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DEVIN_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Devin AI",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Devin service user API key and organization ID to sync your Devin data into the PostHog Data warehouse.

Create a service user API key (prefixed `cog_`) in your [Devin organization settings](https://app.devin.ai/settings). The service user needs the following organization-level permissions:
- `ViewOrgSessions` — Sessions
- `ManageAccountKnowledge` — Playbooks and Knowledge notes
- `ManageOrgSecrets` — Secrets (metadata only; values are never synced)

Your organization ID is the `org-...` identifier shown in your Devin organization settings.""",
            iconPath="/static/services/devin_ai.png",
            docsUrl="https://posthog.com/docs/cdp/sources/devin-ai",
            keywords=["devin", "cognition", "cognition ai"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="cog_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="org_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="org-...",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A revoked/invalid key or a key missing the endpoint's RBAC permission surfaces as a
            # requests HTTPError from `raise_for_status()`. Retrying can't fix a credential problem, so
            # stop the sync. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.devin.ai": "Your Devin API key is invalid or has been revoked. Create a new service user API key in your Devin organization settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.devin.ai": "Your Devin service user is missing the organization permission needed to sync this data. Grant the required permission in your Devin organization settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: DevinAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Devin's v3 list endpoints expose no verified server-side timestamp filter, so every table is
        # full refresh only (see settings.py). Cursor pagination still makes each sync resumable.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=DEVIN_AI_ENDPOINTS[endpoint].primary_keys,
                should_sync_default=DEVIN_AI_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: DevinAISourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Probe the specific table when checking a schema; otherwise probe Sessions as a cheap token check.
        endpoint = schema_name if schema_name in DEVIN_AI_ENDPOINTS else "sessions"
        try:
            status = validate_devin_ai_credentials(config.api_key, config.org_id, endpoint)
        except Exception:
            return False, "Could not reach the Devin API. Check your network connection and try again."

        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid Devin API key. Check your service user key and organization ID, then reconnect."
        if status == 403:
            # A valid key may legitimately lack the scope for some tables. Accept it at source-create so
            # the user can still sync the tables they do have access to; only fail the per-schema check.
            if schema_name is None:
                return True, None
            return (
                False,
                f"Your Devin service user is missing the organization permission required to sync '{schema_name}'.",
            )
        if status == 404:
            return False, "Organization not found. Check that your Devin organization ID is correct."
        return False, f"Unexpected response from the Devin API (status {status})."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DevinAIResumeConfig]:
        return ResumableSourceManager[DevinAIResumeConfig](inputs, DevinAIResumeConfig)

    def source_for_pipeline(
        self,
        config: DevinAISourceConfig,
        resumable_source_manager: ResumableSourceManager[DevinAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return devin_ai_source(
            api_key=config.api_key,
            org_id=config.org_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
