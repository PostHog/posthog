from products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.source import DynamoDBSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamodb import (
    DynamoDBSourceConfig,
)

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.source"


class TestDynamoDBSource:
    def setup_method(self) -> None:
        self.source = DynamoDBSource()
        self.config = DynamoDBSourceConfig(
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
            aws_region="us-east-1",
            aws_session_token=None,
        )

    def test_api_version_is_the_one_the_requests_actually_target(self) -> None:
        assert self.source.supported_versions == ("2012-08-10",)
        assert self.source.default_version == "2012-08-10"
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")
