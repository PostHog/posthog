import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.source import BettermodeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bettermode import (
    BettermodeSourceConfig,
)


class TestBettermodeSource:
    def setup_method(self):
        self.source = BettermodeSource()
        self.team_id = 123
        self.config = BettermodeSourceConfig(region="us", client_id="client", client_secret="secret", network_id="net")

    def test_connection_host_fields_gate_credential_retargeting(self):
        # Removing either field lets an editor retarget the preserved client secret at a
        # different host/community without re-entering it.
        assert self.source.connection_host_fields == ["region", "network_id"]

    @pytest.mark.parametrize(
        "other_error",
        [
            "Bettermode API error (retryable): status=429",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only `posts` has a server-side timestamp filter; everything else is full refresh.
        assert incremental == {"posts"}

    def test_posts_schema_advertises_timestamp_cursors(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["posts"].incremental_fields == INCREMENTAL_FIELDS["posts"]
        assert [f["field"] for f in schemas["posts"].incremental_fields] == ["createdAt", "publishedAt", "updatedAt"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["posts"])
        assert len(schemas) == 1
        assert schemas[0].name == "posts"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            (
                (False, "Bettermode API error (status 404): App not found"),
                False,
                "Bettermode API error (status 404): App not found",
            ),
            ((False, None), False, "Invalid Bettermode credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.source.validate_bettermode_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("us", "client", "secret", "net")
