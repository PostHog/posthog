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
from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.codacy import (
    codacy_source,
    validate_credentials as validate_codacy_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CodacySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CodacySource(SimpleSource[CodacySourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CODACY

    @property
    def connection_host_fields(self) -> list[str]:
        # The token is sent to api.codacy.com against <provider>/<organization>, so retargeting
        # either segment must force re-entry of the token rather than reusing the preserved one.
        return ["provider", "organization"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CODACY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Codacy",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["code quality", "static analysis", "code coverage"],
            caption="""Enter your Codacy account API token to automatically pull your Codacy code quality data into the PostHog Data warehouse.

You can generate an account API token in your [Codacy account settings](https://app.codacy.com/account/access-management). The token grants access to the organizations and repositories your Codacy account can see.
""",
            iconPath="/static/services/codacy.png",
            docsUrl="https://posthog.com/docs/cdp/sources/codacy",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Account API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="provider",
                        label="Git provider",
                        required=True,
                        defaultValue="gh",
                        options=[
                            SourceFieldSelectConfigOption(label="GitHub", value="gh"),
                            SourceFieldSelectConfigOption(label="GitLab", value="gl"),
                            SourceFieldSelectConfigOption(label="Bitbucket", value="bb"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="organization",
                        label="Organization name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-organization",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.codacy.com": "Your Codacy API token is invalid or has been revoked. Generate a new account API token in your Codacy account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.codacy.com": "Your Codacy API token does not have access to this organization or repository. Check your Codacy account permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: CodacySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # No v3 list endpoint exposes a server-side updated-since filter, so every table is
        # full refresh (the per-organization snapshots are small enough for periodic full pulls).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: CodacySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_codacy_credentials(config.api_token):
            return True, None

        return False, "Invalid Codacy API token"

    def source_for_pipeline(self, config: CodacySourceConfig, inputs: SourceInputs) -> SourceResponse:
        return codacy_source(
            api_token=config.api_token,
            provider=config.provider,
            organization=config.organization,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
