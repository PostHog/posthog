from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZonkaFeedbackSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.settings import (
    ENDPOINTS,
    ZONKA_FEEDBACK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.zonka_feedback import (
    DATA_CENTER_IDS,
    ZonkaFeedbackResumeConfig,
    base_url,
    check_access,
    zonka_feedback_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZonkaFeedbackSource(ResumableSource[ZonkaFeedbackSourceConfig, ZonkaFeedbackResumeConfig]):
    api_docs_url = "https://apidocs.zonkafeedback.com/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZONKAFEEDBACK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZONKA_FEEDBACK,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Zonka Feedback",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Zonka Feedback auth token to pull your survey and feedback data into the PostHog Data warehouse.

An Admin can generate an auth token under **Company Settings → Developers → API** in Zonka Feedback. Select the data center that matches your account's region (shown in the same settings area).
""",
            iconPath="/static/services/zonka_feedback.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zonka-feedback",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="auth_token",
                        label="Auth token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="data_center",
                        label="Data center",
                        required=True,
                        defaultValue="us1",
                        options=[
                            SourceFieldSelectConfigOption(label="US (us1.apis.zonkafeedback.com)", value="us1"),
                            SourceFieldSelectConfigOption(label="EU (e.apis.zonkafeedback.com)", value="e"),
                            SourceFieldSelectConfigOption(label="India (in.apis.zonkafeedback.com)", value="in"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # An invalid or revoked auth token surfaces as a requests HTTPError when `_fetch_page` calls
        # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
        # The API host varies by data center, so enumerate the known regional hosts; match the stable
        # status text and base host, not the per-request path/query.
        errors: dict[str, str | None] = {}
        for data_center in DATA_CENTER_IDS:
            host = base_url(data_center)
            errors[f"401 Client Error: Unauthorized for url: {host}"] = (
                "Your Zonka Feedback auth token is invalid or has been revoked. Generate a new token "
                "under Company Settings → Developers → API, then reconnect."
            )
            errors[f"403 Client Error: Forbidden for url: {host}"] = (
                "Your Zonka Feedback auth token does not have access to this data. Check the token's "
                "permissions, then reconnect."
            )
        return errors

    def get_schemas(
        self,
        config: ZonkaFeedbackSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Zonka Feedback's list endpoints expose no server-side
        # timestamp filter, so there is no incremental cursor to advance.
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
        self, config: ZonkaFeedbackSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The auth token is account-wide, so a single probe validates access to every schema; there
        # is no per-endpoint scope to check.
        status, message = check_access(config.auth_token, config.data_center)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid Zonka Feedback auth token"
        return False, message or "Could not validate Zonka Feedback auth token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZonkaFeedbackResumeConfig]:
        return ResumableSourceManager[ZonkaFeedbackResumeConfig](inputs, ZonkaFeedbackResumeConfig)

    def source_for_pipeline(
        self,
        config: ZonkaFeedbackSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZonkaFeedbackResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ZONKA_FEEDBACK_ENDPOINTS:
            raise ValueError(f"Unknown Zonka Feedback schema '{inputs.schema_name}'")

        return zonka_feedback_source(
            auth_token=config.auth_token,
            data_center=config.data_center,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
