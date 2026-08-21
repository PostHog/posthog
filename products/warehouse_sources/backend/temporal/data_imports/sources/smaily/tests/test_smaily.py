from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.smaily import smaily
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.settings import (
    CAMPAIGN_STATISTICS,
    ENDPOINTS,
    SEGMENT_SUBSCRIBERS,
    SMAILY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.smaily import (
    SmailyResumeConfig,
    SmailyRetryableError,
    check_access,
    get_rows,
    normalize_subdomain,
    smaily_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_unwrapped = smaily._fetch.__wrapped__  # type: ignore[attr-defined]

BASE_URL = "https://acme.sendsmaily.net/api"


class _FakeResumableManager:
    def __init__(self, state: SmailyResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SmailyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SmailyResumeConfig | None:
        return self._state

    def save_state(self, data: SmailyResumeConfig) -> None:
        self.saved.append(data)


class _FakeApi:
    """Routes `_fetch(session, url, params, logger)` calls to canned responses and records requests."""

    def __init__(self, responder: Any) -> None:
        self._responder = responder
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, session: Any, url: str, params: dict[str, Any], logger: Any, expect_list: bool = False) -> Any:
        self.requests.append((url, dict(params)))
        return self._responder(url, params)


def _collect(
    monkeypatch: Any,
    endpoint: str,
    responder: Any,
    manager: _FakeResumableManager | None = None,
) -> tuple[list[dict], _FakeApi, _FakeResumableManager]:
    api = _FakeApi(responder)
    manager = manager or _FakeResumableManager()
    monkeypatch.setattr(smaily, "_fetch", api)
    monkeypatch.setattr(smaily, "make_tracked_session", lambda **kwargs: MagicMock())

    rows: list[dict] = []
    for batch in get_rows(
        subdomain="acme",
        username="user",
        password="pass",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(batch)
    return rows, api, manager


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("uppercase_and_whitespace", "  ACME ", "acme"),
            ("full_domain", "acme.sendsmaily.net", "acme"),
            ("full_url_with_path", "https://acme.sendsmaily.net/api/", "acme"),
            ("hyphenated", "my-company", "my-company"),
        ]
    )
    def test_valid_inputs(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("other_domain", "evil.com"),
            ("smuggled_credentials", "acme.sendsmaily.net@evil.com"),
            ("leading_hyphen", "-acme"),
        ]
    )
    def test_invalid_inputs_are_rejected(self, _name: str, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_subdomain(raw)


class TestFetch:
    def _session_returning(self, status_code: int, body: Any = None, invalid_json: bool = False) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        if invalid_json:
            response.json.side_effect = ValueError("not json")
        else:
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
        session = self._session_returning(status)
        with pytest.raises(SmailyRetryableError):
            _fetch_unwrapped(session, f"{BASE_URL}/campaign.php", {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_unwrapped(session, f"{BASE_URL}/campaign.php", {}, MagicMock())

    def test_non_json_body_is_retryable(self) -> None:
        # Smaily serves JSON with a text/html Content-Type; an HTML error page must not crash the sync.
        session = self._session_returning(200, invalid_json=True)
        with pytest.raises(SmailyRetryableError):
            _fetch_unwrapped(session, f"{BASE_URL}/campaign.php", {}, MagicMock())

    @parameterized.expand([("dict_body", {"error": "nope"}), ("non_dict_rows", ["oops"])])
    def test_unexpected_list_shape_is_retryable_inside_fetch(self, _name: str, body: Any) -> None:
        # Shape validation must run inside the retried function so a malformed payload gets
        # backoff instead of failing the sync on the first hit.
        session = self._session_returning(200, body)
        with pytest.raises(SmailyRetryableError):
            _fetch_unwrapped(session, f"{BASE_URL}/campaign.php", {}, MagicMock(), expect_list=True)


class TestTopLevelEndpoints:
    def test_pages_until_short_page(self, monkeypatch: Any) -> None:
        page_size = SMAILY_ENDPOINTS["campaigns"].page_size
        assert page_size is not None
        pages = {
            0: [{"id": i} for i in range(page_size)],
            1: [{"id": page_size}],
        }
        rows, api, manager = _collect(monkeypatch, "campaigns", lambda url, params: pages[params["page"]])

        assert len(rows) == page_size + 1
        # State is saved after the first full page so a retry skips straight to page 1.
        assert [s.page for s in manager.saved] == [1]

    def test_uses_endpoint_specific_page_param_and_limit(self, monkeypatch: Any) -> None:
        # Smaily names the page-index param `page` on some endpoints and `offset` on others;
        # mixing them up silently returns page 0 forever.
        _, campaigns_api, _ = _collect(monkeypatch, "campaigns", lambda url, params: [])
        _, ab_tests_api, _ = _collect(monkeypatch, "ab_tests", lambda url, params: [])

        campaigns_url, campaigns_params = campaigns_api.requests[0]
        assert campaigns_url == f"{BASE_URL}/campaign.php"
        assert campaigns_params["page"] == 0
        assert campaigns_params["limit"] == SMAILY_ENDPOINTS["campaigns"].page_size
        assert campaigns_params["sort_by"] == "created_at"

        ab_tests_url, ab_tests_params = ab_tests_api.requests[0]
        assert ab_tests_url == f"{BASE_URL}/split.php"
        assert ab_tests_params["offset"] == 0
        assert "page" not in ab_tests_params

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SmailyResumeConfig(page=3))
        rows, api, _ = _collect(monkeypatch, "campaigns", lambda url, params: [{"id": 1}], manager)

        assert rows == [{"id": 1}]
        assert api.requests[0][1]["page"] == 3

    def test_unpaginated_endpoint_fetches_once_without_page_params(self, monkeypatch: Any) -> None:
        rows, api, manager = _collect(monkeypatch, "segments", lambda url, params: [{"id": 4, "name": "Women"}])

        assert rows == [{"id": 4, "name": "Women"}]
        assert api.requests == [(f"{BASE_URL}/list.php", {})]
        assert manager.saved == []

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        rows, _, manager = _collect(monkeypatch, "campaigns", lambda url, params: [])
        assert rows == []
        assert manager.saved == []


class TestSegmentSubscribers:
    @staticmethod
    def _responder(subscribers_by_segment: dict[str, list[list[dict] | None]]) -> Any:
        def respond(url: str, params: dict[str, Any]) -> Any:
            if url.endswith("/list.php"):
                return [{"id": segment_id} for segment_id in subscribers_by_segment]
            return subscribers_by_segment[params["list"]][params["offset"]]

        return respond

    def test_fans_out_over_segments_and_annotates_rows(self, monkeypatch: Any) -> None:
        responder = self._responder(
            {
                "1": [[{"email": "a@x.com", "last_open_at": "0000-00-00 00:00:00", "custom_field": "jah"}]],
                "2": [[{"email": "a@x.com", "last_open_at": "2024-01-01 10:00:00"}]],
            }
        )
        rows, _, _ = _collect(monkeypatch, SEGMENT_SUBSCRIBERS, responder)

        # The same email in two segments stays two distinct rows keyed by (segment_id, email).
        assert rows == [
            {"email": "a@x.com", "last_open_at": None, "custom_field": "jah", "segment_id": "1"},
            {"email": "a@x.com", "last_open_at": "2024-01-01 10:00:00", "segment_id": "2"},
        ]

    def test_paginates_within_segment_and_saves_state_after_yield(self, monkeypatch: Any) -> None:
        page_size = SMAILY_ENDPOINTS[SEGMENT_SUBSCRIBERS].page_size
        assert page_size is not None
        responder = self._responder(
            {
                "1": [
                    [{"email": f"user{i}@x.com"} for i in range(page_size)],
                    [{"email": "last@x.com"}],
                ],
            }
        )
        rows, _, manager = _collect(monkeypatch, SEGMENT_SUBSCRIBERS, responder)

        assert len(rows) == page_size + 1
        # First save: next page of segment 1; second save: segment 1 finished, queue empty.
        assert [(s.page, s.pending_parent_ids) for s in manager.saved] == [(1, ["1"]), (0, [])]

    def test_resumes_mid_segment_without_refetching_segment_list(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SmailyResumeConfig(page=2, pending_parent_ids=["5", "6"]))
        responder = self._responder(
            {
                "5": [None, None, [{"email": "resumed@x.com"}]],  # only page 2 is ever requested
                "6": [[{"email": "next@x.com"}]],
            }
        )
        rows, api, _ = _collect(monkeypatch, SEGMENT_SUBSCRIBERS, responder, manager)

        assert [row["email"] for row in rows] == ["resumed@x.com", "next@x.com"]
        # The segment list must not be re-fetched on resume — ids come from the saved queue.
        assert all(not url.endswith("/list.php") for url, _ in api.requests)
        assert api.requests[0][1] == {"list": "5", "limit": 25000, "offset": 2}


class TestCampaignStatistics:
    @staticmethod
    def _responder(stats_by_id: dict[str, Any]) -> Any:
        def respond(url: str, params: dict[str, Any]) -> Any:
            if "id" in params:
                return stats_by_id[params["id"]]
            return [{"id": int(campaign_id)} for campaign_id in stats_by_id]

        return respond

    def test_yields_one_row_per_campaign(self, monkeypatch: Any) -> None:
        responder = self._responder(
            {
                "1": {"id": 1, "delivered_count": 10},
                "2": {"id": 2, "delivered_count": 20},
            }
        )
        rows, _, manager = _collect(monkeypatch, CAMPAIGN_STATISTICS, responder)

        assert rows == [{"id": 1, "delivered_count": 10}, {"id": 2, "delivered_count": 20}]
        assert manager.saved[-1].pending_parent_ids == []

    def test_resume_skips_already_processed_campaigns(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SmailyResumeConfig(page=0, pending_parent_ids=["3"]))
        responder = self._responder({"3": {"id": 3, "delivered_count": 30}})
        rows, api, _ = _collect(monkeypatch, CAMPAIGN_STATISTICS, responder, manager)

        assert rows == [{"id": 3, "delivered_count": 30}]
        # The campaign listing must not be re-fetched on resume.
        assert api.requests == [(f"{BASE_URL}/campaign.php", {"id": "3"})]

    def test_unusable_stats_payload_yields_id_only_row(self, monkeypatch: Any) -> None:
        # A campaign whose stats come back malformed (e.g. an empty list) must not silently
        # vanish from the table — it keeps a row with a numeric id and null stats columns.
        responder = self._responder({"1": [], "2": {"id": 2, "delivered_count": 20}})
        rows, _, _ = _collect(monkeypatch, CAMPAIGN_STATISTICS, responder)

        assert rows == [{"id": 1}, {"id": 2, "delivered_count": 20}]


class TestCheckAccess:
    @staticmethod
    def _session(response: Any) -> MagicMock:
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
            ("server_error", 500, False, 500, "Smaily returned HTTP 500"),
        ]
    )
    @patch(f"{smaily.__name__}.make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        mock_session.return_value = self._session(response)
        assert check_access("acme", "user", "pass") == (expected_status, expected_message)

    @patch(f"{smaily.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("acme", "user", "pass")
        assert status == 0
        assert message is not None and "boom" in message

    def test_invalid_subdomain_fails_without_a_request(self) -> None:
        valid, message = validate_credentials("evil.com/path?x=", "user", "pass")
        assert valid is False
        assert message is not None and "subdomain" in message.lower()

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            (
                "unauthorized",
                401,
                False,
                "Invalid Smaily credentials. Check your subdomain, API username and password.",
            ),
            ("forbidden", 403, False, "Invalid Smaily credentials. Check your subdomain, API username and password."),
            ("server_error", 500, False, "Smaily returned HTTP 500"),
        ]
    )
    @patch(f"{smaily.__name__}.make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_session.return_value = self._session(response)
        assert validate_credentials("acme", "user", "pass") == (expected_valid, expected_message)


class TestSmailySourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = smaily_source(
            subdomain="acme",
            username="user",
            password="pass",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == SMAILY_ENDPOINTS[endpoint].primary_keys

    def test_segment_subscribers_key_includes_parent_segment(self) -> None:
        # `email` alone is only unique within one segment; dropping the parent id from the key
        # would multi-match merges for subscribers in several segments.
        assert SMAILY_ENDPOINTS[SEGMENT_SUBSCRIBERS].primary_keys == ["segment_id", "email"]
