import json
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.inngest import (
    InngestSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest import inngest
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.inngest import (
    EVENTS_PAGE_SIZE,
    InngestResumeConfig,
    _event_window,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.settings import INNGEST_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.source import InngestSource


def _event(internal_id: str, received_at: str = "2026-07-10T10:00:00.000Z", **extra: Any) -> dict[str, Any]:
    return {"internal_id": internal_id, "receivedAt": received_at, "name": "app/user.signed.up", **extra}


def _driver() -> SourceDriver:
    return SourceDriver(InngestSource(), InngestSourceConfig(signing_key="signkey-prod-test"))


class TestEventWindow:
    @parameterized.expand(
        [
            ("iso_string", "2026-07-10T08:30:00+00:00", "2026-07-10T08:30:00.000Z"),
            ("iso_string_z", "2026-07-10T08:30:00.500Z", "2026-07-10T08:30:00.500Z"),
        ]
    )
    @time_machine.travel("2026-07-14T12:00:00Z", tick=False)
    def test_incremental_run_advances_from_the_watermark(self, _name: str, value: Any, expected_after: str) -> None:
        window = _event_window(should_use_incremental_field=True, db_incremental_field_last_value=value)
        assert window.start == expected_after

    @time_machine.travel("2026-07-14T12:00:00Z", tick=False)
    def test_future_watermark_is_clamped_to_now(self) -> None:
        # A future-dated watermark would produce an inverted window that returns nothing forever.
        window = _event_window(
            should_use_incremental_field=True, db_incremental_field_last_value="2027-01-01T00:00:00Z"
        )
        assert window.start == window.end == "2026-07-14T12:00:00.000Z"


class TestEventsPagination:
    @parameterized.expand(
        [
            ("empty_first_page", [[]], 0),
            ("partial_page_stops", [[_event("01A000")]], 1),
        ]
    )
    def test_pagination_terminates(self, _name: str, pages: list[list[dict]], expected_rows: int) -> None:
        result = _driver().run("events", [ScriptedResponse(json={"data": pages[0]})])
        assert result.raised is None
        assert len(result.rows) == expected_rows
        assert len(result.requests) == 1

    def test_resume_continues_the_saved_walk(self) -> None:
        # A resumed attempt must reuse the saved cursor and pinned window, not re-derive a new
        # window from the clock (which would re-fetch everything already yielded).
        state = InngestResumeConfig(
            cursor="01A099",
            received_after="2026-07-01T00:00:00.000Z",
            received_before="2026-07-14T00:00:00.000Z",
        )
        result = _driver().run("events", [ScriptedResponse(json={"data": [_event("01B000")]})], resume_state=state)
        assert result.raised is None
        assert result.requests[0].param("cursor") == "01A099"
        assert result.requests[0].param("received_after") == "2026-07-01T00:00:00.000Z"
        assert result.requests[0].param("received_before") == "2026-07-14T00:00:00.000Z"

    def test_cursor_event_returned_again_is_dropped(self) -> None:
        # We couldn't verify whether the API's cursor is inclusive; re-yielding the cursor event
        # would duplicate it in append mode, so it must be filtered out.
        pages = [
            [_event(f"01A{i:03d}") for i in range(EVENTS_PAGE_SIZE)],
            [_event("01A099"), _event("01B000")],
        ]
        result = _driver().run("events", [ScriptedResponse(json={"data": page}) for page in pages])
        assert result.raised is None
        assert [row["internal_id"] for row in result.rows].count("01A099") == 1
        assert result.requests[1].param("cursor") == "01A099"

    @parameterized.expand(
        [
            ("camel_case", {"internal_id": "01A000", "receivedAt": "2026-07-10T10:00:00.000Z"}),
            ("snake_case", {"internal_id": "01A000", "received_at": "2026-07-10T10:00:00.000Z"}),
        ]
    )
    def test_received_at_is_normalized_from_either_spelling(self, _name: str, item: dict) -> None:
        # The v1 spec documents `receivedAt` amid snake_case fields and the live casing is
        # unverified; the incremental/partition column must exist under one stable name either way.
        result = _driver().run("events", [ScriptedResponse(json={"data": [item]})])
        assert result.raised is None
        assert result.rows[0]["received_at"] == "2026-07-10T10:00:00.000Z"
        assert "receivedAt" not in result.rows[0]


class TestFunctionRunsFanOut:
    def test_fetches_runs_per_event_and_injects_event_received_at(self) -> None:
        result = _driver().run(
            "function_runs",
            route(
                {
                    "/v1/events": [ScriptedResponse(json={"data": [_event("01A000"), _event("01A001")]})],
                    "/v1/events/01A000/runs": [
                        ScriptedResponse(
                            json={"data": [{"run_id": "r1", "status": "Completed", "output": {"ok": True}}]}
                        )
                    ],
                    "/v1/events/01A001/runs": [ScriptedResponse(json={"data": []})],
                }
            ),
        )
        assert result.raised is None
        assert len(result.rows) == 1
        # The parent event's received time drives the incremental watermark; a run's own
        # timestamps can lag behind (debounce) and would advance the watermark past unseen events.
        assert result.rows[0]["event_received_at"] == "2026-07-10T10:00:00.000Z"
        # Non-string outputs are JSON-encoded so the column keeps one stable type across rows.
        assert result.rows[0]["output"] == json.dumps({"ok": True})

    def test_batch_run_returned_for_every_event_is_deduped(self) -> None:
        # A batch run appears under every event in its batch; duplicate run_id rows within one
        # sync seed the Delta table with dupes that every later merge multi-matches.
        result = _driver().run(
            "function_runs",
            route(
                {
                    "/v1/events": [ScriptedResponse(json={"data": [_event("01A000"), _event("01A001")]})],
                    "/runs": [
                        ScriptedResponse(json={"data": [{"run_id": "r-batch", "status": "Completed", "output": None}]}),
                        ScriptedResponse(json={"data": [{"run_id": "r-batch", "status": "Completed", "output": None}]}),
                    ],
                }
            ),
        )
        assert result.raised is None
        assert [row["run_id"] for row in result.rows] == ["r-batch"]


class TestV2ListPagination:
    @parameterized.expand([("event_keys",), ("signing_keys",)])
    def test_secret_key_material_is_never_synced(self, endpoint: str) -> None:
        # The v2 key inventories return the raw `key` secret; syncing it would copy live
        # credentials into the warehouse.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(
                    json={
                        "data": [{"id": "k1", "name": "prod key", "key": "signkey-prod-secretvalue"}],
                        "page": {"hasMore": False},
                    }
                )
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "k1", "name": "prod key"}]


