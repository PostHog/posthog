from typing import Optional, cast

from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    detect,
)
from products.warehouse_sources.sources.svix._config import SvixSourceConfig
from products.warehouse_sources.sources.svix.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    INCREMENTAL_LOOKBACK_SECONDS,
    SVIX_ENDPOINTS,
)
from products.warehouse_sources.sources.svix.svix import SvixResumeConfig, svix_source, validate_credentials


@SourceRegistry.register
class SvixSource(ResumableSource[SvixSourceConfig, SvixResumeConfig]):
    codebase_detection = detect(
        env=("^SVIX_",),
        npm=("svix",),
        pypi=("svix",),
        cargo=("svix", "svix-ksuid"),
        composer=("svix/svix",),
        go=("github.com/svix/svix-webhooks",),
        maven=("com.svix:svix", "com.svix.kotlin:svix-kotlin"),
        rubygems=("svix",),
    )

    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.svix.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SVIX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SVIX,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Svix",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your Svix API key to pull your webhook platform data into the PostHog Data warehouse.

You can create an API key under **Settings → API Access** in the [Svix dashboard](https://dashboard.svix.com/). The region is encoded in the key (the `sk_` prefix), so use the key for the environment you want to sync. The key grants read access to your applications, event types, endpoints, messages and delivery attempts.
""",
            iconPath="/static/services/svix.png",
            docsUrl="https://posthog.com/docs/cdp/sources/svix",
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.svix.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,  # noqa: PLC0415
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.svix.com": "Your Svix API key is invalid or has been revoked. Generate a new key under Settings → API Access, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.svix.com": "Your Svix API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: SvixSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Messages and attempts sync incrementally on `timestamp` by walking newest first to the
        # watermark. The other list endpoints expose no updated-since filter, so they are full refresh.
        schemas = []
        for endpoint in ENDPOINTS:
            incremental_fields = INCREMENTAL_FIELDS.get(endpoint, [])
            schemas.append(
                SourceSchema(
                    name=endpoint,
                    supports_incremental=bool(incremental_fields),
                    # The lookback re-reads rows, so only merge keeps them unique.
                    supports_append=False,
                    incremental_fields=incremental_fields,
                    default_incremental_lookback_seconds=INCREMENTAL_LOOKBACK_SECONDS if incremental_fields else None,
                )
            )
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SvixSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key)

    def resume_covers_run(self, *, incremental_or_append: bool, schema_name: str | None = None) -> bool:
        # A two-level fan-out (applications -> endpoints -> child) carries no resume state.
        config = SVIX_ENDPOINTS.get(schema_name or "")
        return config is None or config.parent != "endpoints"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SvixResumeConfig]:
        return ResumableSourceManager[SvixResumeConfig](inputs, SvixResumeConfig)

    def source_for_pipeline(
        self,
        config: SvixSourceConfig,
        resumable_source_manager: ResumableSourceManager[SvixResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SVIX_ENDPOINTS:
            raise ValueError(f"Unknown Svix schema '{inputs.schema_name}'")

        return svix_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=(
                inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None
            ),
        )
