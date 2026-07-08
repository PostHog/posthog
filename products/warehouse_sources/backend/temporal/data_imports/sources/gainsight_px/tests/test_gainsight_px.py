from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px import gainsight_px
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.gainsight_px import (
    GainsightPxResumeConfig,
    GainsightPxRetryableError,
    _base_url,
    _build_url,
    _normalize_row,
    gainsight_px_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import (
    GAINSIGHT_PX_ENDPOINTS,
)


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", "https://api.aptrinsic.com/v1"),
            ("eu", "https://api-eu.aptrinsic.com/v1"),
            ("us2", "https://api-us2.aptrinsic.com/v1"),
            ("unknown", "https://api.aptrinsic.com/v1"),
        ]
    )
    def test_base_url(self, region: str, expected: str) -> None:
        assert _base_url(region) == expected


class TestBuildUrl:
    def test_encodes_params(self) -> None:
        url = _build_url("https://api.aptrinsic.com/v1/users", {"pageSize": 1000, "scrollId": "a b/c"})
        assert url == "https://api.aptrinsic.com/v1/users?pageSize=1000&scrollId=a+b%2Fc"

    def test_no_params(self) -> None:
        assert _build_url("https://api.aptrinsic.com/v1/users", {}) == "https://api.aptrinsic.com/v1/users"


