from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel import (
    DeelResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.settings import (
    DEEL_API_VERSION_2026_01_01,
    DEEL_API_VERSION_V2,
    DEEL_ENDPOINTS,
    ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.source import DeelSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.deel import DeelSourceConfig

# (pin, base URL, version headers): the legacy pin sends no selector, the dated pin sends X-Version.
VERSION_WIRES = [
    (DEEL_API_VERSION_V2, "https://api.letsdeel.com/rest/v2", {}),
    (DEEL_API_VERSION_2026_01_01, "https://api.letsdeel.com/rest", {"X-Version": "2026-01-01"}),
]


def _driver() -> SourceDriver:
    return SourceDriver(DeelSource(), DeelSourceConfig(api_token="token"))


def _response(items: list[dict[str, Any]] | None, *, cursor: str | None = None) -> ScriptedResponse:
    page: dict[str, Any] = {"total_rows": len(items or [])}
    if cursor is not None:
        page["cursor"] = cursor
    return ScriptedResponse(json={"page": page, "data": items or []})


def _payroll_response(
    items: list[dict[str, Any]], *, next_cursor: str | None = None, has_more: bool = False
) -> ScriptedResponse:
    # Payroll cycles and gross-to-net put both the cursor and the flag at the top level.
    return ScriptedResponse(json={"data": items, "has_more": has_more, "next_cursor": next_cursor})


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            # A valid token without people:read still 403s; only 401 means the token is bad.
            (403, (True, None)),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: tuple[bool, str | None]) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]):
            assert validate_credentials("token", DEEL_API_VERSION_V2) == expected

    @pytest.mark.parametrize("api_version, base_url, version_headers", VERSION_WIRES)
    def test_validate_credentials_probes_on_the_pinned_version(
        self, api_version: str, base_url: str, version_headers: dict[str, str]
    ) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("token", api_version)

        request = network.requests_log[0]
        assert request.url == f"{base_url}/people?limit=1"
        assert request.headers["authorization"] == "Bearer token"
        assert {name: value for name, value in request.headers.items() if name == "x-version"} == {
            name.lower(): value for name, value in version_headers.items()
        }