class TestV2Runs:
    @time_machine.travel("2026-07-14T12:00:00Z", tick=False)
    def test_pages_a_pinned_ascending_queued_at_window_and_stages_the_next_cursor(self) -> None:
        pages = [
            {"data": [{"id": "r1", "output": {"ok": True}}], "page": {"cursor": "c2", "hasMore": True}},
            {"data": [{"id": "r2", "output": "done"}], "page": {"cursor": "c3", "hasMore": False}},
        ]
        result = _driver().run(
            "runs",
            [ScriptedResponse(json=page) for page in pages],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-10T08:30:00Z",
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["r1", "r2"]
        assert result.rows[0]["output"] == json.dumps({"ok": True})
        assert result.rows[1]["output"] == "done"
        assert result.paths == ["/v2/runs", "/v2/runs"]
        for request in result.requests:
            # The incremental watermark is a queuedAt value, so the server window and the order
            # must use queuedAt too; any other field skips or re-reads runs.
            assert request.param("from") == "2026-07-10T08:30:00.000Z"
            assert request.param("until") == "2026-07-14T12:00:00.000Z"
            assert request.param("timeField") == "queuedAt"
            assert request.param("order") == "ASC"
        assert result.requests[0].param("cursor") is None
        assert result.requests[1].param("cursor") == "c2"
        assert [(state.cursor, state.received_after, state.received_before) for state in result.saved_states] == [
            ("c2", "2026-07-10T08:30:00.000Z", "2026-07-14T12:00:00.000Z")
        ]

    def test_resume_continues_the_saved_cursor_and_window(self) -> None:
        state = InngestResumeConfig(
            cursor="c2", received_after="2026-07-01T00:00:00.000Z", received_before="2026-07-14T00:00:00.000Z"
        )
        result = _driver().run(
            "runs", [ScriptedResponse(json={"data": [{"id": "r2"}], "page": {"hasMore": False}})], resume_state=state
        )
        assert result.raised is None
        assert result.requests[0].param("cursor") == "c2"
        assert result.requests[0].param("from") == "2026-07-01T00:00:00.000Z"
        assert result.requests[0].param("until") == "2026-07-14T00:00:00.000Z"


class TestV2FanOut:
    def test_functions_are_listed_per_app_with_the_parent_app_id(self) -> None:
        # `app_id` is part of the primary key; dropping it would collide functions across apps.
        result = _driver().run(
            "functions",
            [
                ScriptedResponse(json={"data": [{"id": "billing"}, {"id": "my app/v2"}], "page": {"hasMore": False}}),
                ScriptedResponse(
                    json={
                        "data": [{"id": "fn-https://api.inngest.com/v2/apps/billing/functions"}],
                        "page": {"hasMore": False},
                    }
                ),
                ScriptedResponse(
                    json={
                        "data": [{"id": "fn-https://api.inngest.com/v2/apps/my%20app%2Fv2/functions"}],
                        "page": {"hasMore": False},
                    }
                ),
            ],
        )
        assert result.raised is None
        assert [(row["app_id"], row["id"]) for row in result.rows] == [
            ("billing", "fn-https://api.inngest.com/v2/apps/billing/functions"),
            # User-defined app IDs are encoded so they can't change the request path.
            ("my app/v2", "fn-https://api.inngest.com/v2/apps/my%20app%2Fv2/functions"),
        ]
        assert result.paths == [
            "/v2/apps",
            "/v2/apps/billing/functions",
            "/v2/apps/my%20app%2Fv2/functions",
        ]

    @time_machine.travel("2026-07-14T12:00:00Z", tick=False)
    def test_session_runs_walk_keys_then_sessions_and_carry_both_parents(self) -> None:
        result = _driver().run(
            "session_runs",
            [
                ScriptedResponse(json={"data": [{"id": "userId"}], "page": {"hasMore": False}}),
                ScriptedResponse(json={"data": [{"id": "u-1"}, {"id": "u-2"}], "page": {"hasMore": False}}),
                ScriptedResponse(json={"data": [{"id": "run-u-1"}], "page": {"hasMore": False}}),
                ScriptedResponse(json={"data": [{"id": "run-u-2"}], "page": {"hasMore": False}}),
            ],
        )
        assert result.raised is None
        assert result.rows == [
            {"id": "run-u-1", "session_key": "userId", "session_id": "u-1"},
            {"id": "run-u-2", "session_key": "userId", "session_id": "u-2"},
        ]
        # The session lists' default time range is undocumented, so the backfill window is always sent.
        for request in result.requests[1:]:
            assert request.param("from") == "2026-04-15T12:00:00.000Z", request.url
            assert request.param("until") == "2026-07-14T12:00:00.000Z", request.url


class TestV1Lists:
    @parameterized.expand(
        [
            ("list_payload", {"data": [{"id": "c1"}, {"id": "c2"}]}, ["c1", "c2"]),
            # The v1 spec is ambiguous about single-object vs array envelopes for these lists.
            ("single_object_payload", {"data": {"id": "c1"}}, ["c1"]),
            ("empty", {"data": []}, []),
        ]
    )
    def test_cancellations_handle_list_and_object_envelopes(
        self, _name: str, payload: dict, expected_ids: list[str]
    ) -> None:
        result = _driver().run("cancellations", [ScriptedResponse(json=payload)])
        assert result.raised is None
        assert [row["id"] for row in result.rows] == expected_ids

    def test_webhook_intake_url_is_never_synced(self) -> None:
        # The intake URL is capability-bearing: anyone holding it can submit events that trigger
        # Inngest functions, so it must not be copied into a warehouse table viewers can read.
        result = _driver().run(
            "webhooks",
            [
                ScriptedResponse(
                    json={
                        "data": [{"id": "wh1", "name": "github intake", "url": "https://inn.gs/e/secret-intake-token"}]
                    }
                )
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "wh1", "name": "github intake"}]


class TestVersionDispatch:
    @parameterized.expand(
        [
            # Cancellations and the webhooks inventory only exist in v1 and the envs inventory only
            # in v2, so a pin on the other version must not relocate them off their only compatible
            # home (a 404 otherwise).
            ("cancellations", "v2", "/v1/cancellations"),
            ("environments", "v1", "/v2/envs"),
            ("webhooks", "v2", "/v1/webhooks"),
            ("webhooks", "v1", "/v1/webhooks"),
        ]
    )
    def test_version_locked_endpoint_ignores_the_pin(self, endpoint: str, api_version: str, expected_path: str) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"data": [{"id": "x1"}], "page": {"hasMore": False}})],
            api_version=api_version,
        )
        assert result.raised is None
        assert result.urls[0] == f"https://api.inngest.com{expected_path}"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("signkey-prod-test") is expected
        assert network.requests_log[0].path == "/v1/events"
        assert network.requests_log[0].param("limit") == "1"

    def test_environment_header_is_sent_when_configured(self) -> None:
        # A branch environment's data is only reachable with the X-Inngest-Env header; dropping it
        # would validate (and later sync) the production environment instead.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("signkey-branch-test", "my-branch")
        assert network.requests_log[0].headers["x-inngest-env"] == "my-branch"

    def test_network_error_is_not_valid(self) -> None:
        with scripted_network([ConnectionResetError("boom")]):
            assert validate_credentials("signkey-prod-test") is False


class TestFetchRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_are_retried(self, _name: str, status: int) -> None:
        bad = MagicMock(status_code=status)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"ok": True}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(inngest._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = inngest._fetch(session, "https://api.inngest.com/v1/events", {}, MagicMock())

        assert result == {"ok": True}
        assert session.get.call_count == 2

    def test_client_error_raises_without_retry(self) -> None:
        import requests

        bad = requests.Response()
        bad.status_code = 401
        session = MagicMock()
        session.get.return_value = bad

        with pytest.raises(requests.HTTPError):
            inngest._fetch(session, "https://api.inngest.com/v1/events", {}, MagicMock())
        assert session.get.call_count == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            # The event-walk endpoints must report "desc" so the watermark is persisted only at
            # successful job end — the walk's arrival order within the window is unverified.
            ("events", "desc", "received_at"),
            ("function_runs", "desc", "run_started_at"),
            ("runs", "asc", "queuedAt"),
            ("session_runs", "asc", "queuedAt"),
            ("cancellations", "asc", None),
            ("environments", "asc", None),
            ("webhooks", "asc", None),
            ("event_keys", "asc", None),
            ("signing_keys", "asc", None),
        ]
    )
    def test_sort_mode_partition_and_primary_keys(
        self, endpoint: str, expected_sort: str, partition_key: str | None
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={"data": [], "page": {"hasMore": False}})])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.sort_mode == expected_sort
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.primary_keys == INNGEST_ENDPOINTS[endpoint].primary_keys
