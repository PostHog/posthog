from typing import Optional, cast

from products.warehouse_sources.sources.fathom._config import FathomSourceConfig
from products.warehouse_sources.sources.fathom.fathom import FathomResumeConfig, fathom_source, probe_status
from products.warehouse_sources.sources.fathom.settings import ENDPOINTS, FATHOM_ENDPOINTS, INCREMENTAL_FIELDS
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
    build_endpoint_schemas,
    detect,
)

ADMIN_ONLY_ENDPOINTS = ("users",)

INVALID_KEY_MESSAGE = (
    "Fathom rejected your API key. Create a new key in Fathom under User settings > API access, then try again."
)
ADMIN_ONLY_MESSAGE = "Only an API key that belongs to a Fathom account admin can sync users."
FORBIDDEN_MESSAGE = (
    "Fathom refused this API key. Check that the user who created the key is still active in Fathom, "
    "then reconnect the source with a new key."
)
RATE_LIMITED_MESSAGE = "Fathom is rate limiting this API key. Wait a minute, then try again."
UNREACHABLE_MESSAGE = "Couldn't reach Fathom. Try again in a few minutes."


@SourceRegistry.register
class FathomSource(ResumableSource[FathomSourceConfig, FathomResumeConfig]):
    # The SDKs read only these two variable names. A bare `FATHOM_` prefix would also match
    # Fathom Analytics, which is a different vendor.
    codebase_detection = detect(
        env=("^FATHOM_API_KEY_AUTH$", "^FATHOM_BEARER_AUTH$"),
        npm=("fathom-typescript",),
        pypi=("fathom-python",),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://developers.fathom.ai/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FATHOM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.fathom.ai": INVALID_KEY_MESSAGE,
            # The first matching key wins, so the admin-only table goes before the general 403.
            "403 Client Error: Forbidden for url: https://api.fathom.ai/external/v1/users": ADMIN_ONLY_MESSAGE,
            "403 Client Error: Forbidden for url: https://api.fathom.ai": FORBIDDEN_MESSAGE,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.fathom.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FathomSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def get_endpoint_permissions(
        self, config: FathomSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        permissions: dict[str, str | None] = dict.fromkeys(endpoints)
        for endpoint in endpoints:
            if (
                endpoint in ADMIN_ONLY_ENDPOINTS
                and probe_status(config.api_key, FATHOM_ENDPOINTS[endpoint].path) == 403
            ):
                permissions[endpoint] = ADMIN_ONLY_MESSAGE
        return permissions

    def validate_credentials(
        self,
        config: FathomSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in FATHOM_ENDPOINTS:
            return False, f"Fathom has no table named {schema_name}."

        # Every key can list meetings. Only the admin-only tables need their own probe.
        path = FATHOM_ENDPOINTS[schema_name].path if schema_name in ADMIN_ONLY_ENDPOINTS else "/meetings"
        status = probe_status(config.api_key, path)

        if status == 200:
            return True, None
        if status == 401:
            return False, INVALID_KEY_MESSAGE
        if status == 403:
            return False, ADMIN_ONLY_MESSAGE if schema_name in ADMIN_ONLY_ENDPOINTS else FORBIDDEN_MESSAGE
        if status == 429:
            return False, RATE_LIMITED_MESSAGE
        if status is None:
            return False, UNREACHABLE_MESSAGE
        return False, f"Fathom returned an unexpected response (HTTP {status}). Check your API key, then try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FathomResumeConfig]:
        return ResumableSourceManager[FathomResumeConfig](inputs, FathomResumeConfig)

    def source_for_pipeline(
        self,
        config: FathomSourceConfig,
        resumable_source_manager: ResumableSourceManager[FathomResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return fathom_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FATHOM,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Fathom",
            caption=(
                "Import meetings, summaries and transcripts from the Fathom AI notetaker. "
                "Create an API key in Fathom under **User settings > API access** and paste it below. "
                "The key reads the meetings you recorded and the meetings shared with you or your team. "
                "To sync users, use a key that belongs to an account admin."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/fathom",
            iconPath="/static/services/fathom.png",
            keywords=["meeting notes", "note taker", "call recording", "fathom video"],
            releaseStatus=ReleaseStatus.BETA,
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
