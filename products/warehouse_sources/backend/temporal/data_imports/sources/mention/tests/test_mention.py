from collections.abc import Mapping
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.mention import mention
from products.warehouse_sources.backend.temporal.data_imports.sources.mention.mention import (
    MENTION_BASE_URL,
    MENTION_HOST,
    MentionResumeConfig,
    MentionRetryableError,
    _more_url,
    check_access,
    get_rows,
    mention_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mention.settings import (
    ENDPOINTS,
    MENTION_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = mention._fetch_page.__wrapped__  # type: ignore[attr-defined]

ME_URL = f"{MENTION_BASE_URL}/accounts/me"
ME_PAYLOAD = {"account": {"id": "acc1", "name": "NASA"}}


class _FakeResumableManager:
    def __init__(self, state: MentionResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[MentionResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> MentionResumeConfig | None:
        return self._state

    def save_state(self, data: MentionResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: Mapping[str, Any],
        endpoint: str,
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
        ):
            rows.extend(batch)
        return rows

    def test_accounts_yields_single_unwrapped_row(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {ME_URL: ME_PAYLOAD}, "accounts")
        assert rows == [{"id": "acc1", "name": "NASA"}]
        assert manager.saved == []

    def test_alerts_follows_more_link_and_unwraps_items(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        first = f"{MENTION_BASE_URL}/accounts/acc1/alerts?limit=100"
        more_href = "/api/accounts/acc1/alerts?limit=100&cursor=abc"
        second = f"{MENTION_HOST}{more_href}"
        pages = {
            ME_URL: ME_PAYLOAD,
            # The docs show list items in single-GET form ({"alert": {...}}) — both shapes must work.
            first: {"alerts": [{"alert": {"id": 11}}], "_links": {"more": {"href": more_href}}},
            second: {"alerts": [{"id": 22}]},
        }
        rows = self._collect(manager, monkeypatch, pages, "alerts")
        assert rows == [{"id": 11}, {"id": 22}]
        # State is saved once — after the first page, pointing at the resolved absolute cursor URL.
        assert [s.next_url for s in manager.saved] == [second]

    def test_alerts_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        second = f"{MENTION_HOST}/api/accounts/acc1/alerts?limit=100&cursor=abc"
        manager = _FakeResumableManager(MentionResumeConfig(next_url=second))
        # Neither /accounts/me nor the first page may be fetched on resume.
        rows = self._collect(manager, monkeypatch, {second: {"alerts": [{"id": 22}]}}, "alerts")
        assert rows == [{"id": 22}]

    def test_mentions_fan_out_injects_alert_id_and_saves_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        alerts_url = f"{MENTION_BASE_URL}/accounts/acc1/alerts?limit=100"
        first_11 = f"{MENTION_BASE_URL}/accounts/acc1/alerts/11/mentions?limit=100"
        more_href = "/api/accounts/acc1/alerts/11/mentions?limit=100&before_date=2024-01-01T00:00:00.0"
        second_11 = f"{MENTION_HOST}{more_href}"
        first_22 = f"{MENTION_BASE_URL}/accounts/acc1/alerts/22/mentions?limit=100"
        pages = {
            ME_URL: ME_PAYLOAD,
            alerts_url: {"alerts": [{"alert": {"id": 11}}, {"alert": {"id": 22}}]},
            first_11: {"mentions": [{"id": "m1", "alert_id": 11}], "_links": {"more": {"href": more_href}}},
            second_11: {"mentions": [{"id": "m2", "alert_id": 11}], "_links": {}},
            first_22: {"mentions": [{"id": "m3", "alert_id": 22}], "_links": {}},
        }
        rows = self._collect(manager, monkeypatch, pages, "mentions")
        # alert_id is normalized to a string so the composite merge key type is consistent.
        assert rows == [
            {"id": "m1", "alert_id": "11"},
            {"id": "m2", "alert_id": "11"},
            {"id": "m3", "alert_id": "22"},
        ]
        assert [(s.alert_ids, s.next_url) for s in manager.saved] == [
            (["11", "22"], second_11),
            (["22"], None),
            ([], None),
        ]

    def test_mentions_resume_skips_completed_alerts_and_uses_cursor(self, monkeypatch: Any) -> None:
        cursor = f"{MENTION_HOST}/api/accounts/acc1/alerts/22/mentions?limit=100&before_date=2024-01-01T00:00:00.0"
        manager = _FakeResumableManager(MentionResumeConfig(alert_ids=["22"], next_url=cursor))
        # Alert 11 and the alerts listing must never be re-fetched; alert 22 resumes mid-pagination.
        pages = {
            ME_URL: ME_PAYLOAD,
            cursor: {"mentions": [{"id": "m4"}], "_links": {}},
        }
        rows = self._collect(manager, monkeypatch, pages, "mentions")
        assert rows == [{"id": "m4", "alert_id": "22"}]

    def test_mentions_empty_page_with_more_link_terminates(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        alerts_url = f"{MENTION_BASE_URL}/accounts/acc1/alerts?limit=100"
        first_11 = f"{MENTION_BASE_URL}/accounts/acc1/alerts/11/mentions?limit=100"
        pages = {
            ME_URL: ME_PAYLOAD,
            alerts_url: {"alerts": [{"alert": {"id": 11}}]},
            # A lingering more link on an empty page must not produce an infinite loop.
            first_11: {"mentions": [], "_links": {"more": {"href": "/api/anything"}}},
        }
        assert self._collect(manager, monkeypatch, pages, "mentions") == []

    def test_alert_tags_injects_alert_id_without_pagination(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        alerts_url = f"{MENTION_BASE_URL}/accounts/acc1/alerts?limit=100"
        tags_url = f"{MENTION_BASE_URL}/accounts/acc1/alerts/11/tags"
        pages = {
            ME_URL: ME_PAYLOAD,
            alerts_url: {"alerts": [{"alert": {"id": 11}}]},
            # The tags endpoint's `_links` is an empty list, not a dict — must not be treated as a cursor.
            tags_url: {"tags": [{"id": 46468, "name": "space"}], "_links": []},
        }
        rows = self._collect(manager, monkeypatch, pages, "alert_tags")
        assert rows == [{"id": 46468, "name": "space", "alert_id": "11"}]
        assert [s.alert_ids for s in manager.saved] == [[]]

    def test_unknown_endpoint_raises(self, monkeypatch: Any) -> None:
        with pytest.raises(ValueError, match="Unknown Mention endpoint 'nope'"):
            self._collect(_FakeResumableManager(), monkeypatch, {}, "nope")


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
    def _session(self, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Mention returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        with patch.object(mention, "make_tracked_session", return_value=self._session(response)):
            assert check_access("tok") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with patch.object(mention, "make_tracked_session", return_value=session):
            status, message = check_access("tok")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Mention access token"),
            ("forbidden", 403, False, "Invalid Mention access token"),
            ("server_error", 500, False, "Mention returned HTTP 500"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        with patch.object(mention, "make_tracked_session", return_value=self._session(response)):
            assert validate_credentials("tok") == (expected_valid, expected_message)


class TestMentionSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = mention_source(
            access_token="tok",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == MENTION_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_fan_out_endpoints_carry_parent_id_in_key(self) -> None:
        # Fan-out children aggregate rows from every alert; the parent id must be in the merge key.
        assert MENTION_ENDPOINTS["mentions"].primary_keys == ["alert_id", "id"]
        assert MENTION_ENDPOINTS["alert_tags"].primary_keys == ["alert_id", "id"]
