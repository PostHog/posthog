from sources.plain._config import PlainSourceConfig
from sources.plain.source import PlainSource
from sources.sdk.testing import error_message_matches


class TestPlainSource:
    def setup_method(self):
        self.source = PlainSource()
        self.team_id = 123
        self.config = PlainSourceConfig(api_key="plainApiKey_test")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["customers"])

        assert len(schemas) == 1
        assert schemas[0].name == "customers"

    def test_read_timeout_is_retryable(self):
        error_msg = "HTTPSConnectionPool(host='core-api.uk.plain.com', port=443): Read timed out. (read timeout=60)"
        assert error_message_matches(error_msg, self.source.get_retryable_errors())
