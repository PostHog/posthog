from typing import Any

import pytest

from products.warehouse_sources.sources.memberful._config import MemberfulSourceConfig
from products.warehouse_sources.sources.memberful.memberful import (
    ACCOUNT_NOT_FOUND_MESSAGE,
    INVALID_SUBDOMAIN_MESSAGE,
    MemberfulResumeConfig,
    graphql_url,
    validate_credentials,
)
from products.warehouse_sources.sources.memberful.source import MemberfulSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network

INVALID_TOKEN_BODY = {"errors": [{"message": "Invalid authentication token."}]}
NOT_FOUND_HTML = b"<!DOCTYPE html><html><head><title>We couldn't find that page</title></head></html>"


def _driver(subdomain: str = "acme") -> SourceDriver:
    return SourceDriver(MemberfulSource(), MemberfulSourceConfig(subdomain=subdomain, api_key="mf_key"))


def _page(root: str, nodes: list[dict[str, Any]], end_cursor: str | None, has_next_page: bool) -> ScriptedResponse:
    return ScriptedResponse(
        json={"data": {root: {"nodes": nodes, "pageInfo": {"endCursor": end_cursor, "hasNextPage": has_next_page}}}}
    )


def _variables(result: Any) -> list[dict[str, Any]]:
    return [request.json()["variables"] for request in result.requests]


