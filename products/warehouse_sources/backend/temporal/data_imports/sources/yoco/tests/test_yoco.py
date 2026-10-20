from datetime import UTC, datetime
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import Mock

from parameterized import parameterized
from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yoco import YocoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.yoco.settings import (
    DEFAULT_PAGE_SIZE,
    MAX_FILTER_WINDOW,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.yoco.source import YocoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.yoco.yoco import (
    YocoCursorPaginator,
    YocoResumeConfig,
    _client_config,
    get_endpoint_permissions,
    get_resource,
    validate_credentials,
)


def _page(next_cursor: Any) -> Mock:
    response = Mock()
    response.json.return_value = {"data": [], "next_cursor": next_cursor}
    return response


class TestYocoPaginator:
    def test_cursor_pages_resend_window_bounds(self) -> None:
        # Yoco echoes filters rather than encoding them in the cursor, so a page that drops the
        # window bounds would walk the merchant's entire history on every incremental sync.
        paginator = YocoCursorPaginator(
            limit=DEFAULT_PAGE_SIZE,
            date_field="updated_at",
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 20, tzinfo=UTC),
        )
        request = Request()
        paginator.init_request(request)
        assert request.params == {
            "limit": DEFAULT_PAGE_SIZE,
            "updated_at__gte": "2026-01-01T00:00:00Z",
            "updated_at__lte": "2026-01-20T00:00:00Z",
        }

        paginator.update_state(_page("cursor-2"))
        paginator.update_request(request)
        assert paginator.has_next_page is True
        assert request.params == {
            "limit": DEFAULT_PAGE_SIZE,
            "cursor": "cursor-2",
            "updated_at__gte": "2026-01-01T00:00:00Z",
            "updated_at__lte": "2026-01-20T00:00:00Z",
        }

    @parameterized.expand(
        [
            ("null_cursor", {"data": [], "next_cursor": None}, False),
            ("missing_cursor", {"data": []}, False),
            ("empty_cursor", {"data": [], "next_cursor": ""}, False),
            ("populated_cursor", {"data": [], "next_cursor": "abc"}, True),
        ]
    )
    def test_termination_on_next_cursor(self, _name: str, body: dict, expected: bool) -> None:
        paginator = YocoCursorPaginator(limit=DEFAULT_PAGE_SIZE)
        response = Mock()
        response.json.return_value = body
        paginator.update_state(response)
        assert paginator.has_next_page is expected

    def test_resume_state_round_trip_restores_cursor_and_window(self) -> None:
        paginator = YocoCursorPaginator(
            limit=DEFAULT_PAGE_SIZE,
            date_field="updated_at",
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 6, 1, tzinfo=UTC),
        )
        paginator.update_state(_page("cursor-9"))
        state = paginator.get_resume_state()
        assert state == {
            "cursor": "cursor-9",
            "window_start": "2026-01-01T00:00:00Z",
            "window_end": "2026-02-01T00:00:00Z",
        }

        resumed = YocoCursorPaginator(
            limit=DEFAULT_PAGE_SIZE,
            date_field="updated_at",
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 6, 1, tzinfo=UTC),
        )
        resumed.set_resume_state(cast(dict[str, Any], state))
        request = Request()
        resumed.init_request(request)
        assert request.params["cursor"] == "cursor-9"
        assert request.params["updated_at__gte"] == "2026-01-01T00:00:00Z"
        # Resuming must keep walking the remaining windows, not stop at the resumed one.
        resumed.update_state(_page(None))
        assert resumed.has_next_page is True

    def test_no_resume_state_once_exhausted(self) -> None:
        paginator = YocoCursorPaginator(limit=DEFAULT_PAGE_SIZE)
        paginator.update_state(_page(None))
        assert paginator.get_resume_state() is None


