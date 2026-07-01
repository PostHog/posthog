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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticsearch.elasticsearch import (
    NON_JSON_RESPONSE_ERROR,
    ElasticsearchAuth,
    elasticsearch_source,
    hostname_of,
    list_indices,
    validate_credentials as validate_elasticsearch_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ElasticsearchSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _auth_from_config(config: ElasticsearchSourceConfig) -> ElasticsearchAuth:
    if config.auth_method.selection == "api_key":
        return ElasticsearchAuth(api_key=config.auth_method.api_key)
    return ElasticsearchAuth(username=config.auth_method.username, password=config.auth_method.password)


@SourceRegistry.register
class ElasticsearchSource(SimpleSource[ElasticsearchSourceConfig], ValidateDatabaseHostMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ELASTICSEARCH

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Elasticsearch authentication failed. Please check your credentials.",
            "403 Client Error: Forbidden for url": "Elasticsearch denied access. Please check that your credentials can read this index.",
            "404 Client Error: Not Found for url": "Elasticsearch index not found. It may have been deleted or renamed.",
            NON_JSON_RESPONSE_ERROR: "Elasticsearch returned an unexpected response. Check that the cluster URL points at the Elasticsearch HTTP API, not a browser or Kibana URL.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ELASTICSEARCH,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Elasticsearch",
            caption="""Connect your Elasticsearch cluster to pull index documents into the PostHog Data warehouse.

Enter the full cluster URL (e.g. `https://my-deployment.es.us-east-1.aws.found.io:9243`) and credentials with read access to the indices you want to sync. Each non-system index appears as a separate table.""",
            iconPath="/static/services/elasticsearch.png",
            docsUrl="https://posthog.com/docs/cdp/sources/elasticsearch",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Cluster URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://my-cluster.example.com:9243",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication method",
                        required=True,
                        defaultValue="basic",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Username and password",
                                value="basic",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="username",
                                            label="Username",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="elastic",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="password",
                                            label="Password",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="API key",
                                value="api_key",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="api_key",
                                            label="API key",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
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

    def get_schemas(
        self,
        config: ElasticsearchSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every non-system index is a schema. Generic Elasticsearch has no
        # knowable timestamp field per index, so syncs are full refresh.
        indices = list_indices(config.host, _auth_from_config(config))
        if names is not None:
            names_set = set(names)
            indices = [index for index in indices if index in names_set]

        return [
            SourceSchema(
                name=index,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for index in indices
        ]

    def validate_credentials(
        self, config: ElasticsearchSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), team_id)
        except ValueError:
            return False, "Invalid Elasticsearch cluster URL"
        if not host_valid:
            return False, host_error

        if validate_elasticsearch_credentials(config.host, _auth_from_config(config)):
            return True, None

        return False, "Could not connect to Elasticsearch with the provided credentials"

    def source_for_pipeline(self, config: ElasticsearchSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # Re-check at sync time so a PATCHed host can't be retargeted at
        # internal infrastructure.
        host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), inputs.team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid Elasticsearch host")

        return elasticsearch_source(
            host=config.host,
            auth=_auth_from_config(config),
            index=inputs.schema_name,
            logger=inputs.logger,
        )