class TestPagination:
    def test_walks_pages_until_has_next_page_is_false(self) -> None:
        # Memberful still returns an endCursor on the last page, so only hasNextPage ends the walk.
        result = _driver().run(
            "members",
            [
                _page("members", [{"id": "1"}, {"id": "2"}], "c1", True),
                _page("members", [{"id": "3"}], "c2", False),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert [v["after"] for v in _variables(result)] == [None, "c1"]
        assert all(v["first"] == 100 for v in _variables(result))
        assert {request.url.split("?")[0] for request in result.requests} == {"https://acme.memberful.com/api/graphql"}
        assert result.requests[0].headers["authorization"] == "Bearer mf_key"

    def test_empty_page_with_next_cursor_keeps_walking(self) -> None:
        result = _driver().run(
            "coupons",
            [
                _page("coupons", [], "c1", True),
                _page("coupons", [{"id": "9", "plans": [], "downloads": []}], None, False),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["9"]
        assert [v["after"] for v in _variables(result)] == [None, "c1"]

    def test_repeated_cursor_raises_instead_of_looping(self) -> None:
        result = _driver().run(
            "members",
            [_page("members", [{"id": "1"}], "c1", True), _page("members", [{"id": "2"}], "c1", True)],
        )

        assert isinstance(result.raised, ValueError)
        assert "not advancing" in str(result.raised)

    @pytest.mark.parametrize("schema", ["plans", "downloads"])
    def test_list_endpoints_make_one_unpaginated_request(self, schema: str) -> None:
        result = _driver().run(schema, [ScriptedResponse(json={"data": {schema: [{"id": "1"}, {"id": "2"}]}})])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert _variables(result) == [{}]
        assert "first" not in result.requests[0].json()["query"]


class TestIncrementalRequestShaping:
    @pytest.mark.parametrize(
        ("schema", "inputs", "expected_filter"),
        [
            (
                "activities",
                {"incremental_field": "createdAt", "db_incremental_field_last_value": 1700000000},
                {"gte": 1700000000},
            ),
            (
                "activities",
                {"incremental_field": "createdAt", "db_incremental_field_last_value": "1700000000"},
                {"gte": 1700000000},
            ),
            ("activities", {"incremental_field": "createdAt", "db_incremental_field_last_value": None}, None),
            (
                "activities",
                {
                    "incremental_field": "createdAt",
                    "should_use_incremental_field": False,
                    "db_incremental_field_last_value": 1700000000,
                },
                None,
            ),
        ],
    )
    def test_created_at_filter(self, schema: str, inputs: dict[str, Any], expected_filter: Any) -> None:
        result = _driver().run(schema, [_page(schema, [], None, False)], **inputs)

        assert result.raised is None
        assert _variables(result)[0]["createdAt"] == expected_filter
        assert "createdAt: $createdAt" in result.requests[0].json()["query"]

    @pytest.mark.parametrize(
        ("schema", "inputs"),
        [
            ("subscriptions", {}),
            # An order refunded after newer orders arrived must still be read on the next sync.
            ("orders", {"incremental_field": "createdAt", "db_incremental_field_last_value": 1700000000}),
        ],
    )
    def test_unfiltered_connection_sends_no_created_at_variable(self, schema: str, inputs: dict[str, Any]) -> None:
        refunded_old_order = {"uuid": "o-1", "createdAt": 1600000000, "status": "refunded"}
        result = _driver().run(schema, [_page(schema, [refunded_old_order], None, False)], **inputs)

        assert result.raised is None
        assert "createdAt" not in _variables(result)[0]
        assert "$createdAt" not in result.requests[0].json()["query"]
        assert len(result.rows) == 1


class TestResume:
    def test_resumes_from_saved_cursor_with_its_original_filter(self) -> None:
        result = _driver().run(
            "activities",
            [_page("activities", [{"id": "a-2"}], None, False)],
            resume_state=MemberfulResumeConfig(cursor="c5", created_at_gte=1600000000),
            incremental_field="createdAt",
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert _variables(result) == [{"first": 100, "after": "c5", "createdAt": {"gte": 1600000000}}]

    @pytest.mark.parametrize("schema", ["members", "plans"])
    def test_completed_state_reads_nothing(self, schema: str) -> None:
        result = _driver().run(schema, [], resume_state=MemberfulResumeConfig(completed=True))

        assert result.raised is None
        assert result.requests == []
        assert result.rows == []

    def test_state_is_committed_with_each_page_including_the_last(self) -> None:
        result = _driver().run(
            "members",
            [_page("members", [{"id": "1"}], "c1", True), _page("members", [{"id": "2"}], "c2", False)],
        )

        assert result.committed_states == [
            MemberfulResumeConfig(cursor="c1"),
            MemberfulResumeConfig(cursor=None, completed=True),
        ]


class TestRowShaping:
    def test_orders_flatten_references_and_keep_nulls(self) -> None:
        nodes = [
            {
                "uuid": "o-1",
                "createdAt": 1700000000,
                "totalCents": 1000,
                "purchasable": {"id": "p-1"},
                "member": {"id": "m-1"},
                "subscription": {"id": "s-1"},
                "coupon": {"id": "c-1", "code": "SAVE10"},
            },
            {
                "uuid": "o-2",
                "createdAt": 1700000100,
                "totalCents": 500,
                "purchasable": None,
                "member": {"id": "m-2"},
                "subscription": None,
                "coupon": None,
            },
        ]
        result = _driver().run("orders", [_page("orders", nodes, None, False)])

        assert result.rows == [
            {
                "uuid": "o-1",
                "createdAt": 1700000000,
                "totalCents": 1000,
                "purchasableId": "p-1",
                "memberId": "m-1",
                "subscriptionId": "s-1",
                "couponId": "c-1",
                "couponCode": "SAVE10",
            },
            {
                "uuid": "o-2",
                "createdAt": 1700000100,
                "totalCents": 500,
                "purchasableId": None,
                "memberId": "m-2",
                "subscriptionId": None,
                "couponId": None,
                "couponCode": None,
            },
        ]

    def test_coupons_collect_id_lists_and_skip_null_items(self) -> None:
        nodes = [{"id": "1", "plans": [{"id": "p-1"}, None, {"id": "p-2"}], "downloads": None}]
        result = _driver().run("coupons", [_page("coupons", nodes, None, False)])

        assert result.rows == [{"id": "1", "planIds": ["p-1", "p-2"], "downloadIds": None}]

    def test_plans_flatten_parent_pass(self) -> None:
        body = {"data": {"plans": [{"id": "1", "label": "$10/month", "pass": {"id": "10", "name": "Premium"}}]}}
        result = _driver().run("plans", [ScriptedResponse(json=body)])

        assert result.rows == [{"id": "1", "label": "$10/month", "passId": "10", "passName": "Premium"}]


class TestErrors:
    @pytest.mark.parametrize(
        ("script", "expected"),
        [
            (
                [ScriptedResponse(status=401, json=INVALID_TOKEN_BODY)],
                "401 Client Error: Unauthorized for url: https://acme.memberful.com/api/graphql "
                "(Memberful API: Invalid authentication token.)",
            ),
            ([ScriptedResponse(status=200, json=INVALID_TOKEN_BODY)], "Invalid authentication token"),
            ([ScriptedResponse(status=403, body=b"Forbidden")], "403 Client Error: Forbidden for url"),
            ([ScriptedResponse(status=404, body=NOT_FOUND_HTML)], "Memberful account not found"),
            (always(ScriptedResponse(status=503, body=b"Service Unavailable")), "Memberful API error (retryable)"),
        ],
    )
    def test_sync_errors_carry_the_text_the_source_maps(self, script: Any, expected: str) -> None:
        result = _driver().run("members", script)

        assert result.raised is not None
        assert expected in str(result.raised)

    def test_retries_a_rate_limit_then_succeeds(self) -> None:
        result = _driver().run(
            "members",
            [ScriptedResponse(status=429, json={}), _page("members", [{"id": "1"}], None, False)],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1"]
        assert len(result.requests) == 2

    def test_retry_after_beyond_the_request_budget_stops_after_one_request(self) -> None:
        result = _driver().run(
            "members", always(ScriptedResponse(status=429, json={}, headers={"Retry-After": "3600"}))
        )

        assert result.raised is not None
        assert "Memberful API error (retryable): status 429" in str(result.raised)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("response", "valid", "message_part"),
        [
            (ScriptedResponse(json={"data": {"members": {"pageInfo": {"hasNextPage": False}}}}), True, None),
            (ScriptedResponse(status=401, json=INVALID_TOKEN_BODY), False, "Invalid Memberful API key"),
            (ScriptedResponse(status=403, body=b"Forbidden"), False, "no API access"),
            (ScriptedResponse(status=404, body=NOT_FOUND_HTML), False, ACCOUNT_NOT_FOUND_MESSAGE),
        ],
    )
    def test_maps_probe_result(self, response: ScriptedResponse, valid: bool, message_part: str | None) -> None:
        with scripted_network([response]) as network:
            ok, message = validate_credentials("https://Acme.memberful.com/admin", "mf_key")

        assert ok is valid
        if message_part is None:
            assert message is None
        else:
            assert message is not None and message_part in message
        assert network.requests_log[0].url.startswith("https://acme.memberful.com/api/graphql")

    @pytest.mark.parametrize("subdomain", ["", "evil.com/x", "acme@evil.com", "a b", "-acme", "acme.example.com"])
    def test_invalid_subdomain_sends_no_request(self, subdomain: str) -> None:
        with scripted_network([]) as network:
            assert validate_credentials(subdomain, "mf_key") == (False, INVALID_SUBDOMAIN_MESSAGE)
        assert network.requests_log == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("acme", "https://acme.memberful.com/api/graphql"),
        ("  ACME  ", "https://acme.memberful.com/api/graphql"),
        ("acme.memberful.com", "https://acme.memberful.com/api/graphql"),
        ("https://acme.memberful.com/admin/members", "https://acme.memberful.com/api/graphql"),
        ("my-shop-2", "https://my-shop-2.memberful.com/api/graphql"),
    ],
)
def test_graphql_url_accepts_pasted_forms(value: str, expected: str) -> None:
    assert graphql_url(value) == expected
