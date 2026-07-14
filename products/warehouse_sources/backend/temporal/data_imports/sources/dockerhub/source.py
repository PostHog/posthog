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
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.dockerhub import (
    DockerhubResumeConfig,
    dockerhub_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.settings import (
    DOCKERHUB_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DockerhubSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _namespace_for_config(config: DockerhubSourceConfig) -> str:
    # A blank namespace means "my own repositories": Docker Hub personal repositories live under the
    # username's namespace.
    namespace = (config.namespace or "").strip()
    return namespace or config.username.strip()


@SourceRegistry.register
class DockerhubSource(ResumableSource[DockerhubSourceConfig, DockerhubResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DOCKERHUB

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored token pulls repositories and tags from whatever `namespace` is configured, so
        # retargeting the namespace must force re-entry of the token — otherwise an editor could
        # point the preserved credential at any org the token can read.
        return ["namespace"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DOCKERHUB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Docker Hub",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Docker Hub username and a personal access token to pull your container repositories and tags into the PostHog Data warehouse.

You can create a personal access token with **Read** access under **Account settings → Personal access tokens** in [Docker Hub](https://app.docker.com/settings/personal-access-tokens). To import an organization's repositories instead of your own, set the namespace field to the organization name.
""",
            iconPath="/static/services/dockerhub.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dockerhub",
            keywords=["docker"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="username",
                        label="Username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="personal_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="namespace",
                        label="Namespace",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Defaults to your username",
                        secret=False,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://hub.docker.com": "Your Docker Hub username or personal access token is invalid or has been revoked. Generate a new token under Account settings → Personal access tokens, then reconnect.",
            "403 Client Error: Forbidden for url: https://hub.docker.com": "Your Docker Hub personal access token does not have access to this data. Check the token's access permissions and the configured namespace, then reconnect.",
        }

    def get_schemas(
        self,
        config: DockerhubSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — the Hub management API exposes no server-side
        # updated_after/since filter on repositories or tags, so there is no incremental cursor.
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
        self, config: DockerhubSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Both endpoints read from the same namespace with the same token, so a single login +
        # namespace probe validates access to every schema.
        return validate_credentials(config.username, config.personal_access_token, _namespace_for_config(config))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DockerhubResumeConfig]:
        return ResumableSourceManager[DockerhubResumeConfig](inputs, DockerhubResumeConfig)

    def source_for_pipeline(
        self,
        config: DockerhubSourceConfig,
        resumable_source_manager: ResumableSourceManager[DockerhubResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in DOCKERHUB_ENDPOINTS:
            raise ValueError(f"Unknown Docker Hub schema '{inputs.schema_name}'")

        return dockerhub_source(
            username=config.username,
            personal_access_token=config.personal_access_token,
            namespace=_namespace_for_config(config),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
