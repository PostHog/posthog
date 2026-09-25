from datetime import UTC, datetime
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.easypost import easypost
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.easypost import (
    EasypostResumeConfig,
    _format_datetime,
    _parse_datetime,
    easypost_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.settings import ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: EasypostResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[EasypostResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> EasypostResumeConfig | None:
        return self._state

    def save_state(self, data: EasypostResumeConfig) -> None:
        self.saved.append(data)


def _patch_pages(monkeypatch: Any, pages_by_before_id: dict[Any, dict[str, Any]]) -> None:
    def fake_fetch(session: Any, url: str, params: dict[str, Any], logger: Any) -> dict[str, Any]:
        return pages_by_before_id[params.get("before_id")]

    monkeypatch.setattr(easypost, "_fetch_page", fake_fetch)


def _patch_response(monkeypatch: Any, payload: Any) -> list[dict[str, Any]]:
    """Answer every request with `payload`, returning the list of params each request sent."""
    requests: list[dict[str, Any]] = []

    def fake_fetch(session: Any, url: str, params: dict[str, Any], logger: Any) -> Any:
        requests.append({"url": url, **params})
        return payload

    monkeypatch.setattr(easypost, "_fetch_page", fake_fetch)
    return requests


def _collect(manager: _FakeResumableManager, endpoint: str = "shipments", **kwargs: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch in get_rows("k", endpoint, MagicMock(), manager, **kwargs):  # type: ignore[arg-type]
        rows.extend(batch)
    return rows


class TestParseDatetime:
    @parameterized.expand(
        [
            ("z_suffix", "2024-01-15T10:30:00Z", datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)),
            ("offset", "2024-01-15T10:30:00+00:00", datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)),
            ("naive_datetime", datetime(2024, 1, 15, 10, 30, 0), datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)),
            ("none", None, None),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_parse(self, _name: str, value: Any, expected: datetime | None) -> None:
        assert _parse_datetime(value) == expected


class TestFormatDatetime:
    def test_uses_z_suffix(self) -> None:
        result = _format_datetime(datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC))
        assert result == "2024-01-02T12:00:00Z"
        assert "+00:00" not in result


class TestGetRows:
    def test_paginates_via_before_id(self, monkeypatch: Any) -> None:
        _patch_pages(
            monkeypatch,
            {
                None: {"shipments": [{"id": "shp_1"}, {"id": "shp_2"}], "has_more": True},
                "shp_2": {"shipments": [{"id": "shp_3"}], "has_more": False},
            },
        )
        rows = _collect(_FakeResumableManager())
        assert [r["id"] for r in rows] == ["shp_1", "shp_2", "shp_3"]

    def test_stops_when_page_is_empty(self, monkeypatch: Any) -> None:
        _patch_pages(monkeypatch, {None: {"shipments": [], "has_more": True}})
        assert _collect(_FakeResumableManager()) == []

    def test_saves_resume_cursor_for_each_yielded_page(self, monkeypatch: Any) -> None:
        # The saved cursor points at the page just yielded (not the next one), so a crash re-fetches
        # and re-yields it rather than skipping ahead — merge dedupes on the id primary key.
        manager = _FakeResumableManager()
        _patch_pages(
            monkeypatch,
            {
                None: {"shipments": [{"id": "shp_1"}], "has_more": True},
                "shp_1": {"shipments": [{"id": "shp_2"}], "has_more": False},
            },
        )
        _collect(manager)
        assert [s.before_id for s in manager.saved] == [None, "shp_1"]

    def test_resumes_from_saved_before_id(self, monkeypatch: Any) -> None:
        _patch_pages(monkeypatch, {"shp_2": {"shipments": [{"id": "shp_3"}], "has_more": False}})
        rows = _collect(_FakeResumableManager(EasypostResumeConfig(before_id="shp_2")))
        assert [r["id"] for r in rows] == ["shp_3"]

    def test_incremental_stops_at_watermark(self, monkeypatch: Any) -> None:
        # Descending order: once a record at/below the watermark appears, everything after it is older,
        # so pagination must stop client-side even though has_more is True.
        _patch_pages(
            monkeypatch,
            {
                None: {
                    "shipments": [
                        {"id": "shp_3", "created_at": "2024-01-03T00:00:00Z"},
                        {"id": "shp_2", "created_at": "2024-01-02T00:00:00Z"},
                        {"id": "shp_1", "created_at": "2024-01-01T00:00:00Z"},
                    ],
                    "has_more": True,
                },
            },
        )
        rows = _collect(
            _FakeResumableManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert [r["id"] for r in rows] == ["shp_3"]

    def test_incremental_passes_start_datetime_filter(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_fetch(session: Any, url: str, params: dict[str, Any], logger: Any) -> dict[str, Any]:
            captured.update(params)
            return {"shipments": [], "has_more": False}

        monkeypatch.setattr(easypost, "_fetch_page", fake_fetch)
        _collect(
            _FakeResumableManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert captured["start_datetime"] == "2024-01-02T12:00:00Z"
        assert captured["page_size"] == 100

    def test_full_refresh_sends_no_time_filter(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_fetch(session: Any, url: str, params: dict[str, Any], logger: Any) -> dict[str, Any]:
            captured.update(params)
            return {"shipments": [], "has_more": False}

        monkeypatch.setattr(easypost, "_fetch_page", fake_fetch)
        _collect(_FakeResumableManager())
        assert "start_datetime" not in captured
        assert "before_id" not in captured


class TestUnpaginatedEndpoints:
    def test_bare_list_response_is_yielded_whole(self, monkeypatch: Any) -> None:
        # /carrier_accounts answers with a bare JSON array, not the {"<name>": [...]} wrapper every
        # other endpoint uses, so extraction has to branch on the endpoint rather than the payload.
        requests = _patch_response(monkeypatch, [{"id": "ca_1"}, {"id": "ca_2"}])
        rows = _collect(_FakeResumableManager(), endpoint="carrier_accounts")
        assert [r["id"] for r in rows] == ["ca_1", "ca_2"]
        assert requests == [{"url": "https://api.easypost.com/v2/carrier_accounts"}]

    def test_wrapped_response_is_unwrapped(self, monkeypatch: Any) -> None:
        requests = _patch_response(monkeypatch, {"carriers": [{"name": "usps"}]})
        rows = _collect(_FakeResumableManager(), endpoint="carriers")
        assert [r["name"] for r in rows] == ["usps"]
        assert requests == [{"url": "https://api.easypost.com/v2/metadata/carriers"}]

    def test_does_not_paginate_or_save_resume_state(self, monkeypatch: Any) -> None:
        # There is no cursor in the response, so looping on a truthy `has_more` — or resuming from
        # a stale saved cursor — would re-request the same page forever.
        manager = _FakeResumableManager(EasypostResumeConfig(before_id="ca_9"))
        requests = _patch_response(monkeypatch, {"carriers": [{"name": "usps"}], "has_more": True})
        _collect(manager, endpoint="carriers")
        assert len(requests) == 1
        assert "before_id" not in requests[0]
        assert manager.saved == []

    def test_empty_response_yields_nothing(self, monkeypatch: Any) -> None:
        _patch_response(monkeypatch, [])
        assert _collect(_FakeResumableManager(), endpoint="carrier_accounts") == []


class TestEndpointsWithoutServerSideTimeFilter:
    def test_incremental_omits_start_datetime_but_still_stops_at_watermark(self, monkeypatch: Any) -> None:
        # /end_shippers paginates by cursor but documents no start_datetime, so the descending
        # client-side stop is the only thing bounding an incremental run.
        requests = _patch_response(
            monkeypatch,
            {
                "end_shippers": [
                    {"id": "es_2", "created_at": "2024-01-03T00:00:00Z"},
                    {"id": "es_1", "created_at": "2024-01-01T00:00:00Z"},
                ],
                "has_more": True,
            },
        )
        rows = _collect(
            _FakeResumableManager(),
            endpoint="end_shippers",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert [r["id"] for r in rows] == ["es_2"]
        assert len(requests) == 1
        assert "start_datetime" not in requests[0]


class TestValidateCredentials:
    @parameterized.expand(
        [("ok", 200, True), ("unauthorized", 401, False), ("inactive", 403, False), ("server", 500, False)]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        session = MagicMock()
        response = MagicMock()
        response.status_code = status
        session.get.return_value = response
        with patch.object(easypost, "make_tracked_session", lambda *a, **k: session):
            assert validate_credentials("k") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch.object(easypost, "make_tracked_session", lambda *a, **k: session):
            assert validate_credentials("k") is False

    def test_redacts_api_key_in_http_logging(self) -> None:
        # The API key is sent as the Basic auth username; it must be registered for redaction so it
        # cannot leak into HTTP telemetry/sample capture.
        factory = MagicMock(return_value=MagicMock())
        with patch.object(easypost, "make_tracked_session", factory):
            validate_credentials("secret-key")
        factory.assert_called_once_with(redact_values=("secret-key",))


class TestGetRowsRedaction:
    def test_redacts_api_key_in_http_logging(self, monkeypatch: Any) -> None:
        # Same secret-leak guard as validate_credentials, on the sync request path.
        factory = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(easypost, "make_tracked_session", factory)
        _patch_pages(monkeypatch, {None: {"shipments": [], "has_more": False}})
        list(get_rows("secret-key", "shipments", MagicMock(), _FakeResumableManager()))  # type: ignore[arg-type]
        factory.assert_called_once_with(redact_values=("secret-key",))


class TestEasypostSource:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = easypost_source("k", endpoint, MagicMock(), _FakeResumableManager())  # type: ignore[arg-type]
        assert response.name == endpoint
        assert response.primary_keys
        # EasyPost returns newest-first; the watermark logic depends on this being declared.
        assert response.sort_mode == "desc"

    def test_partition_settings_follow_the_partition_key(self) -> None:
        # The lookup tables carry no stable creation timestamp, so an unset partition key has to
        # switch every partition_* field off together — a stray mode or format would partition on
        # a column that isn't there.
        shipments = easypost_source("k", "shipments", MagicMock(), _FakeResumableManager())  # type: ignore[arg-type]
        assert shipments.partition_mode == "datetime"
        assert shipments.partition_keys == ["created_at"]

        carriers = easypost_source("k", "carriers", MagicMock(), _FakeResumableManager())  # type: ignore[arg-type]
        assert carriers.partition_mode is None
        assert carriers.partition_format is None
        assert carriers.partition_keys is None
