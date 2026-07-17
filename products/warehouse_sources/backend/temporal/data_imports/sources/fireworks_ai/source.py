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
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.fireworks_ai import (
    FireworksAIResumeConfig,
    fireworks_ai_source,
    get_status_code,
    is_valid_account_id,
    normalize_account_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import (
    ENDPOINTS,
    FIREWORKS_AI_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FireworksAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FireworksAISource(ResumableSource[FireworksAISourceConfig, FireworksAIResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.fireworks.ai/api-reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIREWORKSAI

    @property
    def connection_host_fields(self) -> list[str]:
        # account_id selects which Fireworks account the stored API key is used against; changing
        # it must require re-entering the secret so a preserved key can't be retargeted at another
        # account the key happens to have access to.
        return ["account_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FIREWORKS_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Fireworks AI",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Fireworks AI API key and account ID to sync your models, datasets, deployments, fine-tuning jobs, batch inference jobs, evaluations, and account users into the PostHog Data warehouse.

You can find or create an API key in your [Fireworks AI account settings](https://app.fireworks.ai/settings/users/api-keys). Your account ID is shown in your account settings and in every resource name (`accounts/<account-id>/...`).""",
            iconPath="/static/services/fireworks_ai.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/fireworks-ai",
            keywords=["fireworks", "llm", "inference", "fine-tuning", "ai"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-account",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.canonical_descriptions import (  # noqa: PLC0415 — lazy import per the source architecture contract
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid/revoked key surfaces as a requests HTTPError rebuilt from scheme/host/path
            # (see fireworks_ai._fetch). Match the stable status text and base host.
            "401 Client Error: Unauthorized for url: https://api.fireworks.ai": "Your Fireworks AI API key is invalid or has been revoked. Create a new API key in your Fireworks AI account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.fireworks.ai": "Your Fireworks AI API key does not have permission to access this data. Check that the account ID matches the key's account and that the key has read access, then reconnect.",
            "404 Client Error: Not Found for url: https://api.fireworks.ai": "Fireworks AI could not find this resource. Check that the account ID is correct, then reconnect.",
        }

    def get_schemas(
        self,
        config: FireworksAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The API documents an AIP-160 `filter` param but not its filterable fields, and we could
        # not verify server-side timestamp filtering, so every table is full refresh only
        # (see settings.py).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=FIREWORKS_AI_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: FireworksAISourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        account_id = normalize_account_id(config.account_id)
        if not is_valid_account_id(account_id):
            return False, "Fireworks AI account ID is invalid. Copy it from your Fireworks AI account settings."

        try:
            status = get_status_code(config.api_key, account_id, schema_name)
        except Exception:
            return False, "Could not reach the Fireworks AI API. Check your network connection and try again."

        if status == 200:
            return True, None
        if status == 401:
            return (
                False,
                "Invalid Fireworks AI API key. Check the key in your Fireworks AI account settings, then reconnect.",
            )
        if status == 404:
            return False, "Fireworks AI account not found. Check the account ID and try again."
        if status == 403:
            # Accept a valid-but-restricted key at source-create so the user can still sync the
            # tables the key can reach; only fail the per-schema check.
            if schema_name is None:
                return True, None
            return False, f"Your Fireworks AI API key does not have permission to sync '{schema_name}'."
        return False, f"Unexpected response from the Fireworks AI API (status {status})."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FireworksAIResumeConfig]:
        return ResumableSourceManager[FireworksAIResumeConfig](inputs, FireworksAIResumeConfig)

    def source_for_pipeline(
        self,
        config: FireworksAISourceConfig,
        resumable_source_manager: ResumableSourceManager[FireworksAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return fireworks_ai_source(
            api_key=config.api_key,
            account_id=config.account_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
