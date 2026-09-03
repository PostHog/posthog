from datetime import UTC, datetime
from typing import Any, cast

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized
from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.sources.yoco.settings import (
    DEFAULT_PAGE_SIZE,
    MAX_FILTER_WINDOW,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.yoco.yoco import (
    YocoCursorPaginator,
    YocoResumeConfig,
    _client_config,
    get_endpoint_permissions,
    get_resource,
    validate_credentials,
    yoco_source,
)


def _page(next_cursor: Any) -> Mock:
    response = Mock()
    response.json.return_value = {"data": [], "next_cursor": next_cursor}
    return response


class _FakeResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


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

    def test_window_advances_until_the_final_bound(self) -> None:
        # Yoco rejects a range wider than 31 days, so an older watermark must be walked in
        # windows; stopping after the first one would silently truncate the sync.
        paginator = YocoCursorPaginator(
            limit=DEFAULT_PAGE_SIZE,
            date_field="created_at",
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 4, 1, tzinfo=UTC),
        )
        request = Request()
        paginator.init_request(request)

        windows = [(request.params["created_at__gte"], request.params["created_at__lte"])]
        while True:
            paginator.update_state(_page(None))
            if not paginator.has_next_page:
                break
            paginator.update_request(request)
            windows.append((request.params["created_at__gte"], request.params["created_at__lte"]))

        assert windows == [
            ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"),
            ("2026-02-01T00:00:00Z", "2026-03-04T00:00:00Z"),
            ("2026-03-04T00:00:00Z", "2026-04-01T00:00:00Z"),
        ]
        # The cursor from the previous window must not leak into the next one.
        assert "cursor" not in request.params

    def test_no_window_is_plain_cursor_pagination(self) -> None:
        paginator = YocoCursorPaginator(limit=DEFAULT_PAGE_SIZE)
        request = Request()
        paginator.init_request(request)
        assert request.params == {"limit": DEFAULT_PAGE_SIZE}

        paginator.update_state(_page("cursor-2"))
        assert paginator.has_next_page is True
        paginator.update_state(_page(None))
        assert paginator.has_next_page is False

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
    @freeze_time("2026-05-01T00:00:00Z")
    def test_incremental_resource_windows_from_the_watermark(self) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(
                "payments",
                should_use_incremental_field=True,
                incremental_field="updated_at",
                db_incremental_field_last_value=datetime(2026, 4, 1, tzinfo=UTC),
            ),
        )
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        request = Request()
        resource["endpoint"]["paginator"].init_request(request)
        assert request.params["updated_at__gte"] == "2026-04-01T00:00:00Z"
        assert request.params["updated_at__lte"] == "2026-05-01T00:00:00Z"

    def test_window_never_exceeds_the_api_maximum(self) -> None:
        with freeze_time("2026-05-01T00:00:00Z"):
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

    def test_first_incremental_sync_sends_no_date_filter(self) -> None:
        # With no watermark there is nothing to window from; sending a bogus lower bound would
        # make the first sync walk years of 31-day windows instead of one cursor pass.
        resource = cast(
            dict[str, Any],
            get_resource("payments", should_use_incremental_field=True, db_incremental_field_last_value=None),
        )
        request = Request()
        resource["endpoint"]["paginator"].init_request(request)
        assert request.params == {"limit": DEFAULT_PAGE_SIZE}

    def test_full_refresh_resource_replaces_and_sends_no_date_filter(self) -> None:
        resource = cast(dict[str, Any], get_resource("payments", should_use_incremental_field=False))
        assert resource["write_disposition"] == "replace"
        request = Request()
        resource["endpoint"]["paginator"].init_request(request)
        assert request.params == {"limit": DEFAULT_PAGE_SIZE}

    @parameterized.expand(
        [
            ("user_choice_honoured", "payments", "created_at", "created_at__gte"),
            ("unadvertised_field_falls_back", "payments", "closed_at", "updated_at__gte"),
            ("endpoint_without_updated_at", "modifier_groups", None, "created_at__gte"),
        ]
    )
    @freeze_time("2026-05-01T00:00:00Z")
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

    def test_endpoint_without_incremental_fields_stays_full_refresh(self) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(
                "locations",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 4, 1, tzinfo=UTC),
            ),
        )
        assert resource["write_disposition"] == "replace"
        request = Request()
        resource["endpoint"]["paginator"].init_request(request)
        assert request.params == {"limit": DEFAULT_PAGE_SIZE}

    def test_get_resource_rejects_fanout_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource("payout_entries", should_use_incremental_field=False)

    def test_client_config_pins_host_and_blocks_redirects(self) -> None:
        # A redirect off api.yoco.com would otherwise replay the bearer token to another host.
        config = _client_config("yoco-key", DEFAULT_PAGE_SIZE)
        assert config["allowed_hosts"] == []
        assert config["allow_redirects"] is False
        assert config["auth"] == {"type": "bearer", "token": "yoco-key"}


