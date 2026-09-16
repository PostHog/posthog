import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from requests import PreparedRequest

from products.warehouse_sources.backend.temporal.data_imports.sources.campfire import campfire
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.campfire import (
    CampfireResumeConfig,
    CampfireTokenAuth,
    _format_incremental_value,
    _incremental_config,
    _validate_next_url,
    campfire_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.settings import (
    CAMPFIRE_BASE_URL,
    CAMPFIRE_ENDPOINTS,
    ENDPOINTS,
)

# campfire_source builds its (capture-off) tracked session in the campfire module and hands it
# to the RESTClient, so patch it there rather than in rest_client.
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.campfire.campfire.make_tracked_session"
)


def _response(body: Any, status: int = 200) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp.url = f"{CAMPFIRE_BASE_URL}/coa/api/vendor"
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume: CampfireResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    manager.saved = []
    manager.save_state.side_effect = lambda cfg: manager.saved.append(cfg)
    return manager


def _wire(session: MagicMock, responses: list[requests.Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT PREPARE TIME.

    ``request.params``/``request.url`` are mutated in place across pages, so inspecting them after
    the run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        prepared = MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(endpoint: str, responses: list[requests.Response], manager: MagicMock | None = None, **kwargs: Any) -> Any:
    manager = manager if manager is not None else _make_manager()
    with patch(SESSION_PATCH) as mock_session:
        session = MagicMock()
        snapshots = _wire(session, responses)
        mock_session.return_value = session
        source = campfire_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)
        rows = _rows(source)
    return rows, snapshots, session


class TestTokenAuth:
    def test_sets_token_authorization_header(self) -> None:
        request = PreparedRequest()
        request.prepare_headers({})
        CampfireTokenAuth("secret-key")(request)
        assert request.headers["Authorization"] == "Token secret-key"

    def test_secret_values_expose_the_key_for_redaction(self) -> None:
        assert CampfireTokenAuth("secret-key").secret_values() == ("secret-key",)
        assert CampfireTokenAuth("").secret_values() == ()


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
            ("date", date(2026, 1, 2), "2026-01-02"),
            ("string_passthrough", "2026-01-02T03:04:05Z", "2026-01-02T03:04:05Z"),
        ]
    )
    def test_formats(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestValidateNextUrl:
    def test_same_host_https_is_allowed(self) -> None:
        _validate_next_url(f"{CAMPFIRE_BASE_URL}/coa/api/vendor?offset=100")

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/coa/api/vendor?offset=100"),
            ("http_downgrade", "http://api.meetcampfire.com/coa/api/vendor?offset=100"),
        ]
    )
    def test_off_host_links_are_rejected(self, _name: str, url: str) -> None:
        # The API key rides in a header; following an off-host/downgraded next link would leak it.
        with pytest.raises(ValueError):
            _validate_next_url(url)


