from parameterized import parameterized

from products.warehouse_sources.sources.easypost._config import EasypostSourceConfig
from products.warehouse_sources.sources.easypost.settings import EASYPOST_ENDPOINTS
from products.warehouse_sources.sources.easypost.source import EasypostSource
from products.warehouse_sources.sources.sdk.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    error_message_matches,
    scripted_network,
)


def _config() -> EasypostSourceConfig:
    return EasypostSourceConfig(api_key="EZAK_test")


class TestGetSchemas:
    @parameterized.expand([(name,) for name, c in EASYPOST_ENDPOINTS.items() if c.incremental_fields])
    def test_every_syncable_schema_advertises_created_at(self, endpoint: str) -> None:
        schemas = {s.name: s for s in EasypostSource().get_schemas(_config(), team_id=1)}
        schema = schemas[endpoint]
        assert [f["field"] for f in schema.incremental_fields] == ["created_at"]
        assert schema.supports_append is True

    @parameterized.expand(
        [("carrier_accounts",), ("carriers",), ("carrier_types",), ("child_users",), ("reports",), ("usps_claims",)]
    )
    def test_lookup_schemas_are_full_refresh_only(self, endpoint: str) -> None:
        # These endpoints expose no cursor at all, so offering incremental or append would let a
        # user pick a sync type that silently re-reads the whole collection every run.
        schemas = {s.name: s for s in EasypostSource().get_schemas(_config(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.incremental_fields == []
        assert schema.supports_incremental is False
        assert schema.supports_append is False

    @parameterized.expand(
        [("carrier_accounts",), ("end_shippers",), ("carrier_types",), ("child_users",), ("reports",), ("usps_claims",)]
    )
    def test_restricted_endpoints_are_not_selected_by_default(self, endpoint: str) -> None:
        # EasyPost gates both endpoints: /carrier_accounts rejects test keys, and the EndShipper
        # API is opened per account. Selecting either by default fails a table nobody asked for.
        schemas = {s.name: s for s in EasypostSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].should_sync_default is False
        assert schemas["shipments"].should_sync_default is True


class TestValidateCredentials:
    def test_valid(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert EasypostSource().validate_credentials(_config(), team_id=1) == (True, None)
        assert network.requests_log[0].param("page_size") == "1"

    def test_invalid(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]) as network:
            ok, error = EasypostSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None
        assert network.requests_log[0].path == "/v2/shipments"


class TestGetRetryableErrors:
    @parameterized.expand(
        [
            (
                "connection_error_wrapping_read_timeout",
                "HTTPSConnectionPool(host='api.easypost.com', port=443): Max retries exceeded with url: "
                "/v2/refunds?page_size=100&start_datetime=2018-07-26T20%3A58%3A03Z&end_datetime="
                '2018-08-25T20%3A58%3A04Z (Caused by ReadTimeoutError("HTTPSConnectionPool(host='
                "'api.easypost.com', port=443): Read timed out. (read timeout=60.0)\"))",
            ),
            (
                "exhausted_retryable_status",
                "EasyPost API error (retryable): status=503, url=https://api.easypost.com/v2/shipments",
            ),
        ]
    )
    def test_retryable_errors_cover_exhausted_transient_failures(self, _name: str, error_msg: str) -> None:
        # `_fetch_page` already retries these with backoff; once that budget exhausts they must
        # stay classified as retryable (self-recovering via Temporal) rather than tracked
        # exception noise.
        assert error_message_matches(error_msg, EasypostSource().get_retryable_errors())


class TestSourceForPipeline:
    def test_plumbs_incremental_inputs(self) -> None:
        result = SourceDriver(EasypostSource(), _config()).run(
            "shipments",
            always(ScriptedResponse(json={"shipments": [], "has_more": False})),
            incremental_field="created_at",
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )
        response = result.response
        assert result.raised is None
        assert result.params("start_datetime")[-1] == "2024-01-01T00:00:00Z"
        assert response is not None
        assert response.name == "shipments"
        assert response.sort_mode == "desc"

    def test_drops_last_value_when_not_incremental(self) -> None:
        # When the schema isn't synced incrementally, the watermark must not leak into the request.
        result = SourceDriver(EasypostSource(), _config()).run(
            "addresses",
            always(ScriptedResponse(json={"addresses": [], "has_more": False})),
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )
        response = result.response
        assert result.raised is None
        assert result.params("start_datetime")[-1] == "2010-01-01T00:00:00Z"
        assert response is not None
        assert response.name == "addresses"
