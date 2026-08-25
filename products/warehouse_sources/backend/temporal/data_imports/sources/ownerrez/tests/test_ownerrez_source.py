import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ownerrez import (
    OwnerrezSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.ownerrez import (
    OWNERREZ_API_VERSION_V1,
    OWNERREZ_API_VERSION_V2_0,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.source import OwnerrezSource

_INCREMENTAL_ENDPOINTS = {"Bookings", "Quotes", "Reviews"}
_FULL_REFRESH_ENDPOINTS = {"Payments", "Guests", "Properties", "Deposits", "Fees", "Refunds"}


class TestOwnerrezSource:
    def setup_method(self):
        self.source = OwnerrezSource()
        self.team_id = 123
        self.config = OwnerrezSourceConfig(email="host@example.com", api_key="pt_key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.ownerrez.com/v2/bookings?limit=100",
            "403 Client Error: Forbidden for url: https://api.ownerrez.com/v2/guests?limit=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.ownerrez.com/v2/bookings",
            "500 Server Error: Internal Server Error for url: https://api.ownerrez.com/v2/bookings",
            "HTTPSConnectionPool(host='api.ownerrez.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_version_metadata_declares_v1_deprecation(self):
        # The client only ever built /v2 paths, so both pins are request-identical; the metadata is
        # what drives the deprecation banner and the source-level repin migration.
        assert self.source.supported_versions == (OWNERREZ_API_VERSION_V1, OWNERREZ_API_VERSION_V2_0)
        assert self.source.default_version == OWNERREZ_API_VERSION_V2_0

        deprecation = self.source.get_version_deprecation(OWNERREZ_API_VERSION_V1)
        assert deprecation is not None
        # OwnerRez has published no sunset date, so this stays an advisory deprecation.
        assert deprecation.sunset_at is None
        # The current default must never be flagged deprecated.
        assert self.source.get_version_deprecation(OWNERREZ_API_VERSION_V2_0) is None

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["updated_utc"]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Bookings"])
        assert len(schemas) == 1
        assert schemas[0].name == "Bookings"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid OwnerRez account email or personal access token"),
            (
                (False, 403),
                False,
                "Could not connect to OwnerRez with the provided account email and personal access token",
            ),
            (
                (False, None),
                False,
                "Could not connect to OwnerRez with the provided account email and personal access token",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.source.validate_ownerrez_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("host@example.com", "pt_key")
