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
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.settings import (
    EASYPOST_ENDPOINTS,
    ENDPOINTS,
)
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


class TestChildUsers:
    def test_pages_forward_via_after_id(self) -> None:
        # /users/children documents only `after_id`, and answers under "children", not the table name.
        result = _driver().run(
            "child_users",
            [
                ScriptedResponse(json={"children": [{"id": "user_1"}, {"id": "user_2"}], "has_more": True}),
                ScriptedResponse(json={"children": [{"id": "user_3"}], "has_more": False}),
            ],
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["user_1", "user_2", "user_3"]
        assert result.paths == ["/v2/users/children"] * 2
        assert result.params("after_id") == [None, "user_2"]
        assert result.params("before_id") == [None, None]
        assert result.saved_states == [EasypostResumeConfig(after_id=None), EasypostResumeConfig(after_id="user_2")]
        assert result.response is not None
        assert result.response.sort_mode == "asc"

    def test_resumes_from_saved_after_id(self) -> None:
        result = _driver().run(
            "child_users",
            [ScriptedResponse(json={"children": [{"id": "user_3"}], "has_more": False})],
            resume_state=EasypostResumeConfig(after_id="user_2"),
        )
        assert result.raised is None
        assert result.params("after_id") == ["user_2"]

    def test_api_keys_never_reach_the_warehouse(self) -> None:
        result = _driver().run(
            "child_users",
            [
                ScriptedResponse(
                    json={
                        "children": [
                            {
                                "id": "user_1",
                                "name": "Child",
                                "api_keys": [{"object": "ApiKey", "key": "EZAKfake0000", "mode": "production"}],
                                "children": [{"id": "user_2", "api_keys": [{"key": "EZAKfake1111"}]}],
                            }
                        ],
                        "has_more": False,
                    }
                )
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "user_1", "name": "Child", "children": [{"id": "user_2"}]}]


class TestUspsClaims:
    def test_paginates_the_nested_carrier_claims_path(self) -> None:
        result = _driver().run(
            "usps_claims",
            [
                ScriptedResponse(json={"usps_claims": [{"id": "usc_1"}, {"id": "usc_2"}], "has_more": True}),
                ScriptedResponse(json={"usps_claims": [{"id": "usc_3"}], "has_more": False}),
            ],
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["usc_1", "usc_2", "usc_3"]
        assert result.paths == ["/v2/carrier_claims/usps_claims"] * 2
        assert result.params("before_id") == [None, "usc_2"]
        assert result.params("start_datetime") == [None, None]


REPORT_TYPES = EASYPOST_ENDPOINTS["reports"].path_values


class TestReports:
    def test_walks_every_report_type_and_resets_the_cursor(self) -> None:
        responses = [
            ScriptedResponse(json={"reports": [{"id": "cfrep_1"}, {"id": "cfrep_2"}], "has_more": True}),
            ScriptedResponse(json={"reports": [{"id": "cfrep_3"}], "has_more": False}),
            *[ScriptedResponse(json={"reports": [], "has_more": False}) for _ in REPORT_TYPES[1:-1]],
            ScriptedResponse(json={"reports": [{"id": "trkrep_1", "url": "https://example.com/signed"}]}),
        ]
        result = _driver().run("reports", responses)
        assert result.raised is None
        assert result.rows == [{"id": "cfrep_1"}, {"id": "cfrep_2"}, {"id": "cfrep_3"}, {"id": "trkrep_1"}]
        assert result.paths == [
            "/v2/reports/cash_flow",
            *[f"/v2/reports/{report_type}" for report_type in REPORT_TYPES],
        ]
        assert result.params("before_id") == [None, "cfrep_2", *[None] * (len(REPORT_TYPES) - 1)]
        assert result.saved_states == [
            EasypostResumeConfig(before_id=None, path_value="cash_flow"),
            EasypostResumeConfig(before_id="cfrep_2", path_value="cash_flow"),
            EasypostResumeConfig(before_id=None, path_value="tracker"),
        ]

    @parameterized.expand(
        [
            ("mid_type", EasypostResumeConfig(before_id="shprep_9", path_value="shipment"), "shipment", "shprep_9"),
            ("unknown_type", EasypostResumeConfig(before_id="xrep_1", path_value="retired"), "cash_flow", None),
            ("legacy_state", EasypostResumeConfig(before_id="shprep_9"), "cash_flow", None),
        ]
    )
    def test_resume(
        self, _name: str, state: EasypostResumeConfig, first_type: str, first_before_id: str | None
    ) -> None:
        expected_types = REPORT_TYPES[REPORT_TYPES.index(first_type) :]
        result = _driver().run(
            "reports",
            [ScriptedResponse(json={"reports": [], "has_more": False}) for _ in expected_types],
            resume_state=state,
        )
        assert result.raised is None
        assert result.paths == [f"/v2/reports/{t}" for t in expected_types]
        assert result.params("before_id") == [first_before_id, *[None] * (len(expected_types) - 1)]


class TestUnpaginatedEndpoints:
    @parameterized.expand([("carrier_accounts", "/carrier_accounts"), ("carrier_types", "/carrier_types")])
    def test_bare_list_response_is_yielded_whole(self, endpoint: str, path: str) -> None:
        # These endpoints answer with a bare JSON array, not the {"<name>": [...]} wrapper every
        # other endpoint uses, so extraction has to branch on the endpoint rather than the payload.
        result = _driver().run(endpoint, [ScriptedResponse(json=[{"id": "x_1"}, {"id": "x_2"}])])
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["x_1", "x_2"]
        assert result.urls == [f"https://api.easypost.com/v2{path}"]

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
        [
            ("ok", 200, True),
        ]
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
        assert result.session_options == [{"redact_values": ("secret-key",), "capture": True}]

    def test_endpoints_that_strip_fields_are_not_captured(self) -> None:
        result = _driver().run("reports", [ScriptedResponse(json={"reports": [], "has_more": False}) for _ in range(7)])
        assert result.raised is None
        assert all(options["capture"] is False for options in result.session_options)


class TestEasypostSource:
    @parameterized.expand([(name,) for name in ENDPOINTS if not EASYPOST_ENDPOINTS[name].ascending])
    def test_source_response_shape(self, endpoint: str) -> None:
        config = EASYPOST_ENDPOINTS[endpoint]
        payload: Any = [] if config.returns_bare_list else {config.response_key or endpoint: [], "has_more": False}
        result = _driver().run(endpoint, always(ScriptedResponse(json=payload)))
        response = result.response
        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys
        # EasyPost returns newest-first; the watermark logic depends on this being declared.
        assert response.sort_mode == "desc"
