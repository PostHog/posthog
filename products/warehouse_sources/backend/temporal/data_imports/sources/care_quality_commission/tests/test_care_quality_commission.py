from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission import (
    care_quality_commission as cqc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission.care_quality_commission import (
    CQC_BASE_URL,
    CQCResumeConfig,
    _build_url,
    _fetch,
    _get_headers,
    care_quality_commission_source,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission.settings import (
    CQC_ENDPOINTS,
)


class _FakeResumableManager:
    def __init__(self, state: CQCResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[CQCResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> CQCResumeConfig | None:
        return self._state

    def save_state(self, data: CQCResumeConfig) -> None:
        self.saved.append(data)


class TestGetHeaders:
    def test_uses_subscription_key_header(self) -> None:
        headers = _get_headers("my-key")
        # CQC authenticates with the Azure API Management subscription-key header, not a bearer token.
        assert headers["Ocp-Apim-Subscription-Key"] == "my-key"
        assert headers["Accept"] == "application/json"


class TestBuildUrl:
    def test_includes_partner_code_and_pagination(self) -> None:
        url = _build_url("/providers", {"page": 1, "perPage": 500, "partnerCode": "PC"})
        assert url == f"{CQC_BASE_URL}/providers?page=1&perPage=500&partnerCode=PC"

    def test_omits_none_and_empty_params(self) -> None:
        # A missing partner code must not leak through as `partnerCode=None` / `partnerCode=`.
        url = _build_url("/providers", {"page": 1, "partnerCode": None, "extra": ""})
        assert url == f"{CQC_BASE_URL}/providers?page=1"

    def test_no_params(self) -> None:
        assert _build_url("/providers/1-123", {}) == f"{CQC_BASE_URL}/providers/1-123"


class TestFetch:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_retryable_error(self, _name: str, status: int) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        # Skip tenacity's backoff sleeps so the 5 retries don't slow the test.
        _fetch.retry.sleep = lambda _s: None  # type: ignore[attr-defined]
        with pytest.raises(cqc.CQCRetryableError):
            _fetch(session, "http://x", {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_raises_for_status(self, _name: str, status: int) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} error", response=response)
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            _fetch(session, "http://x", {}, MagicMock())

    def test_success_returns_json(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = {"providers": []}
        session = MagicMock()
        session.get.return_value = response
        assert _fetch(session, "http://x", {}, MagicMock()) == {"providers": []}


def _collect(
    manager: _FakeResumableManager,
    monkeypatch: Any,
    pages: dict[str, Any],
    endpoint: str = "providers",
    partner_code: str | None = "PC",
) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(cqc, "_fetch", fake_fetch)
    monkeypatch.setattr(cqc, "make_tracked_session", lambda **kwargs: MagicMock())

    rows: list[dict] = []
    for table in get_rows(
        api_key="key",
        partner_code=partner_code,
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(table.to_pylist())
    return rows


class TestGetRowsFanOut:
    def test_fans_out_list_to_detail_records(self, monkeypatch: Any) -> None:
        pages = {
            f"{CQC_BASE_URL}/providers?page=1&perPage=500&partnerCode=PC": {
                "providers": [{"providerId": "1-A"}, {"providerId": "1-B"}],
                "totalPages": 1,
            },
            f"{CQC_BASE_URL}/providers/1-A?partnerCode=PC": {"providerId": "1-A", "name": "Alpha"},
            f"{CQC_BASE_URL}/providers/1-B?partnerCode=PC": {"providerId": "1-B", "name": "Bravo"},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [
            {"providerId": "1-A", "name": "Alpha"},
            {"providerId": "1-B", "name": "Bravo"},
        ]

    def test_locations_endpoint_uses_location_paths(self, monkeypatch: Any) -> None:
        pages = {
            f"{CQC_BASE_URL}/locations?page=1&perPage=500&partnerCode=PC": {
                "locations": [{"locationId": "1-L"}],
                "totalPages": 1,
            },
            f"{CQC_BASE_URL}/locations/1-L?partnerCode=PC": {"locationId": "1-L", "name": "Loc"},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, endpoint="locations")
        assert rows == [{"locationId": "1-L", "name": "Loc"}]

    def test_paginates_across_pages(self, monkeypatch: Any) -> None:
        pages = {
            f"{CQC_BASE_URL}/providers?page=1&perPage=500&partnerCode=PC": {
                "providers": [{"providerId": "1-A"}],
                "totalPages": 2,
            },
            f"{CQC_BASE_URL}/providers/1-A?partnerCode=PC": {"providerId": "1-A"},
            f"{CQC_BASE_URL}/providers?page=2&perPage=500&partnerCode=PC": {
                "providers": [{"providerId": "1-B"}],
                "totalPages": 2,
            },
            f"{CQC_BASE_URL}/providers/1-B?partnerCode=PC": {"providerId": "1-B"},
        }
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, pages)
        assert rows == [{"providerId": "1-A"}, {"providerId": "1-B"}]
        # The bookmark advances to page 2 after page 1 completes so a crash resumes mid-stream.
        assert CQCResumeConfig(page=2) in manager.saved

    def test_paginates_when_total_pages_missing(self, monkeypatch: Any) -> None:
        # The API omits totalPages: don't trust the fallback to terminate after page 1 — keep
        # paging until an empty page is returned.
        pages = {
            f"{CQC_BASE_URL}/providers?page=1&perPage=500&partnerCode=PC": {
                "providers": [{"providerId": "1-A"}],
            },
            f"{CQC_BASE_URL}/providers/1-A?partnerCode=PC": {"providerId": "1-A"},
            f"{CQC_BASE_URL}/providers?page=2&perPage=500&partnerCode=PC": {
                "providers": [{"providerId": "1-B"}],
            },
            f"{CQC_BASE_URL}/providers/1-B?partnerCode=PC": {"providerId": "1-B"},
            f"{CQC_BASE_URL}/providers?page=3&perPage=500&partnerCode=PC": {"providers": []},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"providerId": "1-A"}, {"providerId": "1-B"}]

    def test_empty_page_terminates(self, monkeypatch: Any) -> None:
        pages = {
            f"{CQC_BASE_URL}/providers?page=1&perPage=500&partnerCode=PC": {"providers": [], "totalPages": 5},
        }
        assert _collect(_FakeResumableManager(), monkeypatch, pages) == []

    def test_record_without_id_raises(self, monkeypatch: Any) -> None:
        # A list record missing its id field is an API contract violation — fail fast with a
        # KeyError rather than silently dropping the row.
        pages = {
            f"{CQC_BASE_URL}/providers?page=1&perPage=500&partnerCode=PC": {
                "providers": [{"name": "no id"}],
                "totalPages": 1,
            },
        }
        with pytest.raises(KeyError):
            _collect(_FakeResumableManager(), monkeypatch, pages)

    def test_resume_skips_already_synced_pages(self, monkeypatch: Any) -> None:
        # Saved state says page 2; page 1 must not be fetched again.
        pages = {
            f"{CQC_BASE_URL}/providers?page=2&perPage=500&partnerCode=PC": {
                "providers": [{"providerId": "1-B"}],
                "totalPages": 2,
            },
            f"{CQC_BASE_URL}/providers/1-B?partnerCode=PC": {"providerId": "1-B"},
        }
        manager = _FakeResumableManager(CQCResumeConfig(page=2))
        rows = _collect(manager, monkeypatch, pages)
        assert rows == [{"providerId": "1-B"}]

    def test_omits_partner_code_when_absent(self, monkeypatch: Any) -> None:
        pages = {
            f"{CQC_BASE_URL}/providers?page=1&perPage=500": {
                "providers": [{"providerId": "1-A"}],
                "totalPages": 1,
            },
            f"{CQC_BASE_URL}/providers/1-A": {"providerId": "1-A"},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, partner_code=None)
        assert rows == [{"providerId": "1-A"}]


class TestSourceResponse:
    @parameterized.expand([("providers", ["providerId"]), ("locations", ["locationId"])])
    def test_response_shape(self, endpoint: str, expected_keys: list[str]) -> None:
        response = care_quality_commission_source(
            api_key="key",
            partner_code="PC",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        # Partition on the stable registration date so partitions never rewrite.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [CQC_ENDPOINTS[endpoint].partition_key]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(cqc, "make_tracked_session", lambda **kwargs: session):
            assert cqc.validate_credentials("key", "PC") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(cqc, "make_tracked_session", lambda **kwargs: session):
            assert cqc.validate_credentials("key", "PC") is False
