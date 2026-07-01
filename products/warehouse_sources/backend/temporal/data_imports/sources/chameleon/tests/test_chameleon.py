from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon import chameleon
from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.chameleon import (
    ChameleonResumeConfig,
    _build_url,
    chameleon_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.settings import CHAMELEON_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: ChameleonResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ChameleonResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ChameleonResumeConfig | None:
        return self._state

    def save_state(self, data: ChameleonResumeConfig) -> None:
        self.saved.append(data)


def _response_with_status(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


def _collect(
    manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], endpoint: str = "responses"
) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(chameleon, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for batch in get_rows(
        account_secret="secret",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(batch)
    return rows


class TestBuildUrl:
    def test_no_params_returns_base(self) -> None:
        assert (
            _build_url("https://api.chameleon.io/v3/edit/segments", {}) == "https://api.chameleon.io/v3/edit/segments"
        )

    def test_encodes_params(self) -> None:
        url = _build_url("https://api.chameleon.io/v3/analyze/responses", {"id": "S1", "limit": 500})
        assert url == "https://api.chameleon.io/v3/analyze/responses?id=S1&limit=500"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Chameleon account secret"),
            ("forbidden", 403, False, "Invalid Chameleon account secret"),
            ("rate_limited", 429, False, "status 429"),
            ("server_error", 500, False, "status 500"),
        ]
    )
    def test_status_maps_to_result(
        self, _name: str, status_code: int, expected_ok: bool, expected_fragment: str | None
    ) -> None:
        with patch.object(chameleon, "make_tracked_session") as make_session:
            session = MagicMock()
            session.get.return_value = MagicMock(status_code=status_code)
            make_session.return_value = session
            ok, error = validate_credentials("secret")
            assert ok is expected_ok
            if expected_fragment is None:
                assert error is None
            else:
                assert error is not None and expected_fragment in error

    def test_network_error_is_inconclusive(self) -> None:
        with patch.object(chameleon, "make_tracked_session") as make_session:
            session = MagicMock()
            session.get.side_effect = requests.ConnectionError("boom")
            make_session.return_value = session
            ok, error = validate_credentials("secret")
            assert ok is False
            assert error is not None and "Could not reach Chameleon" in error


class TestStandardEndpointPagination:
    def test_follows_before_cursor_until_exhausted(self, monkeypatch: Any) -> None:
        base = "https://api.chameleon.io/v3/edit/segments?limit=500"
        page2 = "https://api.chameleon.io/v3/edit/segments?limit=500&before=S2"
        pages = {
            base: {"segments": [{"id": "S1"}, {"id": "S2"}], "cursor": {"limit": 500, "before": "S2"}},
            page2: {"segments": [{"id": "S3"}], "cursor": {"limit": 500, "before": "S3"}},
            "https://api.chameleon.io/v3/edit/segments?limit=500&before=S3": {"segments": [], "cursor": {}},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "segments")
        assert [r["id"] for r in rows] == ["S1", "S2", "S3"]

    def test_stops_when_cursor_missing(self, monkeypatch: Any) -> None:
        base = "https://api.chameleon.io/v3/edit/tours?limit=500"
        pages = {base: {"tours": [{"id": "T1"}], "cursor": {}}}
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "tours")
        assert [r["id"] for r in rows] == ["T1"]

    def test_saves_resume_state_after_each_page_with_more_to_come(self, monkeypatch: Any) -> None:
        base = "https://api.chameleon.io/v3/edit/segments?limit=500"
        page2 = "https://api.chameleon.io/v3/edit/segments?limit=500&before=S2"
        pages = {
            base: {"segments": [{"id": "S1"}, {"id": "S2"}], "cursor": {"before": "S2"}},
            page2: {"segments": [{"id": "S3"}], "cursor": {}},
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, pages, "segments")
        # Only the first page has a `next_before`, so exactly one checkpoint is saved, pointing at it.
        assert manager.saved == [ChameleonResumeConfig(before="S2")]

    def test_resumes_from_saved_before(self, monkeypatch: Any) -> None:
        # When state exists, the first request must start from the saved cursor, not page one.
        resume_url = "https://api.chameleon.io/v3/edit/segments?limit=500&before=S2"
        pages = {resume_url: {"segments": [{"id": "S3"}], "cursor": {}}}
        manager = _FakeResumableManager(ChameleonResumeConfig(before="S2"))
        rows = _collect(manager, monkeypatch, pages, "segments")
        assert [r["id"] for r in rows] == ["S3"]


