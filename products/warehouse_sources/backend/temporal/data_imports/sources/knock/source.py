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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.knock import KnockSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.knock import (
    NO_AUDIENCE_KEYS_ERROR,
    NO_OBJECT_COLLECTIONS_ERROR,
    KnockResumeConfig,
    knock_source,
    parse_key_list,
    validate_credentials as validate_knock_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.settings import (
    ENDPOINTS,
    ENDPOINTS_CONFIG,
    INCREMENTAL_FIELDS,
    INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KnockSource(ResumableSource[KnockSourceConfig, KnockResumeConfig]):
    codebase_detection = detect(
        env=("^KNOCK_", "^NEXT_PUBLIC_KNOCK_"),
        npm=("@knocklabs/node", "@knocklabs/client", "@knocklabs/react", "@knocklabs/react-native"),
        pypi=("knockapi",),
        cocoapods=("Knock",),
        composer=("knocklabs/knock-php",),
        go=("github.com/knocklabs/knock-go", "github.com/knocklabs/knock-mgmt-go"),
        hex=("knock",),
        maven=(
            "app.knock.api:knock-java",
            "app.knock.api:knock-client",
            "app.knock.api:knock-java-client-okhttp",
            "app.knock.api:knock-java-core",
        ),
        pub=("knock_flutter",),
        rubygems=("knockapi",),
        swiftpm=("github.com/knocklabs/knock-swift",),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.knock.app/api-reference/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KNOCK

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Knock API key is invalid or has been revoked. Please generate a new secret key in the Knock dashboard and reconnect.",
            "403 Client Error: Forbidden for url": "Your Knock API key does not have access to this resource. Please check the key belongs to the right environment.",
            NO_OBJECT_COLLECTIONS_ERROR: None,
            NO_AUDIENCE_KEYS_ERROR: None,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.knock.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: KnockSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        should_sync_default = {name: endpoint.should_sync_default for name, endpoint in ENDPOINTS_CONFIG.items()}
        should_sync_default["objects"] = bool(parse_key_list(config.object_collections))
        should_sync_default["audience_members"] = bool(parse_key_list(config.audience_keys))
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            should_sync_default=should_sync_default,
            default_incremental_lookback_seconds=INCREMENTAL_LOOKBACK_SECONDS,
        )

    def validate_credentials(
        self, config: KnockSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_knock_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KnockResumeConfig]:
        return ResumableSourceManager[KnockResumeConfig](inputs, KnockResumeConfig)

    def source_for_pipeline(
        self,
        config: KnockSourceConfig,
        resumable_source_manager: ResumableSourceManager[KnockResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return knock_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            object_collections=config.object_collections,
            audience_keys=config.audience_keys,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KNOCK,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Knock",
            caption="Use the secret API key (starts with `sk_`) for the environment you want to import from. You can find it in the Knock dashboard under **Developers → API keys**. Knock API keys are scoped to a single environment.",
            docsUrl="https://posthog.com/docs/cdp/sources/knock",
            iconPath="/static/services/knock.png",
            keywords=["notifications"],
            releaseStatus=ReleaseStatus.GA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="object_collections",
                        label="Object collections",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="accounts, projects",
                        secret=False,
                        caption="Comma-separated object collection keys to sync into the `objects` table. Knock can't list collections, so the `objects` table only syncs the collections you enter here.",
                    ),
                    SourceFieldInputConfig(
                        name="audience_keys",
                        label="Audience keys",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="beta-users, enterprise-admins",
                        secret=False,
                        caption="Comma-separated audience keys to sync into the `audience_members` table. Knock can't list audiences, so the `audience_members` table only syncs the audiences you enter here.",
                    ),
                ],
            ),
        )
