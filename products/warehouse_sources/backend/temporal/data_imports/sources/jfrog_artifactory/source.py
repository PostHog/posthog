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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    JfrogArtifactorySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.jfrog_artifactory import (
    JfrogArtifactoryResumeConfig,
    hostname_of,
    jfrog_artifactory_source,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    JFROG_ARTIFACTORY_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Endpoints JFrog restricts to admin users (or access tokens scoped to the relevant domain).
_ADMIN_ENDPOINTS = {"builds", "storage_summary"}


@SourceRegistry.register
class JfrogArtifactorySource(
    ResumableSource[JfrogArtifactorySourceConfig, JfrogArtifactoryResumeConfig], ValidateDatabaseHostMixin
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JFROGARTIFACTORY

    @property
    def connection_host_fields(self) -> list[str]:
        # The access token is sent to `base_url`, so retargeting it must re-require the token.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JFROG_ARTIFACTORY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="JFrog (Artifactory / JFrog Platform)",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["artifactory", "jfrog platform"],
            caption="""Connect your JFrog Platform instance to pull your Artifactory data into the PostHog Data warehouse.

Enter your platform URL (e.g. `https://mycompany.jfrog.io`, or your own domain for self-hosted installs) and an access token. Generate a token from your JFrog user profile (**Edit Profile → Generate an Identity Token**) or, as an admin, under **Administration → User Management → Access Tokens**.

The `artifacts` and `repositories` tables work with any authenticated token that can read your repositories. The `builds` and `storage_summary` tables require an admin user (or a token scoped to those APIs); deselect them if your token can't access them.""",
            iconPath="/static/services/jfrog_artifactory.png",
            docsUrl="https://posthog.com/docs/cdp/sources/jfrog-artifactory",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Platform URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://mycompany.jfrog.io",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_request` calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync. The host is
            # per-tenant, so match on the stable status text only.
            "401 Client Error: Unauthorized for url": "Your JFrog access token is invalid, expired, or has been revoked. Generate a new access token, then reconnect.",
            "403 Client Error: Forbidden for url": "Your JFrog access token is missing the permissions needed to sync this data. The builds and storage_summary tables require an admin token — deselect them or use a token with the required access.",
        }

    def get_schemas(
        self,
        config: JfrogArtifactorySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "builds":
                return "Requires an admin user or a token scoped to the builds domain"
            if endpoint == "storage_summary":
                return "Point-in-time snapshot of per-repository storage usage. Requires an admin token"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = JFROG_ARTIFACTORY_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                detected_primary_keys=list(endpoint_config.primary_keys),
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: JfrogArtifactorySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.base_url), team_id)
        except ValueError as e:
            return False, str(e)
        if not host_valid:
            return False, host_error

        try:
            ok, status_code = probe_endpoint(
                config.base_url,
                config.access_token,
                endpoint=schema_name if schema_name in JFROG_ARTIFACTORY_ENDPOINTS else None,
            )
        except ValueError as e:
            return False, str(e)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid JFrog access token"
        if status_code == 403:
            # At source-create a 403 means the token is genuine but not fully scoped — accept it and
            # surface per-table scope via get_endpoint_permissions instead of blocking the source.
            if schema_name is None:
                return True, None
            if schema_name in _ADMIN_ENDPOINTS:
                return (
                    False,
                    f"Your JFrog access token cannot access the {schema_name} table — it requires an admin user or a token scoped to that API",
                )
            return False, f"Your JFrog access token is missing the permissions needed for the {schema_name} table"
        return False, "Could not connect to JFrog with the provided platform URL and access token"

    def get_endpoint_permissions(
        self, config: JfrogArtifactorySourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        permissions: dict[str, str | None] = {}
        for endpoint in endpoints:
            if endpoint not in JFROG_ARTIFACTORY_ENDPOINTS:
                permissions[endpoint] = None
                continue
            try:
                ok, status_code = probe_endpoint(config.base_url, config.access_token, endpoint=endpoint)
            except ValueError:
                permissions[endpoint] = None
                continue
            # Only a definite denial is a missing scope; throttles, 5xx, and network blips must not
            # mark the table as unreachable.
            if ok or status_code not in (401, 403):
                permissions[endpoint] = None
            elif endpoint in _ADMIN_ENDPOINTS:
                permissions[endpoint] = "Requires an admin user or a token scoped to this API"
            else:
                permissions[endpoint] = "Your access token cannot read this API"
        return permissions

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[JfrogArtifactoryResumeConfig]:
        return ResumableSourceManager[JfrogArtifactoryResumeConfig](inputs, JfrogArtifactoryResumeConfig)

    def source_for_pipeline(
        self,
        config: JfrogArtifactorySourceConfig,
        resumable_source_manager: ResumableSourceManager[JfrogArtifactoryResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host_valid, host_error = self.is_database_host_valid(hostname_of(config.base_url), inputs.team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid JFrog platform URL")

        return jfrog_artifactory_source(
            base_url=config.base_url,
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
