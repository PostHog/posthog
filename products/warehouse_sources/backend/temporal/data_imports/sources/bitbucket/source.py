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
from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.bitbucket import (
    BitbucketAuth,
    BitbucketResumeConfig,
    bitbucket_source,
    validate_credentials as validate_bitbucket_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.settings import (
    BITBUCKET_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BitbucketSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BitbucketSource(ResumableSource[BitbucketSourceConfig, BitbucketResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BITBUCKET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BITBUCKET,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Atlassian Bitbucket Cloud",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["atlassian", "git", "ci"],
            caption="""Connect your Bitbucket Cloud workspace to sync repositories, pull requests, commits, pipelines, and more.

Your credentials need the **repository**, **pullrequest**, **pipeline**, and **account** read scopes. Avoid app passwords — Atlassian is retiring them; use an API token or an access token instead.""",
            iconPath="/static/services/bitbucket.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bitbucket",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="workspace",
                        label="Workspace",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-workspace",
                        caption="Your workspace ID — the part after `bitbucket.org/` in your workspace URL.",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication type",
                        required=True,
                        defaultValue="api_token",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Atlassian API token",
                                value="api_token",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="email",
                                            label="Atlassian account email",
                                            type=SourceFieldInputConfigType.EMAIL,
                                            required=False,
                                            placeholder="you@example.com",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="api_token",
                                            label="API token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            caption="Create an API token with scopes in your [Atlassian account settings](https://id.atlassian.com/manage-profile/security/api-tokens).",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Access token",
                                value="access_token",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="access_token",
                                            label="Access token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            caption="A workspace, project, or repository access token created in your Bitbucket settings.",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.bitbucket.org": "Your Bitbucket credentials are invalid or have been revoked. Check your email and API token (or access token), then reconnect.",
            "403 Client Error: Forbidden for url: https://api.bitbucket.org": "Your Bitbucket token is missing a read scope needed to sync this data. Grant the repository, pullrequest, pipeline, and account read scopes, then reconnect.",
            # Deterministic config errors from _get_auth — retrying can't fix them.
            "Missing Bitbucket access token": "No Bitbucket access token is configured. Please update the source configuration.",
            "Missing Atlassian account email or API token": "The Atlassian account email or API token is missing. Please update the source configuration.",
        }

    def _get_auth(self, config: BitbucketSourceConfig) -> BitbucketAuth:
        if config.auth_method.selection == "access_token":
            if not config.auth_method.access_token:
                raise ValueError("Missing Bitbucket access token")
            return BitbucketAuth(access_token=config.auth_method.access_token)

        if not config.auth_method.email or not config.auth_method.api_token:
            raise ValueError("Missing Atlassian account email or API token")
        return BitbucketAuth(email=config.auth_method.email, api_token=config.auth_method.api_token)

    def get_schemas(
        self,
        config: BitbucketSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = BITBUCKET_ENDPOINTS[endpoint]
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: BitbucketSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            auth = self._get_auth(config)
        except ValueError as e:
            raw = str(e)
            friendly = self.get_non_retryable_errors().get(raw)
            return False, friendly or raw
        return validate_bitbucket_credentials(auth, config.workspace)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BitbucketResumeConfig]:
        return ResumableSourceManager[BitbucketResumeConfig](inputs, BitbucketResumeConfig)

    def source_for_pipeline(
        self,
        config: BitbucketSourceConfig,
        resumable_source_manager: ResumableSourceManager[BitbucketResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bitbucket_source(
            auth=self._get_auth(config),
            workspace=config.workspace,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
