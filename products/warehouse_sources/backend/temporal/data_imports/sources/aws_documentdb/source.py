from pathlib import Path
from typing import ClassVar

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source import MongoDBSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

# DocumentDB certificates chain to Amazon's own CAs, which certifi does not ship. Refresh from
# https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem when AWS adds a CA.
_AWS_CA_BUNDLE = str(Path(__file__).with_name("global-bundle.crt"))

_CONNECTION_STRING_CAPTION = (
    "In the Amazon DocumentDB console, open your cluster and copy the connection string under "
    "**Connectivity & security**, then replace `<insertYourPassword>` with your password. "
    "The cluster endpoint only resolves inside your VPC, so replace the host with your load balancer's "
    "address and add `directConnection=true&tlsAllowInvalidHostnames=true`. PostHog already trusts "
    "the AWS certificate bundle."
)


@SourceRegistry.register
class AwsDocumentDBSource(MongoDBSource):
    tls_ca_file: ClassVar[str | None] = _AWS_CA_BUNDLE
    codebase_detection = detect(
        env=("^DOCDB_", "^DOCUMENTDB_"),
        npm=("@aws-sdk/client-docdb", "@aws-sdk/client-docdb-elastic"),
        pypi=("mypy-boto3-docdb", "mypy-boto3-docdb-elastic"),
    )

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSDOCUMENTDB

    @staticmethod
    def _adjust_field(field: FieldType) -> FieldType:
        if isinstance(field, SourceFieldInputConfig) and field.name == "connection_string":
            return field.model_copy(
                update={
                    "placeholder": "mongodb://username:password@docdb-cluster.cluster-abc123.us-east-1.docdb.amazonaws.com:27017/?tls=true&replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false",
                    "caption": _CONNECTION_STRING_CAPTION,
                }
            )
        if isinstance(field, SourceFieldInputConfig) and field.name == "database_name":
            return field.model_copy(
                update={
                    "required": True,
                    "caption": "The database to import. DocumentDB connection strings don't include one.",
                }
            )
        return field

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSDOCUMENTDB,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["aws", "amazon", "documentdb", "docdb", "mongo"],
            label="Amazon DocumentDB",
            caption=(
                "DocumentDB clusters only accept connections from inside their VPC. Make the cluster "
                "reachable from PostHog, for example through a Network Load Balancer, and allow "
                "PostHog's IP addresses in its security group."
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            iconPath="/static/services/aws.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-documentdb",
            fields=[self._adjust_field(field) for field in super().get_source_config.fields],
        )
