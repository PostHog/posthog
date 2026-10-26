from collections.abc import Mapping
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mention import (
    MentionSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mention import mention
from products.warehouse_sources.backend.temporal.data_imports.sources.mention.mention import (
    MENTION_BASE_URL,
    MENTION_HOST,
    MentionResumeConfig,
    MentionRetryableError,
    _more_url,
    check_access,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mention.settings import (
    ENDPOINTS,
    MENTION_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mention.source import MentionSource

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = mention._fetch_page.__wrapped__  # type: ignore[attr-defined]

ME_URL = f"{MENTION_BASE_URL}/accounts/me"
ME_PAYLOAD = {"account": {"id": "acc1", "name": "NASA"}}


class _FakeResumableManager:
    def __init__(self, state: MentionResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[MentionResumeConfig] = []
        self.safe_points = 0

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> MentionResumeConfig | None:
        return self._state

    def save_state(self, data: MentionResumeConfig) -> None:
        self.saved.append(data)

    def safe_point(self) -> None:
        self.safe_points += 1


class TestGetRows:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(MentionSource(), MentionSourceConfig(access_token="tok"))

    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: Mapping[str, Any],
        endpoint: str,
        api_version: str = mention.API_VERSION_1_19,
    ) -> list[dict]:
        def fake_fetch(session: Any, url: str, logger: Any) -> dict[str, Any]:
            assert url in pages, f"unexpected request to {url}"
            return pages[url]

        monkeypatch.setattr(mention, "_fetch_page", fake_fetch)
        monkeypatch.setattr(mention, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            access_token="tok",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            api_version=api_version,
        ):
            rows.extend(batch)
        return rows

    def test_alerts_follows_more_link_and_unwraps_items(self) -> None:
        more_href = "/api/accounts/acc1/alerts?limit=100&cursor=abc"
        second = f"{MENTION_HOST}{more_href}"
        result = self._driver().run(
            "alerts",
            [
                ScriptedResponse(json=ME_PAYLOAD),
                # The docs show list items in single-GET form ({"alert": {...}}) — both shapes must work.
                ScriptedResponse(json={"alerts": [{"alert": {"id": 11}}], "_links": {"more": {"href": more_href}}}),
                ScriptedResponse(json={"alerts": [{"id": 22}]}),
            ],
            api_version=mention.API_VERSION_1_19,
        )
        assert result.raised is None
        assert result.rows == [{"id": 11}, {"id": 22}]
        assert result.paths == ["/api/accounts/me", "/api/accounts/acc1/alerts", "/api/accounts/acc1/alerts"]
        assert result.params("limit") == [None, "100", "100"]
        assert result.params("cursor") == [None, None, "abc"]
        # State is saved once — after the first page, pointing at the resolved absolute cursor URL.
        assert result.saved_states == [MentionResumeConfig(next_url=second)]

    def test_alerts_resumes_from_saved_cursor(self) -> None:
        second = f"{MENTION_HOST}/api/accounts/acc1/alerts?limit=100&cursor=abc"
        # Neither /accounts/me nor the first page may be fetched on resume.
        result = self._driver().run(
            "alerts",
            [ScriptedResponse(json={"alerts": [{"id": 22}]})],
            resume_state=MentionResumeConfig(next_url=second),
        )
        assert result.raised is None
        assert result.rows == [{"id": 22}]
        assert result.urls == [second]

    def test_mentions_fan_out_injects_alert_id_and_saves_state(self) -> None:
        more_href = "/api/accounts/acc1/alerts/11/mentions?limit=100&before_date=2024-01-01T00:00:00.0"
        second_11 = f"{MENTION_HOST}{more_href}"
        result = self._driver().run(
            "mentions",
            [
                ScriptedResponse(json=ME_PAYLOAD),
                ScriptedResponse(json={"alerts": [{"alert": {"id": 11}}, {"alert": {"id": 22}}]}),
                ScriptedResponse(
                    json={"mentions": [{"id": "m1", "alert_id": 11}], "_links": {"more": {"href": more_href}}}
                ),
                ScriptedResponse(json={"mentions": [{"id": "m2", "alert_id": 11}], "_links": {}}),
                ScriptedResponse(json={"mentions": [{"id": "m3", "alert_id": 22}], "_links": {}}),
            ],
            api_version=mention.API_VERSION_1_19,
        )
        assert result.raised is None
        # alert_id is normalized to a string so the composite merge key type is consistent.
        assert result.rows == [
            {"id": "m1", "alert_id": "11"},
            {"id": "m2", "alert_id": "11"},
            {"id": "m3", "alert_id": "22"},
        ]
        assert [(s.alert_ids, s.next_url) for s in result.saved_states] == [
            (["11", "22"], second_11),
            (["22"], None),
            ([], None),
        ]
        assert result.paths == [
            "/api/accounts/me",
            "/api/accounts/acc1/alerts",
            "/api/accounts/acc1/alerts/11/mentions",
            "/api/accounts/acc1/alerts/11/mentions",
            "/api/accounts/acc1/alerts/22/mentions",
        ]
        assert result.params("before_date") == [None, None, None, "2024-01-01T00:00:00.0", None]

    def test_mentions_resume_skips_completed_alerts_and_uses_cursor(self) -> None:
        cursor = f"{MENTION_HOST}/api/accounts/acc1/alerts/22/mentions?limit=100&before_date=2024-01-01T00:00:00.0"
        # Alert 11 and the alerts listing must never be re-fetched; alert 22 resumes mid-pagination.
        result = self._driver().run(
            "mentions",
            [ScriptedResponse(json=ME_PAYLOAD), ScriptedResponse(json={"mentions": [{"id": "m4"}], "_links": {}})],
            resume_state=MentionResumeConfig(alert_ids=["22"], next_url=cursor),
        )
        assert result.raised is None
        assert result.rows == [{"id": "m4", "alert_id": "22"}]
        assert result.urls == [ME_URL, cursor]

    def test_alert_tags_injects_alert_id_without_pagination(self) -> None:
        result = self._driver().run(
            "alert_tags",
            [
                ScriptedResponse(json=ME_PAYLOAD),
                ScriptedResponse(json={"alerts": [{"alert": {"id": 11}}]}),
                # The tags endpoint's `_links` is an empty list, not a dict — must not be treated as a cursor.
                ScriptedResponse(json={"tags": [{"id": 46468, "name": "space"}], "_links": []}),
            ],
            api_version=mention.API_VERSION_1_19,
        )
        assert result.raised is None
        assert result.rows == [{"id": 46468, "name": "space", "alert_id": "11"}]
        assert result.paths == ["/api/accounts/me", "/api/accounts/acc1/alerts", "/api/accounts/acc1/alerts/11/tags"]
        assert result.saved_states == [MentionResumeConfig(alert_ids=[])]

    @parameterized.expand([("alert_authors", "authors"), ("alert_tasks", "tasks")])
    def test_paginated_fan_out_walks_each_alert_and_stages_state(self, endpoint: str, path: str) -> None:
        manager = _FakeResumableManager()
        alerts_url = f"{MENTION_BASE_URL}/accounts/acc1/alerts?limit=100"
        first_11 = f"{MENTION_BASE_URL}/accounts/acc1/alerts/11/{path}?limit=100"
        more_href = f"/api/accounts/acc1/alerts/11/{path}?limit=100&before_id=140548"
        second_11 = f"{MENTION_HOST}{more_href}"
        first_22 = f"{MENTION_BASE_URL}/accounts/acc1/alerts/22/{path}?limit=100"
        pages = {
            ME_URL: ME_PAYLOAD,
            alerts_url: {"alerts": [{"alert": {"id": 11}}, {"alert": {"id": 22}}]},
            first_11: {path: [{"id": "a"}], "_links": {"more": {"href": more_href}}},
            second_11: {path: [{"id": "b"}], "_links": {}},
            first_22: {path: [], "_links": {}},
        }
        with pytest.MonkeyPatch.context() as monkeypatch:
            rows = self._collect(manager, monkeypatch, pages, endpoint)
        assert rows == [{"id": "a", "alert_id": "11"}, {"id": "b", "alert_id": "11"}]
        assert [(s.alert_ids, s.next_url) for s in manager.saved] == [
            (["11", "22"], second_11),
            (["22"], None),
            ([], None),
        ]
        # The empty alert yields nothing, so it must hand the worker a safe point instead.
        assert manager.safe_points == 1

    def test_paginated_fan_out_resumes_mid_alert_from_cursor(self, monkeypatch: Any) -> None:
        cursor = f"{MENTION_HOST}/api/accounts/acc1/alerts/22/tasks?limit=100&before_id=140548"
        manager = _FakeResumableManager(MentionResumeConfig(alert_ids=["22", "33"], next_url=cursor))
        first_33 = f"{MENTION_BASE_URL}/accounts/acc1/alerts/33/tasks?limit=100"
        pages = {
            ME_URL: ME_PAYLOAD,
            cursor: {"tasks": [{"id": "t1"}], "_links": {}},
            first_33: {"tasks": [{"id": "t2"}], "_links": {}},
        }
        rows = self._collect(manager, monkeypatch, pages, "alert_tasks")
        assert rows == [{"id": "t1", "alert_id": "22"}, {"id": "t2", "alert_id": "33"}]

    def test_alert_daily_stats_reshapes_series_into_daily_rows(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        window = mention.StatsWindow(start="2025-01-01T00:00:00.0", end="2026-01-01T12:00:00.0")
        monkeypatch.setattr(mention, "_stats_window", lambda now: window)
        alerts_url = f"{MENTION_BASE_URL}/accounts/acc1/alerts?limit=100"
        stats_url = (
            f"{MENTION_BASE_URL}/accounts/acc1/stats?alerts%5B%5D=11&from=2025-01-01T00%3A00%3A00.0"
            "&to=2026-01-01T12%3A00%3A00.0&timezone=UTC&interval=P1D"
            "&tones_per_interval_stats=true&reach_per_interval_stats=true"
        )
        reach = {"sum": 507, "max": 267, "avg": 48.5}
        pages = {
            ME_URL: ME_PAYLOAD,
            alerts_url: {"alerts": [{"alert": {"id": 11}}]},
            stats_url: {
                "stats": {
                    "11": {
                        "mentions_per_interval": {"data": {"2025-06-02": 5, "2025-06-01": 322}, "total": 327},
                        "tones_per_interval": {"data": {"2025-06-01": {"-1": 7, "0": 267, "1": 48}}},
                        "direct_reach_per_interval": {"data": {"2025-06-01": reach}},
                        "week_days_total": {"data": {"1": [3, 36]}, "total": 39},
                    }
                },
                "from": window.start,
                "to": window.end,
            },
        }
        rows = self._collect(manager, monkeypatch, pages, "alert_daily_stats")
        assert rows == [
            {
                "alert_id": "11",
                "date": "2025-06-01",
                "mentions": 322,
                "negative_mentions": 7,
                "neutral_mentions": 267,
                "positive_mentions": 48,
                "direct_reach": reach,
                "cumulative_reach": None,
                "domain_reach": None,
            },
            {
                "alert_id": "11",
                "date": "2025-06-02",
                "mentions": 5,
                "negative_mentions": None,
                "neutral_mentions": None,
                "positive_mentions": None,
                "direct_reach": None,
                "cumulative_reach": None,
                "domain_reach": None,
            },
        ]
        assert [s.alert_ids for s in manager.saved] == [[]]

    def test_alert_daily_stats_partial_response_is_retryable(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(MentionResumeConfig(alert_ids=["11"]))
        monkeypatch.setattr(mention, "_stats_window", lambda now: mention.StatsWindow(start="f", end="t"))
        stats_url = (
            f"{MENTION_BASE_URL}/accounts/acc1/stats?alerts%5B%5D=11&from=f&to=t&timezone=UTC&interval=P1D"
            "&tones_per_interval_stats=true&reach_per_interval_stats=true"
        )
        pages = {ME_URL: ME_PAYLOAD, stats_url: {"stats": {"11": {}}, "partial": True}}
        with pytest.raises(MentionRetryableError, match="partial stats"):
            self._collect(manager, monkeypatch, pages, "alert_daily_stats")
        # The alert stays queued so the retried sync fetches its stats again.
        assert manager.saved == []

    def test_unknown_endpoint_raises(self, monkeypatch: Any) -> None:
        with pytest.raises(ValueError, match="Unknown Mention endpoint 'nope'"):
            self._collect(_FakeResumableManager(), monkeypatch, {}, "nope")


class TestApiVersioning:
    @parameterized.expand([(v,) for v in mention.SUPPORTED_API_VERSIONS])
    def test_pinned_version_reaches_accept_version_header(self, api_version: str) -> None:
        # A pinned source must send its version; otherwise the sync silently tracks the app's
        # configured version — the drift the pinning framework exists to prevent.
        result = TestGetRows._driver().run("accounts", [ScriptedResponse(json=ME_PAYLOAD)], api_version=api_version)
        assert result.raised is None
        assert result.requests[0].headers["accept-version"] == api_version

    @parameterized.expand(
        [
            (mention.API_VERSION_1_19, f"{MENTION_BASE_URL}/accounts/acc1/alerts?limit=100"),
            (
                mention.API_VERSION_1_21,
                f"{MENTION_BASE_URL}/accounts/acc1/alerts?limit=100&stats={mention.ALERT_STATS_PARAM}",
            ),
        ]
    )
    def test_alerts_request_asks_for_stats_only_from_1_21(self, api_version: str, alerts_url: str) -> None:
        # 1.21 empties the alert `stats` field unless the counters are requested explicitly; 1.19
        # returns them by default, so only the newer version appends the `stats` query parameter.
        result = TestGetRows._driver().run(
            "alerts",
            [ScriptedResponse(json=ME_PAYLOAD), ScriptedResponse(json={"alerts": [{"id": 1}]})],
            api_version=api_version,
        )
        assert result.raised is None
        assert result.urls[-1] == alerts_url


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"mentions": [], "_links": {}}
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(MentionRetryableError):
            _fetch_page_unwrapped(session, ME_URL, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, ME_URL, MagicMock())

    def test_non_dict_payload_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": "a"}])
        with pytest.raises(MentionRetryableError):
            _fetch_page_unwrapped(session, ME_URL, MagicMock())

    def test_success_returns_payload_without_extra_params(self) -> None:
        body = {"mentions": [{"id": "m1"}], "_links": {}}
        session = self._session_returning(200, body)
        url = f"{MENTION_BASE_URL}/accounts/acc1/alerts/11/mentions?limit=100&before_date=x"
        assert _fetch_page_unwrapped(session, url, MagicMock()) == body
        args, kwargs = session.get.call_args
        assert args[0] == url
        # The cursor URL already carries paging; we must not re-send page params.
        assert "params" not in kwargs


class TestMoreUrl:
    @parameterized.expand(
        [
            ("relative_href", {"_links": {"more": {"href": "/api/a?cursor=x"}}}, f"{MENTION_HOST}/api/a?cursor=x"),
            ("absolute_href", {"_links": {"more": {"href": f"{MENTION_HOST}/api/b"}}}, f"{MENTION_HOST}/api/b"),
            ("no_more", {"_links": {"pull": {"href": "/api/a"}}}, None),
            ("links_is_empty_list", {"_links": []}, None),
            ("missing_links", {"mentions": []}, None),
            ("empty_href", {"_links": {"more": {"href": ""}}}, None),
        ]
    )
    def test_more_url(self, _name: str, payload: dict[str, Any], expected: Optional[str]) -> None:
        assert _more_url(payload) == expected

    @parameterized.expand(
        [
            ("absolute_off_host", "https://evil.com/api/x"),
            ("protocol_relative", "//evil.com/api"),
            ("lookalike_host", "https://api.mention.net.evil.com/api/x"),
        ]
    )
    def test_more_url_rejects_off_host_pagination(self, _name: str, href: str) -> None:
        # A tampered cursor must never send the bearer-token session to another host.
        with pytest.raises(MentionRetryableError, match="not on the Mention API host"):
            _more_url({"_links": {"more": {"href": href}}})


class TestCheckAccess:
    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        script = always(ScriptedResponse(status=status)) if status >= 500 else [ScriptedResponse(status=status)]
        with scripted_network(script) as network:
            assert check_access("tok") == (expected_status, expected_message)
        assert network.requests_log[0].path == "/api/accounts/me"
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"

    def test_connection_error_maps_to_zero(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            status, message = check_access("tok")
        assert status == 0
        assert message is not None and "boom" in message
        assert {request.path for request in network.requests_log} == {"/api/accounts/me"}

    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        script = always(ScriptedResponse(status=status)) if status >= 500 else [ScriptedResponse(status=status)]
        with scripted_network(script) as network:
            assert validate_credentials("tok") == (expected_valid, expected_message)
        assert network.requests_log[0].path == "/api/accounts/me"


class TestMentionSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        script = [ScriptedResponse(json=ME_PAYLOAD)]
        if endpoint != "accounts":
            script.append(ScriptedResponse(json={"alerts": []}))
        result = TestGetRows._driver().run(endpoint, script)
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == MENTION_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_fan_out_endpoints_carry_parent_id_in_key(self) -> None:
        # Fan-out children aggregate rows from every alert; the parent id must be in the merge key.
        assert MENTION_ENDPOINTS["mentions"].primary_keys == ["alert_id", "id"]
        assert MENTION_ENDPOINTS["alert_tags"].primary_keys == ["alert_id", "id"]
