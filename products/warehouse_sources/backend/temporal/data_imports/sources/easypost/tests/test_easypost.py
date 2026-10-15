from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.easypost import (
    EasypostResumeConfig,
    _parse_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.source import EasypostSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.easypost import (
    EasypostSourceConfig,
)


def _driver(api_key: str = "k") -> SourceDriver:
    return SourceDriver(EasypostSource(), EasypostSourceConfig(api_key=api_key))


class TestParseDatetime:
    @parameterized.expand(
        [
            ("z_suffix", "2024-01-15T10:30:00Z", datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)),
            ("offset", "2024-01-15T10:30:00+00:00", datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)),
            ("naive_datetime", datetime(2024, 1, 15, 10, 30, 0), datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)),
            ("none", None, None),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_parse(self, _name: str, value: Any, expected: datetime | None) -> None:
        assert _parse_datetime(value) == expected


class TestGetRows:
    def test_paginates_via_before_id(self) -> None:
        result = _driver().run(
            "shipments",
            [
                ScriptedResponse(json={"shipments": [{"id": "shp_1"}, {"id": "shp_2"}], "has_more": True}),
                ScriptedResponse(json={"shipments": [{"id": "shp_3"}], "has_more": False}),
            ],
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["shp_1", "shp_2", "shp_3"]
        assert result.params("before_id") == [None, "shp_2"]
        assert result.saved_states == [EasypostResumeConfig(before_id=None), EasypostResumeConfig(before_id="shp_2")]

    def test_resumes_from_saved_before_id(self) -> None:
        result = _driver().run(
            "shipments",
            [ScriptedResponse(json={"shipments": [{"id": "shp_3"}], "has_more": False})],
            resume_state=EasypostResumeConfig(before_id="shp_2"),
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["shp_3"]
        assert result.params("before_id") == ["shp_2"]

    def test_incremental_stops_at_watermark(self) -> None:
        # Descending order: once a record at/below the watermark appears, everything after it is older,
        # so pagination must stop client-side even though has_more is True.
        result = _driver().run(
            "shipments",
            [
                ScriptedResponse(
                    json={
                        "shipments": [
                            {"id": "shp_3", "created_at": "2024-01-03T00:00:00Z"},
                            {"id": "shp_2", "created_at": "2024-01-02T00:00:00Z"},
                            {"id": "shp_1", "created_at": "2024-01-01T00:00:00Z"},
                        ],
                        "has_more": True,
                    }
                )
            ],
            incremental_field="created_at",
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["shp_3"]
        assert result.params("start_datetime") == ["2024-01-02T00:00:00Z"]
        assert result.params("before_id") == [None]

    def test_full_refresh_sends_no_time_filter(self) -> None:
        result = _driver().run("shipments", [ScriptedResponse(json={"shipments": [], "has_more": False})])
        assert result.raised is None
        assert result.rows == []
        assert result.params("start_datetime") == [None]
        assert result.params("before_id") == [None]


class TestUnpaginatedEndpoints:
    def test_bare_list_response_is_yielded_whole(self) -> None:
        # /carrier_accounts answers with a bare JSON array, not the {"<name>": [...]} wrapper every
        # other endpoint uses, so extraction has to branch on the endpoint rather than the payload.
        result = _driver().run("carrier_accounts", [ScriptedResponse(json=[{"id": "ca_1"}, {"id": "ca_2"}])])
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["ca_1", "ca_2"]
        assert result.urls == ["https://api.easypost.com/v2/carrier_accounts"]

    def test_carrier_credentials_never_reach_the_warehouse(self) -> None:
        # EasyPost masks password-type credential values but returns the rest in plaintext, and
        # anyone who can query the warehouse can read a synced row.
        result = _driver().run(
            "carrier_accounts",
            [
                ScriptedResponse(
                    json=[
                        {
                            "id": "ca_1",
                            "type": "UspsAccount",
                            "fields": {"credentials": {"client_id": {"value": "123456"}}},
                            "credentials": {"client_id": "123456"},
                            "test_credentials": {"client_id": "123456"},
                        }
                    ]
                )
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "ca_1", "type": "UspsAccount"}]


class TestValidateCredentials:
    @parameterized.expand(
        [("ok", 200, True), ("unauthorized", 401, False), ("inactive", 403, False), ("server", 500, False)]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("k") is expected
        assert {request.path for request in network.requests_log} == {"/v2/shipments"}
        assert {request.param("page_size") for request in network.requests_log} == {"1"}

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("k") is False
        assert {request.path for request in network.requests_log} == {"/v2/shipments"}

    def test_redacts_api_key_in_http_logging(self) -> None:
        # The API key is sent as the Basic auth username; it must be registered for redaction so it
        # cannot leak into HTTP telemetry/sample capture.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("secret-key") is True
        assert network.session_options == [{"redact_values": ("secret-key",)}]


class TestGetRowsRedaction:
    def test_redacts_api_key_in_http_logging(self) -> None:
        # Same secret-leak guard as validate_credentials, on the sync request path.
        result = _driver("secret-key").run("shipments", [ScriptedResponse(json={"shipments": [], "has_more": False})])
        assert result.raised is None
        assert result.session_options == [{"redact_values": ("secret-key",)}]


class TestEasypostSource:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        payload = [] if endpoint == "carrier_accounts" else {endpoint: [], "has_more": False}
        result = _driver().run(endpoint, [ScriptedResponse(json=payload)])
        response = result.response
        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys
        # EasyPost returns newest-first; the watermark logic depends on this being declared.
        assert response.sort_mode == "desc"
