from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant import firehydrant
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.firehydrant import (
    PAGE_SIZE,
    FireHydrantResumeConfig,
    _build_url,
    _extract_items,
    base_url_for_region,
    firehydrant_source,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.settings import (
    ENDPOINTS,
    FIREHYDRANT_ENDPOINTS,
)


class _FakeResumableManager:
    def __init__(self, state: FireHydrantResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[FireHydrantResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> FireHydrantResumeConfig | None:
        return self._state

    def save_state(self, data: FireHydrantResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager,
    monkeypatch: Any,
    pages: dict[str, Any],
    endpoint: str,
    region: str | None = None,
) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(firehydrant, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for batch in get_rows(
        api_key="fhb_test",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        region=region,
    ):
        rows.extend(batch)
    return rows


class TestBuildUrl:
    @parameterized.expand(
        [
            # region -> host: EU accounts are pinned to the data-residency host, so an unknown or
            # missing region must fall back to the US default rather than a wrong host.
            ("default_us", None, "https://api.firehydrant.io"),
            ("us", "us", "https://api.firehydrant.io"),
            ("eu", "eu", "https://api.eu.firehydrant.io"),
            ("unknown_falls_back", "apac", "https://api.firehydrant.io"),
        ]
    )
    def test_includes_page_and_per_page(self, _name: str, region: str | None, base_host: str) -> None:
        url = _build_url(base_url_for_region(region), "/v1/incidents", 3)
        assert url == f"{base_host}/v1/incidents?page=3&per_page={PAGE_SIZE}"


class TestExtractItems:
    @parameterized.expand(
        [
            ("wrapped_data", {"data": [{"id": "1"}], "pagination": {}}, [{"id": "1"}]),
            ("bare_list", [{"id": "1"}, {"id": "2"}], [{"id": "1"}, {"id": "2"}]),
            ("missing_data_key", {"pagination": {}}, []),
            ("data_not_a_list", {"data": {"id": "1"}}, []),
        ]
    )
    def test_extract_items(self, _name: str, payload: Any, expected: list[dict]) -> None:
        assert _extract_items(payload) == expected


class TestGetRows:
    def test_follows_page_pagination(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.firehydrant.io/v1/incidents?page=1&per_page=100": {
                "data": [{"id": "i1"}, {"id": "i2"}],
                "pagination": {"page": 1, "next": 2, "last": 2},
            },
            "https://api.firehydrant.io/v1/incidents?page=2&per_page=100": {
                "data": [{"id": "i3"}],
                "pagination": {"page": 2, "next": None, "last": 2},
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "incidents")
        assert rows == [{"id": "i1"}, {"id": "i2"}, {"id": "i3"}]

    def test_single_unpaginated_response_terminates(self, monkeypatch: Any) -> None:
        # signals_on_call and similar endpoints may return a single page with no `next`.
        pages = {
            "https://api.firehydrant.io/v1/signals_on_call?page=1&per_page=100": {
                "data": [{"id": "s1"}],
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "signals_on_call")
        assert rows == [{"id": "s1"}]

    def test_state_saved_after_each_page_with_next(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            "https://api.firehydrant.io/v1/services?page=1&per_page=100": {
                "data": [{"id": "a"}],
                "pagination": {"next": 2},
            },
            "https://api.firehydrant.io/v1/services?page=2&per_page=100": {
                "data": [{"id": "b"}],
                "pagination": {"next": 3},
            },
            "https://api.firehydrant.io/v1/services?page=3&per_page=100": {
                "data": [{"id": "c"}],
                "pagination": {"next": None},
            },
        }
        _collect(manager, monkeypatch, pages, "services")
        # State saved only when a next page exists — not after the final page.
        assert [s.next_page for s in manager.saved] == [2, 3]

    def test_region_routes_requests_to_eu_host(self, monkeypatch: Any) -> None:
        # EU accounts only answer on the data-residency host; if get_rows ignored region it would hit
        # the US host and every EU sync would fail.
        pages = {
            "https://api.eu.firehydrant.io/v1/incidents?page=1&per_page=100": {
                "data": [{"id": "eu1"}],
                "pagination": {"next": None},
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "incidents", region="eu")
        assert rows == [{"id": "eu1"}]

    def test_resume_from_saved_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(FireHydrantResumeConfig(next_page=2))
        pages = {
            "https://api.firehydrant.io/v1/services?page=2&per_page=100": {
                "data": [{"id": "b"}],
                "pagination": {"next": None},
            },
        }
        rows = _collect(manager, monkeypatch, pages, "services")
        # Resumes at page 2 (page 1 is never requested), proving the saved cursor is honored.
        assert rows == [{"id": "b"}]


class TestFireHydrantSource:
    @parameterized.expand(list(ENDPOINTS))
    def test_source_response_matches_endpoint_config(self, endpoint: str) -> None:
        config = FIREHYDRANT_ENDPOINTS[endpoint]
        response = firehydrant_source(
            api_key="fhb_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_partition_keys_are_stable_creation_fields(self) -> None:
        # A partition key that changes (updated_at/lastSeen) rewrites partitions every sync.
        for config in FIREHYDRANT_ENDPOINTS.values():
            if config.partition_key:
                assert config.partition_key == "created_at"

    @parameterized.expand(
        [
            ("priorities", ["slug"]),
            ("severities", ["slug"]),
            ("incident_tags", ["name"]),
            ("custom_field_definitions", ["field_id"]),
            ("incidents", ["id"]),
        ]
    )
    def test_endpoint_specific_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        assert FIREHYDRANT_ENDPOINTS[endpoint].primary_keys == expected_keys


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            # Only a 200 proves the key is real and usable — a 403 means it reached FireHydrant but
            # lacks permissions, so we reject it rather than register an unverified credential.
            ("forbidden_rejected", 403, False),
            ("unauthorized", 401, False),
            ("unexpected", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        response = requests.Response()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response

        with patch.object(firehydrant, "make_tracked_session", lambda *a, **k: session):
            valid, _error = firehydrant.validate_credentials("fhb_test")
        assert valid is expected_valid

    def test_network_error_is_invalid(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(firehydrant, "make_tracked_session", lambda *a, **k: session)

        valid, error = firehydrant.validate_credentials("fhb_test")
        assert valid is False
        assert error is not None

    @parameterized.expand(
        [
            ("default_us", None, "https://api.firehydrant.io/v1/ping"),
            ("eu", "eu", "https://api.eu.firehydrant.io/v1/ping"),
        ]
    )
    def test_probes_region_host(self, _name: str, region: str | None, expected_url: str) -> None:
        # The key is only valid against its own region's host, so validation must probe there.
        response = requests.Response()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response

        with patch.object(firehydrant, "make_tracked_session", lambda *a, **k: session):
            firehydrant.validate_credentials("fhb_test", region=region)
        assert session.get.call_args.args[0] == expected_url


class TestCredentialRedaction:
    """The token must be registered for redaction so it can't leak into logged URLs or HTTP samples."""

    def test_validate_credentials_redacts_api_key(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_session(*args: Any, **kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            response = requests.Response()
            response.status_code = 200
            session = MagicMock()
            session.get.return_value = response
            return session

        monkeypatch.setattr(firehydrant, "make_tracked_session", fake_session)
        firehydrant.validate_credentials("fhb_secret")
        assert captured.get("redact_values") == ("fhb_secret",)

    def test_get_rows_redacts_api_key(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_session(*args: Any, **kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(firehydrant, "make_tracked_session", fake_session)
        monkeypatch.setattr(firehydrant, "_fetch_page", lambda *a, **k: {"data": [], "pagination": {}})

        list(
            get_rows(
                api_key="fhb_secret",
                endpoint="incidents",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )
        assert captured.get("redact_values") == ("fhb_secret",)


class TestFetchPageRetries:
    def _session_returning(self, status_code: int, headers: dict[str, str] | None = None) -> MagicMock:
        response = requests.Response()
        response.status_code = status_code
        response.headers.update(headers or {})
        session = MagicMock()
        session.get.return_value = response
        return session

    # Tested through `_fetch_page_once` (the undecorated core) so tenacity's waits don't run.
    _URL = "https://api.firehydrant.io/v1/incidents?page=1&per_page=100"

    def test_rate_limit_honors_retry_after_then_raises_retryable(self, monkeypatch: Any) -> None:
        slept: list[int] = []
        monkeypatch.setattr(firehydrant.time, "sleep", lambda s: slept.append(s))
        session = self._session_returning(429, {"Retry-After": "7"})

        with pytest.raises(firehydrant.FireHydrantRetryableError):
            firehydrant._fetch_page_once(session, self._URL, {}, MagicMock())

        assert slept == [7]

    def test_server_error_is_retryable(self) -> None:
        session = self._session_returning(503)
        with pytest.raises(firehydrant.FireHydrantRetryableError):
            firehydrant._fetch_page_once(session, self._URL, {}, MagicMock())