class TestYocoResources:
    def test_window_never_exceeds_the_api_maximum(self) -> None:
        with time_machine.travel("2026-05-01T00:00:00Z", tick=False):
            resource = cast(
                dict[str, Any],
                get_resource(
                    "payments",
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2020, 1, 1, tzinfo=UTC),
                ),
            )
        request = Request()
        resource["endpoint"]["paginator"].init_request(request)
        start = datetime.fromisoformat(request.params["updated_at__gte"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(request.params["updated_at__lte"].replace("Z", "+00:00"))
        assert end - start == MAX_FILTER_WINDOW

    @parameterized.expand(
        [
            ("user_choice_honoured", "payments", "created_at", "created_at__gte"),
            ("unadvertised_field_falls_back", "payments", "closed_at", "updated_at__gte"),
            ("endpoint_without_updated_at", "modifier_groups", None, "created_at__gte"),
        ]
    )
    @time_machine.travel("2026-05-01T00:00:00Z", tick=False)
    def test_incremental_field_selection(
        self, _name: str, endpoint: str, incremental_field: str | None, expected_param: str
    ) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(
                endpoint,
                should_use_incremental_field=True,
                incremental_field=incremental_field,
                db_incremental_field_last_value=datetime(2026, 4, 1, tzinfo=UTC),
            ),
        )
        request = Request()
        resource["endpoint"]["paginator"].init_request(request)
        assert expected_param in request.params

    def test_get_resource_rejects_fanout_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource("payout_entries", should_use_incremental_field=False)

    def test_client_config_pins_host_and_blocks_redirects(self) -> None:
        # A redirect off api.yoco.com would otherwise replay the bearer token to another host.
        config = _client_config("yoco-key", DEFAULT_PAGE_SIZE)
        assert config["allowed_hosts"] == []
        assert config["allow_redirects"] is False
        assert config["auth"] == {"type": "bearer", "token": "yoco-key"}


def _driver() -> SourceDriver:
    return SourceDriver(YocoSource(), YocoSourceConfig(api_key="key"))


class TestYocoSource:
    @parameterized.expand(
        [
            ("incremental_defers_watermark", True, "desc"),
            ("full_refresh", False, "asc"),
        ]
    )
    def test_sort_mode_and_partitioning(self, _name: str, should_use_incremental_field: bool, expected: str) -> None:
        response = _driver().run("payments", [], should_use_incremental_field=should_use_incremental_field).response

        assert response is not None
        # Yoco documents no page ordering, so the watermark must only be committed once the run
        # completes — "asc" would advance it past rows the run never fetched.
        assert response.sort_mode == expected
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    @time_machine.travel("2026-03-01T00:00:00Z", tick=False)
    def test_resume_state_seeds_the_paginator(self) -> None:
        result = _driver().run(
            "payments",
            [ScriptedResponse(json={"data": [], "next_cursor": None})],
            resume_state=YocoResumeConfig(
                cursor="cursor-4", window_start="2026-02-01T00:00:00Z", window_end="2026-03-01T00:00:00Z"
            ),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        request = result.requests[0]
        assert request.param("cursor") == "cursor-4"
        assert request.param("updated_at__gte") == "2026-02-01T00:00:00Z"
        assert request.param("updated_at__lte") == "2026-03-01T00:00:00Z"

    def test_resume_hook_saves_only_advancing_state(self) -> None:
        result = _driver().run(
            "payments",
            [
                ScriptedResponse(json={"data": [{"id": "p1"}], "next_cursor": "cursor-7"}),
                ScriptedResponse(json={"data": [{"id": "p2"}], "next_cursor": None}),
            ],
        )

        assert result.saved_states == [YocoResumeConfig(cursor="cursor-7")]

    def test_payout_entries_fanout_resume_round_trip(self) -> None:
        result = _driver().run(
            "payout_entries",
            route(
                {
                    "/v1/payouts/": [ScriptedResponse(json={"data": [{"id": "po_1"}, {"id": "po_2"}]})],
                    "/v1/payouts/po_2/payout_entries": [
                        ScriptedResponse(json={"data": [{"id": "e1"}], "next_cursor": None})
                    ],
                }
            ),
            resume_state=YocoResumeConfig(
                completed=["/v1/payouts/po_1/payout_entries"],
                current="/v1/payouts/po_2/payout_entries",
                child_state={"cursor": "cursor-2"},
            ),
        )

        assert result.raised is None
        assert result.paths == ["/v1/payouts/", "/v1/payouts/po_2/payout_entries"]
        assert result.requests[1].param("cursor") == "cursor-2"
        assert result.saved_states == [
            YocoResumeConfig(
                completed=["/v1/payouts/po_1/payout_entries", "/v1/payouts/po_2/payout_entries"],
            )
        ]


class TestYocoCredentials:
    @parameterized.expand(
        [
            # A key scoped only to the catalogue still authenticates — 403 must not block setup.
            (200, True, None),
            (403, True, None),
            (401, False, "rejected the API key"),
            (500, False, "unexpected status code"),
        ]
    )
    def test_validate_credentials_status_mapping(self, status: int, expected_valid: bool, fragment: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            is_valid, message = validate_credentials("yoco-key")

        assert is_valid is expected_valid
        if fragment is None:
            assert message is None
        else:
            assert message is not None and fragment in message

        request = network.requests_log[0]
        assert request.origin + request.path == "https://api.yoco.com/v1/payments/"
        assert request.headers["authorization"] == "Bearer yoco-key"
        assert network.session_options[0]["allow_redirects"] is False

    def test_endpoint_permissions_name_the_missing_scope(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            return ScriptedResponse(status=403 if "/v1/payouts/" in request.url else 200, json={})

        with scripted_network(respond) as network:
            permissions = get_endpoint_permissions("yoco-key", ["payments", "payouts", "payout_entries"])

        assert permissions["payments"] is None
        assert permissions["payouts"] is not None and "business/payouts:read" in permissions["payouts"]
        # Payout entries can only be reached through a payout id, so the parent answers for them.
        assert permissions["payout_entries"] is not None and "business/payouts:read" in permissions["payout_entries"]
        assert len(network.requests_log) == 2

    def test_endpoint_permissions_treat_transport_failures_as_reachable(self) -> None:
        # A throttle or network blip is not a missing scope — reporting one would push users to
        # deselect tables they can actually sync.
        with scripted_network(always(ConnectionError("connection reset"))):
            assert get_endpoint_permissions("yoco-key", ["payments"]) == {"payments": None}
