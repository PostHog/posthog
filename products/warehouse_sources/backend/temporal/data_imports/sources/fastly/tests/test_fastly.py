from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.fastly import fastly
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.fastly import (
    FASTLY_BASE_URL,
    FastlyResumeConfig,
    FastlyRetryableError,
    _active_version_number,
    _build_url,
    _ensure_service_id,
    _next_page_url,
    fastly_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.settings import ENDPOINTS, FASTLY_ENDPOINTS


def _fake_response(payload: Any, next_url: str | None = None) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.links = {"next": {"url": next_url}} if next_url else {}
    return response


class _FakeResumableManager:
    def __init__(self, state: FastlyResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[FastlyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> FastlyResumeConfig | None:
        return self._state

    def save_state(self, data: FastlyResumeConfig) -> None:
        self.saved.append(data)


class TestBuildUrl:
    def test_no_params_returns_base(self) -> None:
        assert _build_url(f"{FASTLY_BASE_URL}/service", {}) == f"{FASTLY_BASE_URL}/service"

    def test_encodes_params(self) -> None:
        assert _build_url(f"{FASTLY_BASE_URL}/service", {"per_page": 100}) == f"{FASTLY_BASE_URL}/service?per_page=100"


class TestNextPageUrl:
    def test_reads_next_link(self) -> None:
        response = MagicMock()
        response.links = {"next": {"url": "https://api.fastly.com/service?page=2"}}
        assert _next_page_url(response) == "https://api.fastly.com/service?page=2"

    def test_no_next_link_returns_none(self) -> None:
        response = MagicMock()
        response.links = {}
        assert _next_page_url(response) is None


class TestEnsureServiceId:
    def test_injects_missing_service_id(self) -> None:
        assert _ensure_service_id({"name": "www"}, "SVC")["service_id"] == "SVC"

    def test_keeps_existing_service_id(self) -> None:
        assert _ensure_service_id({"service_id": "REAL"}, "SVC")["service_id"] == "REAL"


class TestActiveVersionNumber:
    @parameterized.expand(
        [
            # The active version is preferred, even when a higher (draft) version number exists.
            ("prefers_active", [{"number": 1, "active": True}, {"number": 2, "active": False}], 1),
            # With no active version, fall back to the highest version number.
            ("falls_back_to_highest", [{"number": 1, "active": False}, {"number": 3, "active": False}], 3),
            ("no_versions", [], None),
        ]
    )
    def test_active_version_number(self, _name: str, versions: list[dict], expected: int | None) -> None:
        session = MagicMock()
        with patch.object(fastly, "_fetch", return_value=_fake_response(versions)):
            assert _active_version_number(session, "SVC", {}, MagicMock()) == expected


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False)])
    def test_validate_credentials_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(fastly, "make_tracked_session", return_value=session):
            assert validate_credentials("token") is expected

    def test_validate_credentials_swallows_exceptions(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(fastly, "make_tracked_session", return_value=session):
            assert validate_credentials("token") is False


class TestTokenRedaction:
    # The token rides in the custom `Fastly-Key` header, which the transport's name-based scrubber
    # doesn't know about — both entry points must pass it as a redact value or it leaks into samples.
    def test_validate_credentials_redacts_token(self) -> None:
        make_session = MagicMock(return_value=MagicMock())
        with patch.object(fastly, "make_tracked_session", make_session):
            validate_credentials("secret-token")
        assert make_session.call_args.kwargs["redact_values"] == ("secret-token",)

    def test_get_rows_redacts_token(self) -> None:
        make_session = MagicMock(return_value=MagicMock())
        pages = {f"{FASTLY_BASE_URL}/current_user": {"id": "U1"}}

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
            return _fake_response(pages[url])

        with (
            patch.object(fastly, "_fetch", side_effect=fake_fetch),
            patch.object(fastly, "make_tracked_session", make_session),
        ):
            list(get_rows("secret-token", "current_user", MagicMock(), _FakeResumableManager()))  # type: ignore[arg-type]
        assert make_session.call_args.kwargs["redact_values"] == ("secret-token",)


class TestFetchRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_status_retries_then_succeeds(self, _name: str, status_code: int) -> None:
        bad = MagicMock()
        bad.status_code = status_code
        good = MagicMock()
        good.status_code = 200
        good.ok = True

        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(fastly._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = fastly._fetch(session, f"{FASTLY_BASE_URL}/service", {}, MagicMock())

        assert result is good
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
            ("chunked", requests.exceptions.ChunkedEncodingError("Connection broken")),
        ]
    )
    def test_transient_exceptions_retried(self, _name: str, exc: Exception) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True

        session = MagicMock()
        session.get.side_effect = [exc, good]

        with patch.object(fastly._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = fastly._fetch(session, f"{FASTLY_BASE_URL}/service", {}, MagicMock())

        assert result is good
        assert session.get.call_count == 2

    def test_retryable_reraised_after_exhausting_attempts(self) -> None:
        bad = MagicMock()
        bad.status_code = 503
        session = MagicMock()
        session.get.return_value = bad

        with patch.object(fastly._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(FastlyRetryableError):
                fastly._fetch(session, f"{FASTLY_BASE_URL}/service", {}, MagicMock())

        assert session.get.call_count == 5


def _collect(endpoint: str, manager: _FakeResumableManager, pages: dict[str, Any]) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
        payload = pages[url]
        if isinstance(payload, tuple):
            body, next_url = payload
            return _fake_response(body, next_url)
        return _fake_response(payload)

    rows: list[dict] = []
    with (
        patch.object(fastly, "_fetch", side_effect=fake_fetch),
        patch.object(fastly, "make_tracked_session", return_value=MagicMock()),
    ):
        for batch in get_rows(
            api_key="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
    return rows


class TestGetRowsObject:
    def test_single_object_is_wrapped_in_a_list(self) -> None:
        pages = {f"{FASTLY_BASE_URL}/current_user": {"id": "U1", "login": "a@b.com"}}
        rows = _collect("current_user", _FakeResumableManager(), pages)
        assert rows == [{"id": "U1", "login": "a@b.com"}]


class TestGetRowsServiceList:
    def test_paginates_and_saves_state_after_each_page(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], f"{FASTLY_BASE_URL}/service?page=2"),
            f"{FASTLY_BASE_URL}/service?page=2": ([{"id": "S2"}], None),
        }
        manager = _FakeResumableManager()
        rows = _collect("services", manager, pages)

        assert rows == [{"id": "S1"}, {"id": "S2"}]
        # State is saved once, after yielding page 1 (which has a next page), pointing at page 2.
        assert [s.next_url for s in manager.saved] == [f"{FASTLY_BASE_URL}/service?page=2"]

    def test_resumes_from_saved_next_url(self) -> None:
        pages = {f"{FASTLY_BASE_URL}/service?page=2": ([{"id": "S2"}], None)}
        manager = _FakeResumableManager(FastlyResumeConfig(next_url=f"{FASTLY_BASE_URL}/service?page=2"))
        rows = _collect("services", manager, pages)
        assert rows == [{"id": "S2"}]


class TestGetRowsVersionListFanOut:
    def test_fans_out_over_services(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}, {"id": "S2"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [{"service_id": "S1", "number": 1}],
            f"{FASTLY_BASE_URL}/service/S2/version": [{"service_id": "S2", "number": 2}],
        }
        manager = _FakeResumableManager()
        rows = _collect("service_versions", manager, pages)

        assert rows == [{"service_id": "S1", "number": 1}, {"service_id": "S2", "number": 2}]
        assert [s.service_id for s in manager.saved] == ["S1", "S2"]

    def test_resumes_from_saved_service_bookmark(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}, {"id": "S2"}], None),
            f"{FASTLY_BASE_URL}/service/S2/version": [{"service_id": "S2", "number": 2}],
        }
        # Bookmarked at S2 — S1 is already synced, so only S2 is (re-)processed.
        manager = _FakeResumableManager(FastlyResumeConfig(service_id="S2"))
        rows = _collect("service_versions", manager, pages)
        assert rows == [{"service_id": "S2", "number": 2}]