class TestResponsesFanOut:
    def test_fans_out_over_surveys_and_stamps_survey_id(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.chameleon.io/v3/edit/surveys?limit=500": {
                "surveys": [{"id": "SV1"}, {"id": "SV2"}],
                "cursor": {},
            },
            "https://api.chameleon.io/v3/analyze/responses?id=SV1&limit=500": {
                "responses": [{"id": "R1"}, {"id": "R2"}],
                "cursor": {},
            },
            "https://api.chameleon.io/v3/analyze/responses?id=SV2&limit=500": {
                "responses": [{"id": "R3"}],
                "cursor": {},
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [
            {"id": "R1", "survey_id": "SV1"},
            {"id": "R2", "survey_id": "SV1"},
            {"id": "R3", "survey_id": "SV2"},
        ]

    def test_paginates_within_a_survey(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.chameleon.io/v3/edit/surveys?limit=500": {"surveys": [{"id": "SV1"}], "cursor": {}},
            "https://api.chameleon.io/v3/analyze/responses?id=SV1&limit=500": {
                "responses": [{"id": "R1"}],
                "cursor": {"before": "R1"},
            },
            "https://api.chameleon.io/v3/analyze/responses?id=SV1&limit=500&before=R1": {
                "responses": [{"id": "R2"}],
                "cursor": {},
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert [r["id"] for r in rows] == ["R1", "R2"]

    def test_survey_deleted_mid_fan_out_is_skipped(self, monkeypatch: Any) -> None:
        not_found = requests.HTTPError(response=_response_with_status(404))
        pages = {
            "https://api.chameleon.io/v3/edit/surveys?limit=500": {
                "surveys": [{"id": "SV1"}, {"id": "GONE"}, {"id": "SV2"}],
                "cursor": {},
            },
            "https://api.chameleon.io/v3/analyze/responses?id=SV1&limit=500": {
                "responses": [{"id": "R1"}],
                "cursor": {},
            },
            "https://api.chameleon.io/v3/analyze/responses?id=GONE&limit=500": not_found,
            "https://api.chameleon.io/v3/analyze/responses?id=SV2&limit=500": {
                "responses": [{"id": "R2"}],
                "cursor": {},
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert [r["id"] for r in rows] == ["R1", "R2"]

    def test_non_404_http_error_propagates(self, monkeypatch: Any) -> None:
        server_error = requests.HTTPError(response=_response_with_status(500))
        pages = {
            "https://api.chameleon.io/v3/edit/surveys?limit=500": {"surveys": [{"id": "SV1"}], "cursor": {}},
            "https://api.chameleon.io/v3/analyze/responses?id=SV1&limit=500": server_error,
        }
        with pytest.raises(requests.HTTPError):
            _collect(_FakeResumableManager(), monkeypatch, pages)

    def test_resume_from_deleted_survey_restarts_from_first(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.chameleon.io/v3/edit/surveys?limit=500": {"surveys": [{"id": "SV1"}], "cursor": {}},
            "https://api.chameleon.io/v3/analyze/responses?id=SV1&limit=500": {
                "responses": [{"id": "R1"}],
                "cursor": {},
            },
        }
        manager = _FakeResumableManager(ChameleonResumeConfig(before=None, survey_id="DELETED"))
        rows = _collect(manager, monkeypatch, pages)
        assert [r["id"] for r in rows] == ["R1"]


class TestChameleonSourceResponse:
    @parameterized.expand(list(CHAMELEON_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        response = chameleon_source(
            account_secret="secret",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Chameleon returns newest-first; the watermark/ordering contract must reflect that.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
