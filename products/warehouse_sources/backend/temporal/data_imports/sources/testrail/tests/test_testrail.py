from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qsl

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.testrail import testrail
from products.warehouse_sources.backend.temporal.data_imports.sources.testrail.settings import (
    ENDPOINTS,
    PAGE_SIZE,
    TESTRAIL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.testrail.testrail import (
    TestrailResumeConfig,
    TestrailRetryableError,
    _build_url,
    _extract_items,
    _to_epoch,
    check_access,
    get_rows,
    normalize_subdomain,
    testrail_source as make_testrail_source,  # aliased so pytest doesn't collect it as a test
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_unwrapped = testrail._fetch.__wrapped__  # type: ignore[attr-defined]

BASE_URL = "https://acme.testrail.io/index.php?"


class _FakeResumableManager:
    def __init__(self, state: TestrailResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TestrailResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TestrailResumeConfig | None:
        return self._state

    def save_state(self, data: TestrailResumeConfig) -> None:
        self.saved.append(data)


def _parse_api_url(url: str) -> tuple[str, Optional[int], dict[str, str]]:
    """Split a TestRail URL into (method, path_id, params) for request assertions."""
    query = url.split("index.php?", 1)[1]
    path, _, param_string = query.partition("&")
    segments = path.removeprefix("/api/v2/").split("/")
    method = segments[0]
    path_id = int(segments[1]) if len(segments) > 1 else None
    return method, path_id, dict(parse_qsl(param_string))


def _bulk(key: str, items: list[dict], has_more: bool = False) -> dict:
    return {
        "offset": 0,
        "limit": PAGE_SIZE,
        "size": len(items),
        "_links": {"next": f"/api/v2/next&offset={PAGE_SIZE}" if has_more else None, "prev": None},
        key: items,
    }


class _FakeApi:
    """Routes _fetch calls to canned responses keyed on (method, path_id); records every request."""

    def __init__(self, responses: dict[tuple[str, Optional[int]], Any]) -> None:
        self._responses = responses
        self.requests: list[tuple[str, Optional[int], dict[str, str]]] = []

    def __call__(self, session: Any, url: str, logger: Any) -> Any:
        method, path_id, params = _parse_api_url(url)
        self.requests.append((method, path_id, params))
        response = self._responses[(method, path_id)]
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(params)
        return response

    def params_for(self, method: str) -> list[dict[str, str]]:
        return [params for m, _, params in self.requests if m == method]


def _http_error(status: int) -> requests.HTTPError:
    response = MagicMock()
    response.status_code = status
    return requests.HTTPError(f"{status} error", response=response)


def _collect(
    api: _FakeApi,
    endpoint: str,
    monkeypatch: Any,
    manager: _FakeResumableManager | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[dict]:
    monkeypatch.setattr(testrail, "_fetch", api)
    monkeypatch.setattr(testrail, "_make_session", lambda username, api_key: MagicMock())
    rows: list[dict] = []
    for batch in get_rows(
        subdomain="acme",
        username="qa@acme.com",
        api_key="secret",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager or _FakeResumableManager(),  # type: ignore[arg-type]
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    ):
        rows.extend(batch)
    return rows


class TestUrlBuilding:
    def test_params_are_appended_with_ampersand_not_second_question_mark(self) -> None:
        # TestRail's whole API path lives inside the query string; a second `?` would break routing.
        url = _build_url(BASE_URL, "get_cases", 12, {"suite_id": 3, "limit": 250, "offset": 0})
        assert url == "https://acme.testrail.io/index.php?/api/v2/get_cases/12&suite_id=3&limit=250&offset=0"

    def test_method_without_id_or_params(self) -> None:
        assert _build_url(BASE_URL, "get_statuses") == "https://acme.testrail.io/index.php?/api/v2/get_statuses"

    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("full_host", "acme.testrail.io", "acme"),
            ("scheme_and_slash", "https://acme.testrail.io/", "acme"),
            ("whitespace", "  acme  ", "acme"),
        ]
    )
    def test_normalize_subdomain_accepts(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected

    @parameterized.expand(
        [
            ("path_injection", "evil.com/index.php"),
            ("at_sign", "user@evil.com"),
            ("dotted_host", "acme.evil.com"),
            ("empty", ""),
        ]
    )
    def test_normalize_subdomain_rejects_retargeting(self, _name: str, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_subdomain(raw)


class TestToEpoch:
    @parameterized.expand(
        [
            ("int_passthrough", 1700000000, 1700000000),
            ("numeric_string", "1700000000", 1700000000),
            ("datetime_utc", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            ("naive_datetime_treated_as_utc", datetime(2023, 11, 14, 22, 13, 20), 1700000000),
            ("date_midnight_utc", date(2023, 11, 14), 1699920000),
        ]
    )
    def test_coercions(self, _name: str, value: Any, expected: int) -> None:
        assert _to_epoch(value) == expected


class TestExtractItems:
    def test_plain_array_is_a_single_page(self) -> None:
        items, has_more = _extract_items([{"id": 1}], "suites")
        assert items == [{"id": 1}]
        assert has_more is False

    def test_bulk_envelope_reads_items_and_next_link(self) -> None:
        items, has_more = _extract_items(_bulk("cases", [{"id": 2}], has_more=True), "cases")
        assert items == [{"id": 2}]
        assert has_more is True

    def test_null_next_link_terminates(self) -> None:
        _, has_more = _extract_items(_bulk("cases", [{"id": 2}] * PAGE_SIZE, has_more=False), "cases")
        # A full page with a null `_links.next` must NOT be treated as "more" — an endpoint that
        # ignores limit/offset would otherwise loop on the same page forever.
        assert has_more is False

    @parameterized.expand([("string", "nope"), ("wrong_key", {"other": []}), ("null", None)])
    def test_unexpected_payload_is_retryable(self, _name: str, payload: Any) -> None:
        with pytest.raises(TestrailRetryableError):
            _extract_items(payload, "cases")


class TestFetch:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else []
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        with pytest.raises(TestrailRetryableError):
            _fetch_unwrapped(
                self._session_returning(status), "https://acme.testrail.io/index.php?/api/v2/x", MagicMock()
            )

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        with pytest.raises(requests.HTTPError):
            _fetch_unwrapped(
                self._session_returning(status), "https://acme.testrail.io/index.php?/api/v2/x", MagicMock()
            )


class TestPagination:
    def test_follows_next_link_and_checkpoints_after_each_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()

        def projects(params: dict[str, str]) -> dict:
            if params["offset"] == "0":
                return _bulk("projects", [{"id": 1}], has_more=True)
            return _bulk("projects", [{"id": 2}], has_more=False)

        api = _FakeApi({("get_projects", None): projects})
        rows = _collect(api, "projects", monkeypatch, manager=manager)

        assert [row["id"] for row in rows] == [1, 2]
        offsets = [params["offset"] for params in api.params_for("get_projects")]
        assert offsets == ["0", str(PAGE_SIZE)]
        # State is saved AFTER each yielded page, pointing at the next page's offset.
        assert [(s.parent_path, s.offset) for s in manager.saved] == [([], PAGE_SIZE), ([], PAGE_SIZE * 2)]


class TestSuiteScopedFanOut:
    def _api(self) -> _FakeApi:
        return _FakeApi(
            {
                ("get_projects", None): _bulk("projects", [{"id": 1}]),
                ("get_suites", 1): [{"id": 10}, {"id": 11}],
                ("get_cases", 1): lambda params: _bulk(
                    "cases", [{"id": int(params["suite_id"]) * 100, "suite_id": int(params["suite_id"])}]
                ),
            }
        )

    def test_cases_fan_out_over_every_suite(self, monkeypatch: Any) -> None:
        rows = _collect(self._api(), "cases", monkeypatch)
        assert [row["id"] for row in rows] == [1000, 1100]

    def test_incremental_sends_updated_after_to_every_case_request(self, monkeypatch: Any) -> None:
        api = self._api()
        _collect(
            api, "cases", monkeypatch, should_use_incremental_field=True, db_incremental_field_last_value=1700000000
        )
        case_params = api.params_for("get_cases")
        assert len(case_params) == 2
        assert all(params["updated_after"] == "1700000000" for params in case_params)

    def test_full_refresh_sends_no_timestamp_filter(self, monkeypatch: Any) -> None:
        api = self._api()
        _collect(api, "cases", monkeypatch)
        assert all("updated_after" not in params for params in api.params_for("get_cases"))

    def test_resume_skips_completed_suites_and_restarts_at_saved_offset(self, monkeypatch: Any) -> None:
        api = self._api()
        manager = _FakeResumableManager(TestrailResumeConfig(parent_path=[1, 11], offset=PAGE_SIZE))
        rows = _collect(api, "cases", monkeypatch, manager=manager)
        # Suite 10 compares below the saved position, so it was fully synced before the crash.
        assert [row["id"] for row in rows] == [1100]
        case_params = api.params_for("get_cases")
        assert [params["suite_id"] for params in case_params] == ["11"]
        assert case_params[0]["offset"] == str(PAGE_SIZE)


class TestRunsEndpoint:
    def _api(self) -> _FakeApi:
        return _FakeApi(
            {
                ("get_projects", None): _bulk("projects", [{"id": 1}]),
                ("get_runs", 1): _bulk("runs", [{"id": 100, "plan_id": None}]),
                ("get_plans", 1): _bulk("plans", [{"id": 200}]),
                ("get_plan", 200): {"id": 200, "entries": [{"runs": [{"id": 201, "plan_id": 200}]}]},
            }
        )

    def test_combines_standalone_and_plan_entry_runs(self, monkeypatch: Any) -> None:
        rows = _collect(self._api(), "runs", monkeypatch)
        assert [row["id"] for row in rows] == [100, 201]

    def test_incremental_bounds_both_get_runs_and_get_plans(self, monkeypatch: Any) -> None:
        api = self._api()
        _collect(
            api, "runs", monkeypatch, should_use_incremental_field=True, db_incremental_field_last_value=1700000000
        )
        assert api.params_for("get_runs")[0]["created_after"] == "1700000000"
        assert api.params_for("get_plans")[0]["created_after"] == "1700000000"


class TestRunScopedFanOut:
    def _api(self) -> _FakeApi:
        return _FakeApi(
            {
                ("get_projects", None): _bulk("projects", [{"id": 1}]),
                ("get_runs", 1): _bulk("runs", [{"id": 100}]),
                ("get_plans", 1): _bulk("plans", [{"id": 200}]),
                ("get_plan", 200): {"id": 200, "entries": [{"runs": [{"id": 201}]}]},
                ("get_results_for_run", 100): _bulk("results", [{"id": 9000, "test_id": 1}]),
                ("get_results_for_run", 201): _bulk("results", [{"id": 9001, "test_id": 2}]),
            }
        )

    def test_results_cover_plan_entry_runs(self, monkeypatch: Any) -> None:
        rows = _collect(self._api(), "results", monkeypatch)
        assert [row["id"] for row in rows] == [9000, 9001]

    def test_incremental_filters_results_but_not_run_enumeration(self, monkeypatch: Any) -> None:
        # The run walk must stay unfiltered so results added to OLD runs after the watermark are
        # still found; only the per-run results request carries created_after.
        api = self._api()
        _collect(
            api, "results", monkeypatch, should_use_incremental_field=True, db_incremental_field_last_value=1700000000
        )
        assert all("created_after" not in params for params in api.params_for("get_runs"))
        assert all("created_after" not in params for params in api.params_for("get_plans"))
        assert all(params["created_after"] == "1700000000" for params in api.params_for("get_results_for_run"))


class TestUsersEndpoint:
    def test_admin_listing_is_used_when_permitted(self, monkeypatch: Any) -> None:
        api = _FakeApi({("get_users", None): [{"id": 1}, {"id": 2}]})
        rows = _collect(api, "users", monkeypatch)
        assert [row["id"] for row in rows] == [1, 2]
        # No per-project fallback means get_projects is never called.
        assert api.params_for("get_projects") == []

    def test_forbidden_admin_listing_falls_back_to_per_project_with_dedupe(self, monkeypatch: Any) -> None:
        api = _FakeApi(
            {
                ("get_users", None): _http_error(403),
                ("get_projects", None): _bulk("projects", [{"id": 1}, {"id": 2}]),
                ("get_users", 1): [{"id": 7}, {"id": 8}],
                ("get_users", 2): [{"id": 8}, {"id": 9}],
            }
        )
        rows = _collect(api, "users", monkeypatch)
        assert [row["id"] for row in rows] == [7, 8, 9]

    def test_non_403_admin_error_propagates(self, monkeypatch: Any) -> None:
        api = _FakeApi({("get_users", None): _http_error(500)})
        with pytest.raises(requests.HTTPError):
            _collect(api, "users", monkeypatch)


class TestInstanceDictionaries:
    def test_statuses_yield_from_a_single_plain_array_request(self, monkeypatch: Any) -> None:
        api = _FakeApi({("get_statuses", None): [{"id": 1, "name": "passed"}]})
        rows = _collect(api, "statuses", monkeypatch)
        assert rows == [{"id": 1, "name": "passed"}]
        assert len(api.requests) == 1
        # Dictionary endpoints are documented as plain arrays — no pagination params sent.
        assert api.params_for("get_statuses") == [{}]


class TestTestrailSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = make_testrail_source(
            subdomain="acme",
            username="qa@acme.com",
            api_key="secret",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Fan-out rows never arrive globally time-ordered, so incremental endpoints must commit
        # their watermark only at end of sync (desc); asc would corrupt it on mid-sync restarts.
        config = TESTRAIL_ENDPOINTS[endpoint]
        assert response.sort_mode == ("desc" if config.incremental_param else "asc")
        # Only endpoints carrying a stable `created_on` partition; the rest stay unpartitioned so a
        # missing/moving key never becomes a datetime bucket. `created_on` (not the `updated_on`
        # cursor) keeps partitions from being rewritten on later syncs.
        if config.partition_key:
            assert config.partition_key == "created_on"
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == ["created_on"]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestCheckAccess:
    def _response(self, status: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        if body is None:
            response.json.side_effect = ValueError("no body")
        else:
            response.json.return_value = body
        return response

    @patch(f"{testrail.__name__}._make_session")
    def test_surfaces_testrail_error_message_on_forbidden(self, mock_session: MagicMock) -> None:
        api_disabled = "The API is disabled for your installation."
        mock_session.return_value.get.return_value = self._response(403, {"error": api_disabled})
        assert check_access("acme", "qa@acme.com", "key") == (403, api_disabled)

    @patch(f"{testrail.__name__}._make_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        status, message = check_access("acme", "qa@acme.com", "key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid TestRail email or API key"),
            ("server_error", 500, False, "TestRail returned HTTP 500"),
        ]
    )
    @patch(f"{testrail.__name__}._make_session")
    def test_validate_credentials_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None, mock_session: MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = self._response(status)
        assert validate_credentials("acme", "qa@acme.com", "key") == (expected_valid, expected_message)

    def test_malformed_subdomain_returns_precise_message(self) -> None:
        valid, message = validate_credentials("evil.com/@x", "qa@acme.com", "key")
        assert valid is False
        assert message is not None and "Invalid TestRail address" in message
