from datetime import UTC, date, datetime

from parameterized import parameterized
from requests import PreparedRequest
from requests.structures import CaseInsensitiveDict

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.fleetio import (
    FLEETIO_API_VERSION,
    FLEETIO_LEGACY_VERSION,
    FLEETIO_VERSION_2025_05_05,
    FleetioAuth,
    FleetioResumeConfig,
    _build_base_params,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.settings import FLEETIO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.source import FleetioSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fleetio import (
    FleetioSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(FleetioSource(), FleetioSourceConfig(api_key="k", account_token="a"))


def _response(records: list[dict[str, object]], next_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"records": records, "next_cursor": next_cursor})


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "some-cursor", "some-cursor"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestFleetioAuth:
    def test_sets_both_credential_headers(self) -> None:
        request = PreparedRequest()
        request.headers = CaseInsensitiveDict()
        FleetioAuth("key123", "acct456")(request)
        assert request.headers["Authorization"] == "Token key123"
        assert request.headers["Account-Token"] == "acct456"

    def test_reports_both_credentials_as_secret_for_redaction(self) -> None:
        # Both the API key and the account token must be masked in HTTP telemetry; the account-token
        # header name isn't one the generic scrubbers recognise, so value-based redaction is required.
        assert set(FleetioAuth("key123", "acct456").secret_values()) == {"key123", "acct456"}


class TestBuildBaseParams:
    def test_incremental_on_created_at_filters_created_at(self) -> None:
        params = _build_base_params(
            FLEETIO_ENDPOINTS["fuel_entries"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert params["sort[created_at]"] == "asc"
        assert params["filter[created_at][gt]"] == "2026-01-01T00:00:00+00:00"


class TestPagination:
    def test_paginates_until_next_cursor_is_null(self) -> None:
        result = _driver().run("vehicles", [_response([{"id": 1}, {"id": 2}], "CUR2"), _response([{"id": 3}], None)])

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        # First page carries no cursor; the second is fetched with the cursor from page one.
        assert result.params("start_cursor") == [None, "CUR2"]
        assert result.params("per_page") == ["100", "100"]
        assert result.params("sort[created_at]") == ["asc", "asc"]
        # Checkpoint saved once (pointing at the next page); the terminal page saves nothing.
        assert result.saved_states == [FleetioResumeConfig(start_cursor="CUR2")]

    def test_resume_starts_from_saved_cursor(self) -> None:
        result = _driver().run(
            "vehicles", [_response([{"id": 9}], None)], resume_state=FleetioResumeConfig(start_cursor="SAVED")
        )

        assert result.raised is None
        assert result.rows == [{"id": 9}]
        assert result.params("start_cursor") == ["SAVED"]

    @parameterized.expand(
        [
            # The "v1" pin sends the 2024-06-30 date version under the integer `/api/v1` path;
            # 2025-05-05 drops the integer segment and moves resources to `/api/{resource}`.
            (FLEETIO_LEGACY_VERSION, FLEETIO_API_VERSION, "https://secure.fleetio.com/api/v1/vehicles"),
            (FLEETIO_VERSION_2025_05_05, "2025-05-05", "https://secure.fleetio.com/api/vehicles"),
        ]
    )
    def test_version_selects_header_and_base_path(
        self, api_version: str, expected_header: str, expected_url: str
    ) -> None:
        result = _driver().run("vehicles", [_response([{"id": 1}], None)], api_version=api_version)

        assert result.raised is None
        assert result.requests[0].headers["x-api-version"] == expected_header
        assert result.requests[0].url.split("?", 1)[0] == expected_url

    def test_unsupported_version_pin_raises(self) -> None:
        # A pin outside the supported map must fail loudly rather than fall through to no version
        # header (which would silently track "latest").
        result = _driver().run("vehicles", [], api_version="1999-01-01")

        assert isinstance(result.raised, ValueError)
        assert "Unsupported Fleetio API version" in str(result.raised)
        assert result.requests == []

    def test_bare_list_body_fails_loudly(self) -> None:
        # A bare list means the version pin was ignored (legacy page-based response) — fail loud
        # instead of silently truncating to one page.
        result = _driver().run("vehicles", [ScriptedResponse(json=[{"id": 1}])])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)
        assert result.rows == []


class TestValidateCredentials:
    def test_network_error_is_not_valid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("k", "a", FLEETIO_VERSION_2025_05_05) is False

        assert network.requests_log[0].path == "/api/vehicles"


class TestServiceEntryLineItemsFanout:
    """The only fan-out endpoint: line items are listed per service entry, never account-wide."""

    @parameterized.expand(
        [
            # Fleetio removed `/v1/service_entries` when it moved the resource to v2, so a legacy
            # pin that assumes one shared generation segment cannot list the fan-out's parents.
            (FLEETIO_LEGACY_VERSION, "/api/v2/service_entries", "/api/v2/service_entries/11/service_entry_line_items"),
            (FLEETIO_VERSION_2025_05_05, "/api/service_entries", "/api/service_entries/11/service_entry_line_items"),
        ]
    )
    def test_parent_and_child_carry_their_own_version_segment(
        self, api_version: str, parent_path: str, child_path: str
    ) -> None:
        result = _driver().run(
            "service_entry_line_items",
            [_response([{"id": 11}], None), _response([{"id": 101}], None)],
            api_version=api_version,
        )

        assert result.raised is None
        assert result.paths == [parent_path, child_path]


class TestPurchaseOrderLineItemsFanout:
    """Line items are listed per purchase order, and the path binds the order's number, not its id."""

    def test_checkpoints_by_parent_and_resumes_past_completed_parents(self) -> None:
        completed = "/purchase_orders/4001/purchase_order_line_items"
        result = _driver().run(
            "purchase_order_line_items",
            [
                _response([{"id": 11, "number": 4001}, {"id": 22, "number": 4002}], None),
                _response([{"id": 201}], None),
            ],
            resume_state=FleetioResumeConfig(completed=[completed], current=None, child_state=None),
        )

        assert result.raised is None
        assert [row["purchase_order_number"] for row in result.rows] == [4002]
        assert result.paths == ["/api/purchase_orders", "/api/purchase_orders/4002/purchase_order_line_items"]
        assert any(state.completed is not None and completed in state.completed for state in result.saved_states)


class TestLocationEntriesFanout:
    @parameterized.expand(
        [
            (FLEETIO_LEGACY_VERSION, "/api/v1/vehicles", "/api/v1/vehicles/7/location_entries"),
            (FLEETIO_VERSION_2025_05_05, "/api/vehicles", "/api/vehicles/7/location_entries"),
        ]
    )
    def test_lists_entries_per_vehicle_and_keys_them_by_the_parent(
        self, api_version: str, parent_path: str, child_path: str
    ) -> None:
        result = _driver().run(
            "location_entries",
            [
                _response([{"id": 7}], None),
                _response([{"id": 501, "location": "40.0,-75.0"}, {"id": 502, "vehicle_id": 7}], None),
            ],
            api_version=api_version,
        )

        assert result.raised is None
        assert result.paths == [parent_path, child_path]
        assert [(row["vehicle_id"], row["id"]) for row in result.rows] == [(7, 501), (7, 502)]
