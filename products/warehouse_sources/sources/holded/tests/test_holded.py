from typing import Any

import pytest

import requests

from products.warehouse_sources.sources.holded._config import HoldedSourceConfig
from products.warehouse_sources.sources.holded.holded import HoldedResumeConfig
from products.warehouse_sources.sources.holded.source import INVALID_KEY_MESSAGE, HoldedSource
from products.warehouse_sources.sources.sdk.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)

# Holded's verbatim answer to a request with a missing or unknown key.
ACCESS_DENIED = {
    "type": "https://api.holded.com/problems/forbidden",
    "title": "Forbidden",
    "status": 403,
    "detail": "Access denied.",
}


def _driver() -> SourceDriver:
    return SourceDriver(HoldedSource(), HoldedSourceConfig(api_key="test-key"))


def _page(ids: list[str], cursor: str | None, has_more: bool | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"items": [{"id": i} for i in ids], "cursor": cursor}
    body["has_more"] = cursor is not None if has_more is None else has_more
    return ScriptedResponse(json=body)


class TestHoldedPagination:
    def test_walks_cursor_pages_and_saves_each_cursor_before_its_page(self) -> None:
        result = _driver().run(
            "invoices",
            [_page(["a"], "c1"), _page(["b"], "c2"), _page(["c"], None)],
        )

        assert result.raised is None
        assert result.paths == ["/api/v2/invoices"] * 3
        assert result.params("cursor") == [None, "c1", "c2"]
        assert result.params("limit") == ["200", "200", "200"]
        assert result.requests[0].headers["authorization"] == "Bearer test-key"
        assert [row["id"] for row in result.rows] == ["a", "b", "c"]
        assert result.saved_states == [HoldedResumeConfig(cursor="c1"), HoldedResumeConfig(cursor="c2")]

    def test_has_more_false_stops_the_walk_even_with_a_cursor(self) -> None:
        result = _driver().run("contacts", [_page(["a"], "stale-cursor", has_more=False)])

        assert result.raised is None
        assert result.params("cursor") == [None]
        assert [row["id"] for row in result.rows] == ["a"]

    def test_resume_starts_from_the_saved_cursor(self) -> None:
        result = _driver().run(
            "invoices",
            [_page(["c"], None)],
            resume_state=HoldedResumeConfig(cursor="c2"),
        )

        assert result.params("cursor") == ["c2"]
        assert [row["id"] for row in result.rows] == ["c"]

    @pytest.mark.parametrize(
        "endpoint, path, expected_params",
        [
            (
                "ledger_entries",
                "/api/v2/ledger-entries",
                {"start_date": ("1970-01-01",), "end_date": ("2099-12-31",), "limit": ("200",)},
            ),
            ("services", "/api/v2/services", {"include_archived": ("true",), "limit": ("100",)}),
            (
                "employee_time_offs",
                "/api/v2/employees/time-offs",
                {"start_date_from": ("1970-01-01",), "start_date_to": ("2099-12-31",), "limit": ("100",)},
            ),
            ("contacts", "/api/v2/contacts", {"limit": ("100",)}),
            ("warehouses", "/api/v2/warehouses", {}),
            (
                "accounting_accounts",
                "/api/v2/accounting-accounts",
                {"archived": ("true",), "include_empty": ("true",)},
            ),
        ],
    )
    def test_request_shape_per_endpoint(self, endpoint: str, path: str, expected_params: dict[str, Any]) -> None:
        result = _driver().run(endpoint, [_page(["a"], None)])

        assert result.raised is None
        assert result.paths == [path]
        assert dict(result.requests[0].query) == expected_params

    def test_single_page_endpoint_ignores_a_cursor_in_the_body(self) -> None:
        result = _driver().run("taxes", [_page(["vat"], "unexpected-cursor", has_more=True)])

        assert result.raised is None
        assert result.paths == ["/api/v2/taxes"]
        assert [row["id"] for row in result.rows] == ["vat"]


ACCOUNTS = "/api/v2/treasury/accounts"


def _movements(account_id: str) -> str:
    return f"/api/v2/treasury/accounts/{account_id}/bank-movements"


def _bank_movement_script() -> Any:
    return route(
        {
            _movements("acc1"): [_page(["m1"], "c1"), _page(["m2"], None)],
            _movements("acc2"): [_page(["m3"], None)],
            ACCOUNTS: [_page(["acc1"], "p1"), _page(["acc2"], None)],
        }
    )


class TestHoldedBankMovements:
    def test_fans_out_over_every_treasury_account_page_and_movement_page(self) -> None:
        result = _driver().run("bank_movements", _bank_movement_script())

        assert result.raised is None
        assert [(row["treasury_account_id"], row["id"]) for row in result.rows] == [
            ("acc1", "m1"),
            ("acc1", "m2"),
            ("acc2", "m3"),
        ]
        by_path = [(r.path, r.param("cursor"), r.param("limit")) for r in result.requests]
        assert [entry for entry in by_path if entry[0] == ACCOUNTS] == [
            (ACCOUNTS, None, "100"),
            (ACCOUNTS, "p1", "100"),
        ]
        assert [entry for entry in by_path if entry[0] == _movements("acc1")] == [
            (_movements("acc1"), None, "200"),
            (_movements("acc1"), "c1", "200"),
        ]

    def test_resume_continues_the_account_that_was_in_progress(self) -> None:
        first = _driver().run("bank_movements", _bank_movement_script())
        mid_account = next(
            state
            for state in first.saved_states
            if state.fanout_state and state.fanout_state.get("child_state", {}) and not state.fanout_state["completed"]
        )

        result = _driver().run(
            "bank_movements",
            route(
                {
                    _movements("acc1"): [_page(["m2"], None)],
                    _movements("acc2"): [_page(["m3"], None)],
                    ACCOUNTS: [_page(["acc1"], "p1"), _page(["acc2"], None)],
                }
            ),
            resume_state=mid_account,
        )

        assert result.raised is None
        assert [r.param("cursor") for r in result.requests if r.path == _movements("acc1")] == ["c1"]
        assert [row["id"] for row in result.rows] == ["m2", "m3"]


class TestHoldedValidateCredentials:
    @pytest.mark.parametrize(
        "answer, expected",
        [
            (always(ScriptedResponse(json={"id": "acc_1", "name": "Acme"})), (True, None)),
            (always(ScriptedResponse(status=403, json=ACCESS_DENIED)), (False, INVALID_KEY_MESSAGE)),
            (always(ScriptedResponse(status=401, json={"status": 401})), (False, INVALID_KEY_MESSAGE)),
            (
                always(ScriptedResponse(status=429, json={"status": 429}, headers={"Retry-After": "0"})),
                (False, "Holded rate limited the request. Wait a minute, then try again."),
            ),
            (
                always(requests.ConnectionError("connection refused")),
                (False, "Couldn't connect to Holded. Try again, and if it keeps happening contact support."),
            ),
        ],
    )
    def test_maps_the_account_probe_to_a_result(self, answer: Any, expected: tuple[bool, str | None]) -> None:
        with scripted_network(answer) as network:
            result = HoldedSource().validate_credentials(HoldedSourceConfig(api_key="test-key"), team_id=1)

        assert result == expected
        assert {request.path for request in network.requests_log} == {"/api/v2/account"}
        assert network.requests_log[0].headers["authorization"] == "Bearer test-key"