class TestYocoSource:
    @parameterized.expand(
        [
            ("incremental_defers_watermark", True, "desc"),
            ("full_refresh", False, "asc"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.yoco.rest_api_resource")
    def test_sort_mode_and_partitioning(
        self, _name: str, should_use_incremental_field: bool, expected: str, _mock_resource: MagicMock
    ) -> None:
        response = yoco_source(
            api_key="key",
            endpoint="payments",
            team_id=1,
            job_id="job-1",
            should_use_incremental_field=should_use_incremental_field,
        )
        # Yoco documents no page ordering, so the watermark must only be committed once the run
        # completes — "asc" would advance it past rows the run never fetched.
        assert response.sort_mode == expected
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.yoco.rest_api_resource")
    def test_resume_state_seeds_the_paginator(self, mock_resource: MagicMock) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = YocoResumeConfig(
            cursor="cursor-4", window_start="2026-02-01T00:00:00Z", window_end="2026-03-01T00:00:00Z"
        )

        yoco_source(
            api_key="key",
            endpoint="payments",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert mock_resource.call_args.kwargs["initial_paginator_state"] == {
            "cursor": "cursor-4",
            "window_start": "2026-02-01T00:00:00Z",
            "window_end": "2026-03-01T00:00:00Z",
        }

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.yoco.rest_api_resource")
    def test_resume_hook_saves_only_advancing_state(self, mock_resource: MagicMock) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        yoco_source(api_key="key", endpoint="payments", team_id=1, job_id="job-1", resumable_source_manager=manager)
        resume_hook = mock_resource.call_args.kwargs["resume_hook"]

        resume_hook({"cursor": "cursor-7"})
        assert manager.save_state.call_args.args[0] == YocoResumeConfig(cursor="cursor-7")

        manager.save_state.reset_mock()
        resume_hook(None)
        resume_hook({})
        manager.save_state.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.yoco.build_dependent_resource")
    def test_payout_entries_fanout_wiring(self, mock_build: MagicMock) -> None:
        mock_build.return_value = iter([])

        response = yoco_source(api_key="key", endpoint="payout_entries", team_id=1, job_id="job-1")

        kwargs = mock_build.call_args.kwargs
        assert kwargs["child_endpoint"] == "payout_entries"
        assert kwargs["fanout"].parent_name == "payouts"
        assert kwargs["fanout"].resolve_param == "payout_id"
        # The cursor paginator already sends `limit`; a second size param would be undocumented.
        assert kwargs["page_size_param"] is None
        assert kwargs["should_use_incremental_field"] is False
        # `id` is only documented as unique within its payout, and this table aggregates entries
        # from every payout, so the parent id has to be part of the key.
        assert response.primary_keys == ["payout_id", "id"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_payout_entries_rows_carry_the_parent_id(self, mock_resources: MagicMock) -> None:
        mock_resources.return_value = [
            _FakeResource("payouts", [{"id": "po_1"}]),
            _FakeResource("payout_entries", [{"id": "pe_1", "payout_id": "po_1", "type": "payment"}]),
        ]

        response = yoco_source(api_key="key", endpoint="payout_entries", team_id=1, job_id="job-1")

        assert list(cast(Any, response.items())) == [{"id": "pe_1", "payout_id": "po_1", "type": "payment"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.yoco.build_dependent_resource")
    def test_payout_entries_fanout_resume_round_trip(self, mock_build: MagicMock) -> None:
        mock_build.return_value = iter([])
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = YocoResumeConfig(
            completed=["/v1/payouts/po_1/payout_entries"],
            current="/v1/payouts/po_2/payout_entries",
            child_state={"cursor": "cursor-2"},
        )

        yoco_source(
            api_key="key",
            endpoint="payout_entries",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        kwargs = mock_build.call_args.kwargs
        assert kwargs["initial_paginator_state"] == {
            "completed": ["/v1/payouts/po_1/payout_entries"],
            "current": "/v1/payouts/po_2/payout_entries",
            "child_state": {"cursor": "cursor-2"},
        }

        kwargs["resume_hook"]({"completed": ["a"], "current": "b", "child_state": {"cursor": "c"}})
        assert manager.save_state.call_args.args[0] == YocoResumeConfig(
            completed=["a"], current="b", child_state={"cursor": "c"}
        )


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
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.yoco.make_tracked_session")
    def test_validate_credentials_status_mapping(
        self, status: int, expected_valid: bool, fragment: str | None, mock_session: MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status)

        is_valid, message = validate_credentials("yoco-key")

        assert is_valid is expected_valid
        if fragment is None:
            assert message is None
        else:
            assert message is not None and fragment in message

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.yoco.com/v1/payments/"
        assert call.kwargs["headers"]["Authorization"] == "Bearer yoco-key"
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.yoco.make_tracked_session")
    def test_endpoint_permissions_name_the_missing_scope(self, mock_session: MagicMock) -> None:
        def _get(url: str, **_kwargs: Any) -> Mock:
            return Mock(status_code=403 if "/v1/payouts/" in url else 200)

        mock_session.return_value.get.side_effect = _get

        permissions = get_endpoint_permissions("yoco-key", ["payments", "payouts", "payout_entries"])

        assert permissions["payments"] is None
        assert permissions["payouts"] is not None and "business/payouts:read" in permissions["payouts"]
        # Payout entries can only be reached through a payout id, so the parent answers for them.
        assert permissions["payout_entries"] is not None and "business/payouts:read" in permissions["payout_entries"]
        assert mock_session.return_value.get.call_count == 2

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.yoco.make_tracked_session")
    def test_endpoint_permissions_treat_transport_failures_as_reachable(self, mock_session: MagicMock) -> None:
        # A throttle or network blip is not a missing scope — reporting one would push users to
        # deselect tables they can actually sync.
        mock_session.return_value.get.side_effect = Exception("connection reset")

        assert get_endpoint_permissions("yoco-key", ["payments"]) == {"payments": None}