class TestNormalizeRow:
    def test_converts_epoch_millis_to_datetime(self) -> None:
        # 2021-01-01T00:00:00Z == 1609459200000 ms
        row = _normalize_row({"id": "u1", "createDate": 1609459200000})
        assert row["createDate"] == datetime(2021, 1, 1, tzinfo=UTC)

    def test_leaves_non_date_fields_untouched(self) -> None:
        row = _normalize_row({"id": "u1", "score": 42, "globalUnsubscribe": True, "name": "Acme"})
        assert row == {"id": "u1", "score": 42, "globalUnsubscribe": True, "name": "Acme"}

    def test_ignores_missing_and_non_int_dates(self) -> None:
        # releaseDate is an ISO string on articles — must not be reinterpreted as epoch millis.
        row = _normalize_row({"id": "a1", "releaseDate": "2021-01-01"})
        assert row["releaseDate"] == "2021-01-01"


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_codes_are_retried(self, _name: str, status_code: int) -> None:
        retryable = MagicMock(status_code=status_code)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"users": []}

        session = MagicMock()
        session.get.side_effect = [retryable, good]

        with patch.object(gainsight_px._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = gainsight_px._fetch_page(session, "https://api.aptrinsic.com/v1/users", {}, MagicMock())

        assert result == {"users": []}
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout("timed out")),
            ("connection_error", requests.ConnectionError("reset")),
        ]
    )
    def test_transient_network_errors_are_retried(self, _name: str, error: Exception) -> None:
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"users": []}
        session = MagicMock()
        session.get.side_effect = [error, good]

        with patch.object(gainsight_px._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = gainsight_px._fetch_page(session, "https://api.aptrinsic.com/v1/users", {}, MagicMock())

        assert result == {"users": []}
        assert session.get.call_count == 2

    def test_auth_error_is_not_retried(self) -> None:
        response = MagicMock(status_code=401, ok=False, text="unauthorized")
        response.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error: Unauthorized", response=cast(requests.Response, response)
        )
        session = MagicMock()
        session.get.return_value = response

        with patch.object(gainsight_px._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(requests.HTTPError):
                gainsight_px._fetch_page(session, "https://api.aptrinsic.com/v1/users", {}, MagicMock())

        assert session.get.call_count == 1

    def test_retry_exhausts_and_reraises(self) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=500)

        with patch.object(gainsight_px._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(GainsightPxRetryableError):
                gainsight_px._fetch_page(session, "https://api.aptrinsic.com/v1/users", {}, MagicMock())

        assert session.get.call_count == 5


class _FakeResumableManager:
    def __init__(self, state: GainsightPxResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[GainsightPxResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> GainsightPxResumeConfig | None:
        return self._state

    def save_state(self, data: GainsightPxResumeConfig) -> None:
        self.saved.append(data)


def _collect(endpoint: str, manager: _FakeResumableManager, monkeypatch: Any, responses: list[dict]) -> list[dict]:
    """Run get_rows with a canned sequence of API responses and flatten the yielded pages."""
    it = iter(responses)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        return next(it)

    monkeypatch.setattr(gainsight_px, "_fetch_page", fake_fetch)
    monkeypatch.setattr(gainsight_px, "make_tracked_session", lambda *a, **k: MagicMock())

    rows: list[dict] = []
    for page in get_rows(
        api_key="key",
        region="us",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(page)
    return rows


class TestScrollPagination:
    def test_follows_scroll_id_and_stops_on_short_page(self, monkeypatch: Any) -> None:
        # users caps at a large pageSize; shrink it so a 2-then-1 record run terminates.
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["users"], "page_size", 2)
        manager = _FakeResumableManager()

        rows = _collect(
            "users",
            manager,
            monkeypatch,
            [
                {"users": [{"id": "1"}, {"id": "2"}], "scrollId": "s1"},
                {"users": [{"id": "3"}], "scrollId": "s2"},  # short page → stop
            ],
        )

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        # State saved after the first (full) page only, carrying the next scroll cursor.
        assert [s.scroll_id for s in manager.saved] == ["s1"]

    def test_stops_when_scroll_id_absent(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["accounts"], "page_size", 2)
        manager = _FakeResumableManager()

        rows = _collect(
            "accounts",
            manager,
            monkeypatch,
            [{"accounts": [{"id": "1"}, {"id": "2"}], "scrollId": None}],
        )

        assert [r["id"] for r in rows] == ["1", "2"]
        assert manager.saved == []

    def test_resumes_from_saved_scroll_id(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["users"], "page_size", 2)
        seen_urls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            seen_urls.append(url)
            return {"users": [{"id": "9"}], "scrollId": None}

        monkeypatch.setattr(gainsight_px, "_fetch_page", fake_fetch)
        monkeypatch.setattr(gainsight_px, "make_tracked_session", lambda *a, **k: MagicMock())

        manager = _FakeResumableManager(GainsightPxResumeConfig(scroll_id="saved-cursor"))
        list(
            get_rows(
                api_key="key",
                region="us",
                endpoint="users",
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
        )

        assert "scrollId=saved-cursor" in seen_urls[0]


class TestPageNumberPagination:
    def test_stops_on_is_last_page(self, monkeypatch: Any) -> None:
        # page_size 1 keeps each page "full", so isLastPage (not the short-page guard) is what stops us.
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["features"], "page_size", 1)
        manager = _FakeResumableManager()

        rows = _collect(
            "features",
            manager,
            monkeypatch,
            [
                {"features": [{"id": "f1"}], "isLastPage": False},
                {"features": [{"id": "f2"}], "isLastPage": True},
            ],
        )

        assert [r["id"] for r in rows] == ["f1", "f2"]
        assert [s.page_number for s in manager.saved] == [1]

    def test_stops_on_short_page(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["segments"], "page_size", 2)
        manager = _FakeResumableManager()

        rows = _collect(
            "segments",
            manager,
            monkeypatch,
            [{"segments": [{"id": "s1"}], "isLastPage": False}],  # short page → stop even without isLastPage
        )

        assert [r["id"] for r in rows] == ["s1"]
        assert manager.saved == []

    def test_resumes_from_saved_page_number(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["features"], "page_size", 100)
        seen_urls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            seen_urls.append(url)
            return {"features": [{"id": "f"}], "isLastPage": True}

        monkeypatch.setattr(gainsight_px, "_fetch_page", fake_fetch)
        monkeypatch.setattr(gainsight_px, "make_tracked_session", lambda *a, **k: MagicMock())

        manager = _FakeResumableManager(GainsightPxResumeConfig(page_number=4))
        list(
            get_rows(
                api_key="key",
                region="us",
                endpoint="features",
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
        )

        assert "pageNumber=4" in seen_urls[0]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_maps_status_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        with patch.object(gainsight_px, "make_tracked_session", return_value=session):
            assert validate_credentials("key", "us") is expected

    def test_network_error_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(gainsight_px, "make_tracked_session", return_value=session):
            assert validate_credentials("key", "us") is False


class TestSessionHardening:
    """The API key travels in a custom `X-APTRINSIC-API-KEY` header, which the sample-capture
    denylist can't recognise. Every session must value-mask the key and leave retries to tenacity."""

    @staticmethod
    def _assert_hardened(call: Any) -> None:
        assert call.kwargs["redact_values"] == ("secret-key",)
        assert call.kwargs["retry"].total == 0

    def test_validate_credentials_masks_key_and_disables_adapter_retry(self) -> None:
        with patch.object(gainsight_px, "make_tracked_session", return_value=MagicMock()) as make_session:
            validate_credentials("secret-key", "us")
        self._assert_hardened(make_session.call_args)

    def test_get_rows_masks_key_and_disables_adapter_retry(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(gainsight_px, "_fetch_page", lambda *a, **k: {"users": [], "scrollId": None})
        with patch.object(gainsight_px, "make_tracked_session", return_value=MagicMock()) as make_session:
            list(get_rows("secret-key", "us", "users", MagicMock(), MagicMock()))
        self._assert_hardened(make_session.call_args)


class TestSourceResponse:
    @parameterized.expand(
        [
            ("accounts", ["id"], "createDate"),
            ("users", ["id"], "createDate"),
            ("features", ["id"], None),
            ("segments", ["id"], None),
            ("engagements", ["id"], None),
            ("articles", ["id"], "createdDate"),
            ("kc_bots", ["id"], "createdDate"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        response = gainsight_px_source(
            api_key="key",
            region="us",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
