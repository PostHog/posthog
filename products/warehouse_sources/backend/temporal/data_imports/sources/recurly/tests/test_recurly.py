from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recurly import (
    RecurlySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.recurly import (
    RecurlyPaginator,
    RecurlyResumeConfig,
    _extract_cursor,
    _format_datetime,
    _usage_add_ons,
    get_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.settings import RECURLY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.source import RecurlySource

INCREMENTAL_ENDPOINTS = [name for name, e in RECURLY_ENDPOINTS.items() if e.supports_incremental]
NO_LIST_PARAMS_ENDPOINTS = [name for name, e in RECURLY_ENDPOINTS.items() if not e.supports_list_params]


def _list_body(data: list[dict[str, Any]], has_more: bool = False, next_path: str | None = None) -> dict[str, Any]:
    return {"object": "list", "has_more": has_more, "next": next_path, "data": data}


def _resource(endpoint: str, **kwargs: Any) -> dict[str, Any]:
    # get_resource returns an EndpointResource TypedDict whose nested values are unions;
    # cast to a plain dict so the structural assertions below stay readable.
    return cast(dict[str, Any], get_resource(endpoint, **kwargs))


class TestRecurlyHelpers:
    @pytest.mark.parametrize(
        "next_path, expected",
        [
            ("/accounts?cursor=abc123&limit=200", "abc123"),
            ("/sites/subdomain-foo/accounts?sort=updated_at&cursor=zzz", "zzz"),
            ("/accounts?limit=200", None),
            ("", None),
            (None, None),
        ],
    )
    def test_extract_cursor(self, next_path, expected):
        assert _extract_cursor(next_path) == expected

    def test_format_datetime_date(self):
        assert _format_datetime(date(2024, 1, 2)) == "2024-01-02T00:00:00.000Z"

    def test_format_datetime_none(self):
        assert _format_datetime(None) is None

    def test_format_datetime_string_passthrough(self):
        assert _format_datetime("2024-01-02T00:00:00Z") == "2024-01-02T00:00:00Z"


class TestUsageAddOns:
    @pytest.mark.parametrize(
        "add_ons, expected_add_on_ids",
        [
            ([], []),
            (None, []),
            ([{"add_on": {"id": "u1", "add_on_type": "usage"}}], ["u1"]),
            ([{"add_on": {"id": "f1", "add_on_type": "fixed"}}], []),
            ([{"add_on": {"id": "u1"}}], []),
            ([{"add_on": {"add_on_type": "usage"}}], []),
            ([{"add_on": None}, {}], []),
            (
                [
                    {"add_on": {"id": "u1", "add_on_type": "usage"}},
                    {"add_on": {"id": "f1", "add_on_type": "fixed"}},
                    {"add_on": {"id": "u1", "add_on_type": "usage"}},
                    {"add_on": {"id": "u2", "add_on_type": "usage"}},
                ],
                ["u1", "u2"],
            ),
        ],
    )
    def test_explodes_subscription_into_usage_add_ons(
        self, add_ons: list[dict[str, Any]] | None, expected_add_on_ids: list[str]
    ) -> None:
        rows = _usage_add_ons({"id": "sub-1", "add_ons": add_ons})

        assert rows == [{"subscription_id": "sub-1", "add_on_id": add_on_id} for add_on_id in expected_add_on_ids]


class TestRecurlyPaginator:
    def test_update_state_has_more_but_missing_cursor_terminates(self):
        paginator = RecurlyPaginator()
        response = MagicMock()
        response.json.return_value = _list_body([{"id": "a1"}], has_more=True, next_path="/accounts?limit=200")
        paginator.update_state(response)
        assert paginator._next_cursor is None
        assert paginator.has_next_page is False

    def test_update_state_invalid_json_terminates(self):
        paginator = RecurlyPaginator()
        response = MagicMock()
        response.json.side_effect = ValueError("no json")
        paginator.update_state(response)
        assert paginator.has_next_page is False

    def test_get_resume_state_returns_none_on_terminal_page(self):
        paginator = RecurlyPaginator()
        response = MagicMock()
        response.json.return_value = _list_body([], has_more=False)
        paginator.update_state(response)
        assert paginator.get_resume_state() is None


class TestGetResource:
    @pytest.mark.parametrize("endpoint", INCREMENTAL_ENDPOINTS)
    def test_incremental_resource_uses_merge_and_begin_time(self, endpoint):
        resource = _resource(
            endpoint,
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        params = resource["endpoint"]["params"]
        assert params["sort"] == "updated_at"
        assert params["order"] == "asc"
        assert params["begin_time"] == "2024-01-01T00:00:00.000Z"

    @pytest.mark.parametrize("endpoint", NO_LIST_PARAMS_ENDPOINTS)
    @pytest.mark.parametrize("should_use_incremental_field", [True, False])
    def test_endpoint_without_list_params_sends_no_query_params(
        self, endpoint: str, should_use_incremental_field: bool
    ) -> None:
        # gift_cards' list endpoint 400s on any query parameter at all (confirmed against
        # the v2021-02-25 OpenAPI spec, which declares none for it), so limit/sort/order
        # must never be sent even when the pipeline asks for incremental.
        resource = _resource(
            endpoint,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert resource["endpoint"]["params"] == {}
        assert resource["write_disposition"] == "replace"


class TestRecurlySourceResumeBehavior:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(RecurlySource(), RecurlySourceConfig(api_key="test-key", region="us"))

    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self):
        result = self._driver().run(
            "accounts",
            [
                ScriptedResponse(json=_list_body([{"id": "a1"}], has_more=True, next_path="/accounts?cursor=cur-1")),
                ScriptedResponse(json=_list_body([{"id": "a2"}], has_more=True, next_path="/accounts?cursor=cur-2")),
                ScriptedResponse(json=_list_body([{"id": "a3"}], has_more=False)),
            ],
        )

        assert result.params("cursor") == [None, "cur-1", "cur-2"]
        assert result.saved_states == [
            RecurlyResumeConfig(next_cursor="cur-1"),
            RecurlyResumeConfig(next_cursor="cur-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self):
        result = self._driver().run(
            "accounts",
            [ScriptedResponse(json=_list_body([{"id": "a4"}], has_more=False))],
            resume_state=RecurlyResumeConfig(next_cursor="cur-resumed"),
        )

        assert result.params("cursor") == ["cur-resumed"]

    def test_does_not_resume_when_there_is_no_saved_state(self):
        result = self._driver().run("accounts", [ScriptedResponse(json=_list_body([{"id": "a"}], has_more=False))])

        assert result.params("cursor") == [None]


class TestRecurlyFanOut:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(RecurlySource(), RecurlySourceConfig(api_key="test-key", region="us"))

    def test_coupon_redemptions_walk_every_account_and_tag_rows(self) -> None:
        result = self._driver().run(
            "coupon_redemptions",
            route(
                {
                    "/accounts": [
                        ScriptedResponse(
                            json=_list_body(
                                [{"id": "a1"}, {"id": "a2"}], has_more=True, next_path="/accounts?cursor=p2"
                            )
                        ),
                        ScriptedResponse(json=_list_body([{"id": "a3"}])),
                    ],
                    "/accounts/a1/coupon_redemptions": [
                        ScriptedResponse(
                            json=_list_body(
                                [{"id": "r1"}], has_more=True, next_path="/accounts/a1/coupon_redemptions?cursor=c2"
                            )
                        ),
                        ScriptedResponse(json=_list_body([{"id": "r2"}])),
                    ],
                    # An account closed between the listing and its child fetch.
                    "/accounts/a2/coupon_redemptions": [ScriptedResponse(status=404, json={"error": {}})],
                    "/accounts/a3/coupon_redemptions": [ScriptedResponse(json=_list_body([{"id": "r3"}]))],
                }
            ),
        )

        assert result.raised is None
        assert [(row["account_id"], row["id"]) for row in result.rows] == [("a1", "r1"), ("a1", "r2"), ("a3", "r3")]
        assert all("_accounts_id" not in row for row in result.rows)
        assert result.response is not None
        assert result.response.primary_keys == ["account_id", "id"]
        child_queries = [request.query for request in result.requests if request.path.endswith("/coupon_redemptions")]
        # The spec declares no `limit` or `order` here, so only the pagination cursor may be sent.
        assert child_queries == [{}, {"cursor": ("c2",)}, {}, {}]

    def test_usage_requests_only_usage_add_ons_and_tags_rows(self) -> None:
        subscriptions: list[dict[str, Any]] = [
            {
                "id": "s1",
                "add_ons": [
                    {"add_on": {"id": "u1", "add_on_type": "usage"}},
                    {"add_on": {"id": "f1", "add_on_type": "fixed"}},
                ],
            },
            {"id": "s2", "add_ons": []},
            {"id": "s3", "add_ons": [{"add_on": {"id": "u2", "add_on_type": "usage"}}]},
        ]
        result = self._driver().run(
            "usage",
            route(
                {
                    "/subscriptions": [ScriptedResponse(json=_list_body(subscriptions))],
                    "/subscriptions/s1/add_ons/u1/usage": [
                        ScriptedResponse(
                            json=_list_body(
                                [{"id": "x1"}], has_more=True, next_path="/subscriptions/s1/add_ons/u1/usage?cursor=c2"
                            )
                        ),
                        ScriptedResponse(json=_list_body([{"id": "x2"}])),
                    ],
                    "/subscriptions/s3/add_ons/u2/usage": [ScriptedResponse(json=_list_body([{"id": "x3"}]))],
                }
            ),
        )

        assert result.raised is None
        assert [(row["subscription_id"], row["add_on_id"], row["id"]) for row in result.rows] == [
            ("s1", "u1", "x1"),
            ("s1", "u1", "x2"),
            ("s3", "u2", "x3"),
        ]
        usage_requests = [request for request in result.requests if request.path.endswith("/usage")]
        assert [request.path for request in usage_requests] == [
            "/subscriptions/s1/add_ons/u1/usage",
            "/subscriptions/s1/add_ons/u1/usage",
            "/subscriptions/s3/add_ons/u2/usage",
        ]
        assert {(r.param("sort"), r.param("order"), r.param("limit")) for r in usage_requests} == {
            ("recorded_timestamp", "asc", "200")
        }

    def test_resume_skips_completed_parents_and_continues_the_current_one(self) -> None:
        result = self._driver().run(
            "coupon_redemptions",
            route(
                {
                    "/accounts": [ScriptedResponse(json=_list_body([{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]))],
                    "/accounts/a2/coupon_redemptions": [ScriptedResponse(json=_list_body([{"id": "r2"}]))],
                    "/accounts/a3/coupon_redemptions": [ScriptedResponse(json=_list_body([{"id": "r3"}]))],
                }
            ),
            resume_state=RecurlyResumeConfig(
                fanout_state={
                    "completed": ["/accounts/a1/coupon_redemptions"],
                    "current": "/accounts/a2/coupon_redemptions",
                    "child_state": {"next_cursor": "c-resumed"},
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["r2", "r3"]
        child_requests = [r for r in result.requests if r.path.endswith("/coupon_redemptions")]
        assert [(r.path, r.param("cursor")) for r in child_requests] == [
            ("/accounts/a2/coupon_redemptions", "c-resumed"),
            ("/accounts/a3/coupon_redemptions", None),
        ]
        assert all(state.next_cursor == "" and state.fanout_state for state in result.saved_states)