class TestOffsetPagination:
    def test_paginates_until_short_page(self) -> None:
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        result = _driver().run("people", [_response(full_page), _response([{"id": "last"}])], api_version="v2")

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [*(str(i) for i in range(PAGE_SIZE)), "last"]
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("limit") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # Checkpoint saved once after the first full page; the short page ends the walk.
        assert result.saved_states == [DeelResumeConfig(offset=PAGE_SIZE)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("people", [_response([])], resume_state=DeelResumeConfig(offset=150), api_version="v2")

        assert result.raised is None
        assert result.params("offset") == ["150"]


class TestCursorPagination:
    def test_paginates_via_after_cursor(self) -> None:
        result = _driver().run(
            "contracts", [_response([{"id": "1"}], cursor="cur_abc"), _response([{"id": "2"}])], api_version="v2"
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert result.params("limit") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        assert result.params("after_cursor") == [None, "cur_abc"]
        assert result.saved_states == [DeelResumeConfig(cursor="cur_abc")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "contracts", [_response([])], resume_state=DeelResumeConfig(cursor="cur_resume"), api_version="v2"
        )

        assert result.raised is None
        assert result.params("after_cursor") == ["cur_resume"]


class TestDeelSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = DEEL_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [ScriptedResponse(json={"data": []})])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestTimeOffEvents:
    def test_skips_a_person_that_disappeared_between_the_listing_and_the_fetch(self) -> None:
        result = _driver().run(
            "time_off_events",
            [
                _response([{"id": "prof_1"}, {"id": "prof_2"}]),
                ScriptedResponse(status=404, json={}),
                ScriptedResponse(json={"data": [{"id": "ev_2", "hris_profile_id": "prof_2"}]}),
            ],
            api_version="v2",
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["ev_2"]


class TestPayrollEndpoints:
    def test_payroll_cycles_fan_out_and_carry_their_legal_entity(self) -> None:
        result = _driver().run(
            "payroll_cycles",
            [
                _response([{"id": "le_1"}]),
                _payroll_response([{"id": "cy_1"}], next_cursor="cur_1", has_more=True),
                _payroll_response([{"id": "cy_2"}], has_more=False),
            ],
            api_version="v2",
        )

        assert result.raised is None
        assert result.paths[1:] == ["/rest/v2/legal-entities/le_1/payroll-events"] * 2
        assert result.requests[2].param("cursor") == "cur_1"
        assert result.requests[1].param("limit") == str(PAGE_SIZE)
        assert [(row["id"], row["legal_entity_id"]) for row in result.rows] == [
            ("cy_1", "le_1"),
            ("cy_2", "le_1"),
        ]


class TestGrossToNet:
    def test_resume_skips_cycles_already_emitted(self) -> None:
        result = _driver().run(
            "payroll_gross_to_net",
            [
                _response([{"id": "le_1"}]),
                _payroll_response([{"id": "cy_1", "has_g2n_report": True}, {"id": "cy_2", "has_g2n_report": True}]),
                _payroll_response([{"contract_oid": "con_2"}]),
            ],
            resume_state=DeelResumeConfig(completed=["le_1:cy_1"]),
            api_version="v2",
        )

        assert result.raised is None
        assert result.paths[-1] == "/rest/v2/reports/payroll/cycles/cy_2/gross-to-net"
        assert [row["cycle_id"] for row in result.rows] == ["cy_2"]
        assert result.saved_states == [DeelResumeConfig(completed=["le_1:cy_1", "le_1:cy_2"])]

    def test_skips_a_cycle_whose_report_went_away(self) -> None:
        # A cycle can flag a report that 404s by the time we ask for it; that must not fail
        # the whole sync.
        result = _driver().run(
            "payroll_gross_to_net",
            [
                _response([{"id": "le_1"}]),
                _payroll_response([{"id": "cy_1", "has_g2n_report": True}, {"id": "cy_2", "has_g2n_report": True}]),
                ScriptedResponse(status=404, json={}),
                _payroll_response([{"contract_oid": "con_2"}]),
            ],
            api_version="v2",
        )

        assert result.raised is None
        assert [row["contract_oid"] for row in result.rows] == ["con_2"]

    def test_stops_a_report_that_keeps_echoing_the_same_cursor(self) -> None:
        result = _driver().run(
            "payroll_gross_to_net",
            [
                _response([{"id": "le_1"}]),
                _payroll_response([{"id": "cy_1", "has_g2n_report": True}]),
                _payroll_response([{"contract_oid": "con_1"}], next_cursor="cur_1", has_more=True),
                _payroll_response([{"contract_oid": "con_1"}], next_cursor="cur_1", has_more=True),
            ],
            api_version="v2",
        )

        assert result.raised is None
        assert [row["contract_oid"] for row in result.rows] == ["con_1", "con_1"]
        assert len(result.requests) == 4


class TestDatedVersionEndpoints:
    @pytest.mark.parametrize(
        "endpoint, path, x_version, cursor_key, cursor_param, page_size_param, page_size, has_more_key",
        [
            ("it_seats", "/it/seats", "2026-09-25", "next_cursor", "cursor", "limit", 20, "has_more"),
            (
                "it_clearance_requests",
                "/it/clearance-requests",
                "2026-09-16",
                "next_cursor",
                "cursor",
                "limit",
                20,
                "has_more",
            ),
            (
                "time_off_policies",
                "/time-offs/policy",
                "2026-09-09",
                "next",
                "next",
                "page_size",
                PAGE_SIZE,
                "has_next_page",
            ),
            ("equity_awards", "/equity-awards", "2026-09-09", "next_cursor", "cursor", "limit", PAGE_SIZE, "has_more"),
        ],
    )
    def test_walks_on_the_endpoints_own_published_version(
        self,
        endpoint: str,
        path: str,
        x_version: str,
        cursor_key: str,
        cursor_param: str,
        page_size_param: str,
        page_size: int,
        has_more_key: str,
    ) -> None:
        # These endpoints were published after the 2026-01-01 baseline, and Deel rejects a date an
        # endpoint was not published under, so each one must send its own date.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"data": [{"id": "a"}], has_more_key: True, cursor_key: "cur_1"}),
                ScriptedResponse(json={"data": [{"id": "b"}], has_more_key: False, cursor_key: None}),
            ],
            api_version=DEEL_API_VERSION_2026_01_01,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a", "b"]
        assert result.paths == [f"/rest{path}"] * 2
        assert all(request.origin == "https://api.letsdeel.com" for request in result.requests)
        assert all(request.headers["x-version"] == x_version for request in result.requests)
        assert result.requests[0].param(page_size_param) == str(page_size)
        assert result.requests[1].param(cursor_param) == "cur_1"

    def test_an_undeclared_pin_fails_instead_of_sending_no_version(self) -> None:
        result = _driver().run("people", [], api_version="2099-01-01")

        assert isinstance(result.raised, ValueError)
        assert "Unsupported Deel API version" in str(result.raised)