class TestFirstRequestParams:
    """The first request carries the page size, cursor opt-in, static params, and incremental filter."""

    def test_windowed_endpoints_request_all_time(self) -> None:
        # Without all_time=true these endpoints silently default to roughly the last six months.
        for endpoint in ("chart_transactions", "journal_entries"):
            _, snapshots, _ = _run(endpoint, [_response({"results": [], "next": None})])
            assert snapshots[0]["params"]["all_time"] == "true", endpoint

    def test_page_size_limit_is_sent(self) -> None:
        _, snapshots, _ = _run("vendors", [_response({"results": [], "next": None})])
        assert snapshots[0]["params"]["limit"] == CAMPFIRE_ENDPOINTS["vendors"].page_size

    def test_cursor_endpoints_send_empty_cursor(self) -> None:
        _, snapshots, _ = _run("bill_payments", [_response({"results": [], "next": None})])
        assert snapshots[0]["params"]["cursor"] == ""

    def test_offset_endpoints_do_not_send_cursor(self) -> None:
        _, snapshots, _ = _run("vendors", [_response({"results": [], "next": None})])
        assert "cursor" not in snapshots[0]["params"]

    def test_incremental_value_becomes_last_modified_filter(self) -> None:
        _, snapshots, _ = _run(
            "vendors",
            [_response({"results": [], "next": None})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        assert snapshots[0]["params"]["last_modified_at__gte"] == "2026-01-02T03:04:05Z"

    @parameterized.expand([("full_refresh", False, None), ("incremental_no_watermark", True, None)])
    def test_no_filter_without_watermark(self, _name: str, use_incremental: bool, last_value: Any) -> None:
        _, snapshots, _ = _run(
            "vendors",
            [_response({"results": [], "next": None})],
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value=last_value,
        )
        assert "last_modified_at__gte" not in snapshots[0]["params"]

    def test_full_refresh_only_endpoint_never_sends_filter(self) -> None:
        # journal_entries has no server-side last_modified filter; sending one anyway would be
        # silently ignored at best.
        _, snapshots, _ = _run(
            "journal_entries",
            [_response({"results": [], "next": None})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert "last_modified_at__gte" not in snapshots[0]["params"]


class TestPagination:
    def test_follows_next_links_and_saves_state_after_each_yield(self) -> None:
        page2 = f"{CAMPFIRE_BASE_URL}/coa/api/vendor?limit=500&offset=500"
        manager = _make_manager()
        rows, snapshots, session = _run(
            "vendors",
            [
                _response({"count": 3, "next": page2, "results": [{"id": 1}, {"id": 2}]}),
                _response({"count": 3, "next": None, "results": [{"id": 3}]}),
            ],
            manager=manager,
        )

        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert snapshots[1]["url"] == page2
        # State is saved only while more pages remain, so a crash re-yields (not skips) the last
        # page — merge dedupes on the primary key.
        assert [s.next_url for s in manager.saved] == [page2]

    def test_resumes_from_saved_next_url(self) -> None:
        page2 = f"{CAMPFIRE_BASE_URL}/coa/api/vendor?limit=500&offset=500"
        manager = _make_manager(CampfireResumeConfig(next_url=page2))
        rows, snapshots, session = _run(
            "vendors",
            [_response({"count": 3, "next": None, "results": [{"id": 3}]})],
            manager=manager,
        )

        assert rows == [{"id": 3}]
        assert session.send.call_count == 1
        assert snapshots[0]["url"] == page2

    def test_empty_first_page_yields_no_rows(self) -> None:
        rows, _, _ = _run("vendors", [_response({"count": 0, "next": None, "results": []})])
        assert rows == []

    def test_dict_without_results_yields_no_rows(self) -> None:
        # A DRF envelope missing `results` is tolerated (0 rows), not fail-loud.
        rows, _, _ = _run("vendors", [_response({"count": 0, "next": None})])
        assert rows == []

    def test_off_host_next_link_stops_the_sync(self) -> None:
        with pytest.raises(ValueError):
            _run(
                "vendors",
                [_response({"count": 1, "next": "https://evil.example.com/x", "results": [{"id": 1}]})],
            )


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @patch("tenacity.nap.time.sleep")
    def test_retryable_status_codes_are_retried(self, _name: str, status: int, _mock_sleep: MagicMock) -> None:
        rows, _, session = _run(
            "vendors",
            [_response({}, status=status), _response({"count": 0, "next": None, "results": []})],
        )
        assert rows == []
        assert session.send.call_count == 2

    @patch("tenacity.nap.time.sleep")
    def test_client_error_raises_without_retry(self, _mock_sleep: MagicMock) -> None:
        with pytest.raises(requests.HTTPError):
            _run("vendors", [_response({}, status=401)])


class TestCampfireSourceResponse:
    def test_every_endpoint_builds_a_source_response(self) -> None:
        # Catches a catalog entry whose wiring can't be built at all -- a fan-out naming a parent
        # that isn't in the catalog raises here rather than mid-sync.
        for endpoint in ENDPOINTS:
            response = campfire_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
            assert response.name == endpoint

    def test_fanout_rows_are_keyed_by_contract_and_id(self) -> None:
        # Subscription ids are only documented as unique within their contract, and the fan-out
        # pools every contract's rows into one table.
        response = campfire_source(
            "key", "contract_subscriptions", team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        assert response.primary_keys == ["contract", "id"]

    def test_payment_sync_endpoints_are_ascending(self) -> None:
        # Campfire documents (last_modified_at, id) ascending order on the payment sync endpoints,
        # which lets the pipeline checkpoint the watermark per batch.
        for endpoint in ("bill_payments", "invoice_payments"):
            response = campfire_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
            assert response.sort_mode == "asc"

    def test_undocumented_order_endpoints_are_descending(self) -> None:
        # Everything else has no documented response order, so the watermark must only be persisted
        # once the sync completes.
        for endpoint in ("chart_transactions", "vendors", "contracts"):
            response = campfire_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
            assert response.sort_mode == "desc"

    @parameterized.expand(
        [
            ("partitioned", "journal_entries", ["created_at"]),
            ("unpartitioned", "chart_of_accounts", None),
        ]
    )
    def test_partitioning(self, _name: str, endpoint: str, expected_keys: list[str] | None) -> None:
        response = campfire_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.partition_keys == expected_keys
        assert response.partition_mode == ("datetime" if expected_keys else None)


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status)
        with patch.object(campfire, "make_tracked_session", return_value=session):
            assert validate_credentials("cf_test_key") is expected

    def test_network_error_is_not_valid(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch.object(campfire, "make_tracked_session", return_value=session):
            assert validate_credentials("cf_test_key") is False

    def test_schema_probe_targets_the_given_path(self) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=200)
        with patch.object(campfire, "make_tracked_session", return_value=session):
            validate_credentials("cf_test_key", path="/rr/api/v1/contracts")
        assert session.get.call_args[0][0].startswith(f"{CAMPFIRE_BASE_URL}/rr/api/v1/contracts?")


class TestUnpaginatedEndpoints:
    """Some endpoints return a bare JSON array and document no pagination params."""

    def test_bare_array_rows_are_yielded(self) -> None:
        rows, _, session = _run("chart_entities", [_response([{"id": 1}, {"id": 2}])])
        assert rows == [{"id": 1}, {"id": 2}]
        # No `next` key to follow, so the sync stops after the single response.
        assert session.send.call_count == 1

    def test_no_page_size_is_requested(self) -> None:
        # `/coa/api/entity` documents no `limit`; sending one would be an undocumented param.
        _, snapshots, _ = _run("chart_entities", [_response([])])
        assert "limit" not in snapshots[0]["params"]


class TestIncrementalConfig:
    def test_binds_last_modified_at_to_the_server_side_filter(self) -> None:
        config = _incremental_config("last_modified_at")
        assert config is not None
        assert config["start_param"] == "last_modified_at__gte"
        assert config["cursor_path"] == "last_modified_at"

    def test_unknown_cursor_field_gets_no_request_window(self) -> None:
        # Campfire filters on `last_modified_at` and nothing else, so any other field must not
        # produce a param the API would ignore.
        assert _incremental_config("created_at") is None


class TestFanout:
    """`contract_subscriptions` is only reachable per contract, so it walks `contracts` first."""

    def _responses(self) -> list[requests.Response]:
        return [
            _response({"count": 2, "next": None, "results": [{"id": 11}, {"id": 22}]}),
            _response([{"id": 1, "contract": 11}]),
            _response([{"id": 2, "contract": 22}]),
        ]

    def test_fetches_each_contracts_subscriptions(self) -> None:
        rows, snapshots, _ = _run("contract_subscriptions", self._responses())

        assert rows == [{"id": 1, "contract": 11}, {"id": 2, "contract": 22}]
        assert snapshots[0]["url"] == f"{CAMPFIRE_BASE_URL}/rr/api/v1/contracts"
        assert [s["url"] for s in snapshots[1:]] == [
            f"{CAMPFIRE_BASE_URL}/rr/api/v1/contracts/11/subscriptions",
            f"{CAMPFIRE_BASE_URL}/rr/api/v1/contracts/22/subscriptions",
        ]

    def test_only_the_parent_listing_requests_a_page_size(self) -> None:
        # The child endpoint documents no `limit`; the parent needs one to page past its default.
        _, snapshots, _ = _run("contract_subscriptions", self._responses())
        assert snapshots[0]["params"]["limit"] == CAMPFIRE_ENDPOINTS["contracts"].page_size
        assert all("limit" not in s["params"] for s in snapshots[1:])

    def test_child_requests_carry_the_watermark(self) -> None:
        _, snapshots, _ = _run(
            "contract_subscriptions",
            self._responses(),
            should_use_incremental_field=True,
            incremental_field="last_modified_at",
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        assert [s["params"].get("last_modified_at__gte") for s in snapshots[1:]] == [
            "2026-01-02T03:04:05Z",
            "2026-01-02T03:04:05Z",
        ]
        # The parent walk is unfiltered: a subscription can change without its contract changing.
        assert "last_modified_at__gte" not in snapshots[0]["params"]

    def test_first_incremental_sync_sends_an_epoch_floor(self) -> None:
        # The framework sends the start param on every request, so with no stored watermark it
        # must still be a timestamp that selects everything.
        _, snapshots, _ = _run(
            "contract_subscriptions",
            self._responses(),
            should_use_incremental_field=True,
            incremental_field="last_modified_at",
            db_incremental_field_last_value=None,
        )
        assert snapshots[1]["params"]["last_modified_at__gte"] == "1970-01-01T00:00:00Z"

    def test_full_refresh_sends_no_watermark(self) -> None:
        _, snapshots, _ = _run("contract_subscriptions", self._responses())
        assert all("last_modified_at__gte" not in s["params"] for s in snapshots)

    def test_checkpoints_each_finished_contract(self) -> None:
        manager = _make_manager()
        _run("contract_subscriptions", self._responses(), manager=manager)
        assert [s.completed for s in manager.saved][-1] == [
            "/rr/api/v1/contracts/11/subscriptions",
            "/rr/api/v1/contracts/22/subscriptions",
        ]

    def test_resumes_past_contracts_already_synced(self) -> None:
        manager = _make_manager(
            CampfireResumeConfig(completed=["/rr/api/v1/contracts/11/subscriptions"], current=None, child_state=None)
        )
        rows, snapshots, _ = _run(
            "contract_subscriptions",
            [
                _response({"count": 2, "next": None, "results": [{"id": 11}, {"id": 22}]}),
                _response([{"id": 2, "contract": 22}]),
            ],
            manager=manager,
        )

        assert rows == [{"id": 2, "contract": 22}]
        assert [s["url"] for s in snapshots[1:]] == [f"{CAMPFIRE_BASE_URL}/rr/api/v1/contracts/22/subscriptions"]
