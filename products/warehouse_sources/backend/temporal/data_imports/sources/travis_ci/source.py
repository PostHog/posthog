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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TravisCISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TRAVIS_CI_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.travis_ci import (
    TravisCIResumeConfig,
    travis_ci_source,
    validate_credentials as validate_travis_ci_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TravisCISource(ResumableSource[TravisCISourceConfig, TravisCIResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRAVISCI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TRAVIS_CI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Travis CI (Idera)",
            releaseStatus=ReleaseStatus.ALPHA,
            docsUrl="https://posthog.com/docs/cdp/sources/travis-ci",
            caption="""Enter your Travis CI API token to sync your CI/CD build history into the PostHog Data warehouse.

You can find or generate the token in your [Travis CI settings](https://app.travis-ci.com/account/preferences) under **API authentication**, or with the Travis CI CLI: `travis token --com`.

The token can read every repository its owning user has access to; only those repositories are synced.
""",
            iconPath="/static/services/travis_ci.png",
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

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Travis CI answers 403 "access denied" for missing/invalid/revoked tokens (it does
            # not use 401, but match it too in case that changes). Retrying can't satisfy a
            # credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://api.travis-ci.com": "Your Travis CI API token is invalid or has been revoked. Generate a new token in your Travis CI settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.travis-ci.com": "Your Travis CI API token is invalid or has been revoked. Generate a new token in your Travis CI settings, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TravisCISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint in ("builds", "jobs"):
                return (
                    "Synced newest-first; incremental syncs stop at the last-synced id, so rows that "
                    "were still running when previously synced keep their state from that sync — run a "
                    "full refresh to re-pull final states"
                )
            if endpoint == "branches":
                return "Full refresh only, walking every accessible repository's branch list"
            return None

        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=TRAVIS_CI_ENDPOINTS[endpoint].should_sync_default,
                description=_description(endpoint),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: TravisCISourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # Travis CI tokens carry no scopes, so one /user probe covers every endpoint — a valid
        # token can read everything the owning user can.
        return validate_travis_ci_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TravisCIResumeConfig]:
        return ResumableSourceManager[TravisCIResumeConfig](inputs, TravisCIResumeConfig)

    def source_for_pipeline(
        self,
        config: TravisCISourceConfig,
        resumable_source_manager: ResumableSourceManager[TravisCIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return travis_ci_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