class TestGetRowsVersionResourceFanOut:
    def test_uses_active_version_and_injects_service_id(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [
                {"number": 1, "active": False},
                {"number": 2, "active": True},
            ],
            # Only the active version (2) is read for the resource.
            f"{FASTLY_BASE_URL}/service/S1/version/2/backend": [{"name": "origin", "version": 2}],
        }
        rows = _collect("service_backends", _FakeResumableManager(), pages)
        assert rows == [{"name": "origin", "version": 2, "service_id": "S1"}]

    def test_service_without_versions_is_skipped_but_bookmark_advances(self) -> None:
        # A versionless service yields no rows, but its bookmark must still advance so resume doesn't
        # re-evaluate it on every future run.
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}, {"id": "S2"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [],
            f"{FASTLY_BASE_URL}/service/S2/version": [{"number": 1, "active": True}],
            f"{FASTLY_BASE_URL}/service/S2/version/1/backend": [{"name": "origin", "version": 1}],
        }
        manager = _FakeResumableManager()
        rows = _collect("service_backends", manager, pages)

        assert rows == [{"name": "origin", "version": 1, "service_id": "S2"}]
        assert [s.service_id for s in manager.saved] == ["S1", "S2"]


class TestFastlySourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_primary_keys_match_settings(self, endpoint: str) -> None:
        response = fastly_source(
            api_key="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == FASTLY_ENDPOINTS[endpoint].primary_keys

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_partitions_on_stable_created_at(self, endpoint: str) -> None:
        response = fastly_source(
            api_key="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
