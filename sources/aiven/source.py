from typing import Optional, cast

from sources.aiven._config import AivenSourceConfig
from sources.aiven.aiven import (
    aiven_source,
    validate_credentials as validate_aiven_credentials,
)
from sources.aiven.settings import AIVEN_ENDPOINTS, ENDPOINTS, INCREMENTAL_FIELDS
from sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    SimpleSource,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
)


@SourceRegistry.register
class AivenSource(SimpleSource[AivenSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://api.aiven.io/doc/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIVEN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AIVEN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Aiven",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter an Aiven API token to pull your Aiven projects, services and billing data into the PostHog Data warehouse.

You can create a personal token from your [Aiven profile authentication page](https://console.aiven.io/profile/auth).

Billing tables (billing groups, invoices, invoice lines) and organization membership tables require organization-level read access on the token.
""",
            iconPath="/static/services/aiven.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/aiven",
            keywords=["aiven", "cloud", "billing", "infrastructure"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from sources.aiven.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid, revoked, or insufficiently-scoped token surfaces as an HTTPError when
            # `_fetch` calls `raise_for_status()`. Retrying can never satisfy a credential problem.
            "401 Client Error: Unauthorized for url: https://api.aiven.io": "Your Aiven API token is invalid or has expired. Create a new token on your Aiven profile authentication page, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.aiven.io": "Your Aiven API token is missing the access needed to sync this data. Grant organization-level read access, then reconnect.",
        }

    def get_schemas(
        self,
        config: AivenSourceConfig,
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
            should_sync_default={name: cfg.should_sync_default for name, cfg in AIVEN_ENDPOINTS.items()},
        )

    def validate_credentials(
        self, config: AivenSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        if validate_aiven_credentials(config.api_token):
            return True, None

        return False, "Invalid Aiven API token"

    def source_for_pipeline(self, config: AivenSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return aiven_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )
