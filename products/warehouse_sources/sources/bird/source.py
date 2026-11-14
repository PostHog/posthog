from typing import Optional, cast

from products.warehouse_sources.sources.bird._config import BirdSourceConfig
from products.warehouse_sources.sources.bird.bird import (
    INVALID_KEY_ERROR,
    BirdResumeConfig,
    bird_source,
    validate_credentials as validate_bird_credentials,
)
from products.warehouse_sources.sources.bird.settings import ENDPOINTS, INCREMENTAL_FIELDS
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

SOURCE_KEY = "Bird"


@SourceRegistry.register
class BirdSource(ResumableSource[BirdSourceConfig, BirdResumeConfig]):
    codebase_detection = detect(
        env=("^BIRD_API_KEY$",),
        npm=("@messagebird/sdk",),
        pypi=("messagebird-sdk",),
        composer=("messagebird/sdk",),
        go=("github.com/messagebird/bird-sdk-go",),
    )

    lists_tables_without_credentials = True  # Static endpoint catalog, safe for public docs.
    # The bird.com API has only ever been served under /v1, with no documented version choice.
    api_docs_url = "https://bird.com/docs/api"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def credential_auth_type(self) -> str:
        # The scaffold froze "credentials" in facade/credential_auth_types.py before the key field
        # existed. The stored default must not change, and both types hold the key the same way.
        return "credentials"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": INVALID_KEY_ERROR,
            "403 Client Error: Forbidden for url": (
                "Your Bird API key can't read one of the tables you sync. Give the key read access to that "
                "data in the Bird dashboard under Platform tools > API keys, then sync again."
            ),
            "421 Client Error": (
                "Bird sent this request to the wrong region for your API key. Copy the whole key from the "
                "Bird dashboard, then reconnect the source."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.bird.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BirdSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BirdSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_bird_credentials(config.api_key, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BirdResumeConfig]:
        return ResumableSourceManager[BirdResumeConfig](inputs, BirdResumeConfig)

    def source_for_pipeline(
        self,
        config: BirdSourceConfig,
        resumable_source_manager: ResumableSourceManager[BirdResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bird_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            keywords=["messagebird"],
            label="Bird",
            caption=(
                "Connect your bird.com workspace with an API key to sync contacts, audiences, email, SMS and "
                "WhatsApp messages, broadcasts, templates, and daily sending stats. Create a key in the Bird "
                "dashboard under **Platform tools > API keys**. Give it read access to the scopes of the "
                "tables you want, such as `emails`, `email_marketing`, `email_management`, `sms`, "
                "`whatsapp`, and `numbers`. Keys from the older Bird Engagement Platform (app.bird.com) "
                "or MessageBird don't work here."
            ),
            iconPath="/static/warehouse-sources/bird/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bird",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="bk_us1_...",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.BETA,
        )
