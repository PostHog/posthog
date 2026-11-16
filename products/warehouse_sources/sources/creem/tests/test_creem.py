from typing import Any, Literal

import pytest

from products.warehouse_sources.sources.creem._config import CreemSourceConfig
from products.warehouse_sources.sources.creem.creem import (
    INVALID_KEY_ERROR,
    UNVERIFIED_KEY_ERROR,
    CreemResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.sources.creem.source import CreemSource
from products.warehouse_sources.sources.sdk.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)


def _driver(environment: Literal["production", "test"] = "production") -> SourceDriver:
    return SourceDriver(CreemSource(), CreemSourceConfig(api_key="creem_test_key", environment=environment))


def _page(ids: list[str], next_page: int | None) -> ScriptedResponse:
    return ScriptedResponse(json={"items": [{"id": row_id} for row_id in ids], "pagination": {"next_page": next_page}})


def _cursor_page(ids: list[str], has_more: bool) -> ScriptedResponse:
    return ScriptedResponse(json={"object": "list", "data": [{"id": row_id} for row_id in ids], "has_more": has_more})


class TestPageNumberListings:
    @pytest.mark.parametrize(
        ("environment", "origin"),
        [("production", "https://api.creem.io"), ("test", "https://test-api.creem.io")],
    )
    def test_walks_next_page_to_the_last_page(self, environment: Literal["production", "test"], origin: str) -> None:
        result = _driver(environment).run(
            "Products",
            [_page(["p1"], 2), _page(["p2"], 3), _page(["p3"], None)],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["p1", "p2", "p3"]
        assert {request.origin for request in result.requests} == {origin}
        assert {request.headers["x-api-key"] for request in result.requests} == {"creem_test_key"}
        assert result.params("page_number") == ["1", "2", "3"]
        assert result.params("page_size") == ["50", "50", "50"]
        assert result.saved_states == [CreemResumeConfig(page_number=2), CreemResumeConfig(page_number=3)]
        # License keys arrive under `key`, which the sample scrubber keeps, so no Creem body may be sampled.
        assert result.session_options and all(options.get("capture") is False for options in result.session_options)

    @pytest.mark.parametrize(
        ("script", "expected_pages"),
        [
            # A next_page that does not move forward would request the same page forever.
            ([_page(["p1"], 1)], ["1"]),
            # An empty page ends the walk even when next_page still names a page.
            ([_page(["p1"], 2), _page([], 3)], ["1", "2"]),
            # Without a pagination envelope, the walk stops at the first empty page.
            (
                [ScriptedResponse(json={"items": [{"id": "p1"}]}), ScriptedResponse(json={"items": []})],
                ["1", "2"],
            ),
        ],
    )
    def test_stops_on_unusual_termination_signals(
        self, script: list[ScriptedResponse], expected_pages: list[str]
    ) -> None:
        result = _driver().run("Customers", script)

        assert result.raised is None
        assert result.params("page_number") == expected_pages

    def test_a_response_without_items_fails_the_run(self) -> None:
        result = _driver().run("Subscriptions", [ScriptedResponse(json={"data": [{"id": "s1"}]})])

        assert result.raised is not None
        assert result.rows == []


class TestCursorListings:
    def test_sends_the_last_id_as_starting_after_while_has_more(self) -> None:
        result = _driver().run(
            "Meters",
            [_cursor_page(["m1", "m2"], True), _cursor_page(["m3"], True), _cursor_page(["m4"], False)],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["m1", "m2", "m3", "m4"]
        assert result.params("starting_after") == [None, "m2", "m3"]
        assert result.params("limit") == ["100", "100", "100"]
        assert result.params("include_archived") == ["true", "true", "true"]
        assert result.saved_states == [
            CreemResumeConfig(starting_after="m2"),
            CreemResumeConfig(starting_after="m3"),
        ]

    @pytest.mark.parametrize(
        "last_page",
        [
            _cursor_page([], True),
            # The same cursor twice means the listing is not advancing.
            _cursor_page(["e1"], True),
        ],
    )
    def test_stops_when_has_more_cannot_advance(self, last_page: ScriptedResponse) -> None:
        result = _driver().run("UsageEvents", [_cursor_page(["e1"], True), last_page])

        assert result.raised is None
        assert result.params("starting_after") == [None, "e1"]


class TestResume:
    @pytest.mark.parametrize(
        ("endpoint", "resume_state", "script", "param", "expected"),
        [
            ("Transactions", CreemResumeConfig(page_number=4), [_page(["t1"], None)], "page_number", ["4"]),
            (
                "CreditAccounts",
                CreemResumeConfig(starting_after="acc_9"),
                [_cursor_page(["acc_10"], False)],
                "starting_after",
                ["acc_9"],
            ),
        ],
    )
    def test_resume_starts_from_the_saved_position(
        self,
        endpoint: str,
        resume_state: CreemResumeConfig,
        script: list[ScriptedResponse],
        param: str,
        expected: list[str],
    ) -> None:
        result = _driver().run(endpoint, script, resume_state=resume_state)

        assert result.raised is None
        assert result.params(param) == expected


class TestLicenses:
    def test_fans_out_over_customers_and_skips_a_deleted_customer(self) -> None:
        result = _driver().run(
            "Licenses",
            route(
                {
                    "/v1/customers/list": [_page(["cust_1", "cust_2"], 2), _page(["cust_3"], None)],
                    "/v1/customers/cust_1/licenses": [_page(["lic_1"], 2), _page(["lic_2"], None)],
                    "/v1/customers/cust_2/licenses": [ScriptedResponse(status=404, json={"status": 404})],
                    "/v1/customers/cust_3/licenses": [_page(["lic_3"], None)],
                }
            ),
        )

        assert result.raised is None
        rows: list[dict[str, Any]] = result.rows
        assert [(row["customer_id"], row["id"]) for row in rows] == [
            ("cust_1", "lic_1"),
            ("cust_1", "lic_2"),
            ("cust_3", "lic_3"),
        ]

    def test_resume_restarts_the_customer_listing_near_the_saved_page(self) -> None:
        customer_pages = [_page(["cust_1"], 2), _page(["cust_2"], 3), _page(["cust_3", "cust_4"], None)]
        first = _driver().run(
            "Licenses",
            route(
                {
                    "/v1/customers/list": customer_pages,
                    **{f"/v1/customers/cust_{n}/licenses": [_page([f"lic_{n}"], None)] for n in range(1, 5)},
                }
            ),
        )
        after_cust_3 = next(
            state
            for state in first.saved_states
            if state.fanout_state and "/v1/customers/cust_3/licenses" in state.fanout_state["completed"]
        )

        result = _driver().run(
            "Licenses",
            route(
                {
                    "/v1/customers/list": customer_pages[1:],
                    "/v1/customers/cust_4/licenses": [_page(["lic_4"], None)],
                }
            ),
            resume_state=after_cust_3,
        )

        assert result.raised is None
        assert [request.param("page_number") for request in result.requests if request.path.endswith("/list")] == [
            "2",
            "3",
        ]
        assert [row["id"] for row in result.rows] == ["lic_4"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("answer", "expected"),
        [
            (ScriptedResponse(json={"items": [], "pagination": {"next_page": None}}), (True, None)),
            (
                ScriptedResponse(status=401, json={"status": 401, "message": ["Invalid API Key"]}),
                (False, INVALID_KEY_ERROR),
            ),
            (ScriptedResponse(status=403, json={"status": 403}), (False, INVALID_KEY_ERROR)),
            (ScriptedResponse(status=500, json={"status": 500}), (False, UNVERIFIED_KEY_ERROR)),
        ],
    )
    def test_maps_the_probe_response(self, answer: ScriptedResponse, expected: tuple[bool, str | None]) -> None:
        with scripted_network(always(answer)) as network:
            assert validate_credentials("creem_test_key", "test") == expected

        assert {request.url for request in network.requests_log} == {
            "https://test-api.creem.io/v1/products/search?page_number=1&page_size=1"
        }
