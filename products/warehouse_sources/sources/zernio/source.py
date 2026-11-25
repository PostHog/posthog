from typing import Optional, cast

from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceKey,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
    source_key,
)
from products.warehouse_sources.sources.zernio._config import ZernioSourceConfig
from products.warehouse_sources.sources.zernio.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.sources.zernio.zernio import (
    ZernioResumeConfig,
    validate_credentials as validate_zernio_credentials,
    zernio_source,
)

SOURCE_KEY = "Zernio"

# Zernio writes `updatedAt` when it saves a change, so a write that commits after a sync read can
# carry an `updatedAt` below that sync's highest value. Each incremental sync reads 5 minutes back.
INCREMENTAL_LOOKBACK_SECONDS = 5 * 60


@SourceRegistry.register
class ZernioSource(ResumableSource[ZernioSourceConfig, ZernioResumeConfig]):
    codebase_detection = detect(
        env=("^ZERNIO_",),
        npm=("@zernio/node",),
        pypi=("zernio-sdk",),
        go=("github.com/zernio-dev/zernio-go",),
        rubygems=("zernio-sdk",),
        maven=("com.zernio:zernio-sdk",),
        composer=("zernio-dev/zernio-php",),
        cargo=("zernio",),
    )

    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    # Zernio versions every endpoint in the URL path and `v1` is the only version.
    api_docs_url = "https://docs.zernio.com/changelog"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            keywords=["late", "getlate", "social media"],
            label="Zernio",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your Zernio API key to pull your profiles, connected accounts, posts, contacts, inbox conversations and ads into the PostHog Data warehouse.

Create a key on the [API keys](https://zernio.com/dashboard/api-keys) page of the Zernio dashboard. The key starts with `sk_`.

The inbox conversations table needs the Zernio Inbox add-on, and the ads table needs ads access on your plan.
""",
            iconPath="/static/warehouse-sources/zernio/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zernio",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": (
                "Zernio didn't accept your API key. Create a new key on the API keys page of the Zernio "
                "dashboard, then reconnect the source."
            ),
            "403 Client Error: Forbidden": (
                "Your Zernio plan or API key can't read this table. Inbox conversations need the Inbox "
                "add-on and ads need ads access. Turn off the table or upgrade your Zernio plan."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.zernio.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ZernioSourceConfig,
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
            default_incremental_lookback_seconds={
                name: INCREMENTAL_LOOKBACK_SECONDS for name, fields in INCREMENTAL_FIELDS.items() if fields
            },
        )

    def validate_credentials(
        self,
        config: ZernioSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_zernio_credentials(config.api_key, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZernioResumeConfig]:
        return ResumableSourceManager[ZernioResumeConfig](inputs, ZernioResumeConfig).with_namespace(inputs.schema_name)

    def source_for_pipeline(
        self,
        config: ZernioSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZernioResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return zernio_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
