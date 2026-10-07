from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.neo4j import Neo4jSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.neo4j.canonical_descriptions import (
    NODE_DESCRIPTION,
    RELATIONSHIP_DESCRIPTION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.neo4j.neo4j import (
    Neo4jClient,
    neo4j_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.neo4j.settings import (
    API_VERSION,
    NON_RETRYABLE_ERRORS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Neo4jSource(SimpleSource[Neo4jSourceConfig], ValidateDatabaseHostMixin):
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://neo4j.com/docs/query-api/current/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEO4J

    @property
    def connection_host_fields(self) -> list[str]:
        return ["host"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(NON_RETRYABLE_ERRORS)

    def validate_credentials(
        self,
        config: Neo4jSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, team_id)

    def get_schemas(
        self,
        config: Neo4jSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                detected_primary_keys=["element_id"],
                description=(NODE_DESCRIPTION if name.startswith("node_") else RELATIONSHIP_DESCRIPTION)["description"],
            )
            for name in Neo4jClient(config, team_id).discover_tables()
            if names is None or name in names
        ]

    def source_for_pipeline(self, config: Neo4jSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return neo4j_source(config, inputs.team_id, inputs.schema_name)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NEO4J,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Neo4j",
            caption=(
                "Use the database credentials saved when you created your Aura instance, or ask your database administrator. "
                "Requires a public HTTPS endpoint with Query API enabled (Neo4j 5.19 or later). "
                "Imports support full refresh only, with a limit of 1,000,000 rows per table."
            ),
            keywords=["graph database", "cypher", "auradb"],
            iconPath="/static/services/neo4j.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="HTTPS host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://your-instance.databases.neo4j.io",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="neo4j",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="username",
                        label="Username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="neo4j",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
