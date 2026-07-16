import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from freezegun import freeze_time
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.instana import instana as inst
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.instana import (
    InstanaResumeConfig,
    _to_epoch_ms,
    instana_source,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.settings import (
    EVENTS_DEFAULT_LOOKBACK_DAYS,
    EVENTS_WINDOW_CHUNK_MS,
    PAGE_SIZE,
)

BASE_URL = "https://unit-tenant.instana.io"


def _patch_host_safe():
    return mock.patch.object(inst, "_is_host_safe", return_value=(True, None))


def _make_response(status_code: int, payload: Any = None, ok: bool | None = None) -> Any:
    """Build a streaming-response mock: `_read_capped_body` reads it via `iter_content`."""
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = ok if ok is not None else status_code < 400
    body = b"" if payload is None else json.dumps(payload).encode()
    resp.iter_content.return_value = iter([body]) if body else iter([])
    resp.text = body.decode()
    return resp


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://unit-tenant.instana.io", "https://unit-tenant.instana.io"),
            ("unit-tenant.instana.io", "https://unit-tenant.instana.io"),
            ("  https://unit-tenant.instana.io/  ", "https://unit-tenant.instana.io"),
            # http is upgraded so the token never travels in plaintext.
            ("http://selfhosted.example.com", "https://selfhosted.example.com"),
            # Paths/queries are dropped so endpoint paths always join against the bare host.
            ("https://unit-tenant.instana.io/some/path?q=1", "https://unit-tenant.instana.io"),
            ("https://selfhosted.example.com:8443", "https://selfhosted.example.com:8443"),
        ],
    )
    def test_normalizes(self, raw: str, expected: str) -> None:
        assert normalize_base_url(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "https://",
            "ftp://unit-tenant.instana.io",
            # Embedded credentials could smuggle the request elsewhere.
            "https://user:pass@evil.example.com",
        ],
    )
    def test_rejects_invalid(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_base_url(raw)


class TestToEpochMs:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1767225600000, 1767225600000),
            (1767225600000.0, 1767225600000),
            ("1767225600000", 1767225600000),
            (datetime(2026, 1, 1, tzinfo=UTC), 1767225600000),
            (datetime(2026, 1, 1), 1767225600000),  # naive treated as UTC
            (date(2026, 1, 1), 1767225600000),
            ("not-a-number", None),
            (None, None),
            (True, None),
        ],
    )
    def test_coercion(self, value: Any, expected: int | None) -> None:
        assert _to_epoch_ms(value) == expected


def _run_get_rows(
    endpoint: str,
    pages: list[Any],
    can_resume: bool = False,
    resume_state: InstanaResumeConfig | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> tuple[list[Any], list[InstanaResumeConfig], list[str]]:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    saved: list[InstanaResumeConfig] = []
    manager.save_state.side_effect = saved.append

    fetched_urls: list[str] = []

    def fake_get(url: str, timeout: Any = None, stream: bool = False) -> Any:
        fetched_urls.append(url)
        payload = pages[min(len(fetched_urls), len(pages)) - 1]
        return _make_response(200, payload)

    with _patch_host_safe(), mock.patch.object(inst, "make_tracked_session") as mock_session:
        mock_session.return_value.get.side_effect = fake_get
        rows = list(
            inst.get_rows(
                base_url=BASE_URL,
                api_token="token",
                endpoint=endpoint,
                team_id=1,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
        )
    return rows, saved, fetched_urls


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


@freeze_time("2026-01-10T00:00:00Z")
class TestEventRows:
    NOW_MS = 1768003200000

    def test_incremental_run_chunks_from_watermark(self) -> None:
        watermark = self.NOW_MS - int(1.5 * EVENTS_WINDOW_CHUNK_MS)
        pages = [[{"eventId": "a", "start": watermark + 1}]]
        rows, saved, fetched = _run_get_rows(
            "events",
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert len(fetched) == 2
        first, second = _query(fetched[0]), _query(fetched[1])
        assert first["from"] == [str(watermark)]
        assert first["to"] == [str(watermark + EVENTS_WINDOW_CHUNK_MS)]
        assert second["from"] == [str(watermark + EVENTS_WINDOW_CHUNK_MS)]
        assert second["to"] == [str(self.NOW_MS)]
        # Both chunks yielded rows.
        assert len(rows) == 2
        # State saved only between chunks (after the yield), never after the final chunk.
        assert [s.events_window_from for s in saved] == [watermark + EVENTS_WINDOW_CHUNK_MS]

    def test_first_sync_reaches_back_the_default_lookback(self) -> None:
        rows, _saved, fetched = _run_get_rows("events", [[]])

        expected_from = self.NOW_MS - EVENTS_DEFAULT_LOOKBACK_DAYS * 24 * 60 * 60 * 1000
        assert _query(fetched[0])["from"] == [str(expected_from)]
        assert _query(fetched[-1])["to"] == [str(self.NOW_MS)]
        assert len(fetched) == EVENTS_DEFAULT_LOOKBACK_DAYS
        # Empty windows keep advancing without yielding.
        assert rows == []

    def test_resume_starts_at_saved_window(self) -> None:
        resume_from = self.NOW_MS - EVENTS_WINDOW_CHUNK_MS // 2
        _rows, _saved, fetched = _run_get_rows(
            "events",
            [[]],
            can_resume=True,
            resume_state=InstanaResumeConfig(events_window_from=resume_from),
        )

        assert len(fetched) == 1
        assert _query(fetched[0])["from"] == [str(resume_from)]

    def test_future_watermark_is_clamped_and_makes_no_requests(self) -> None:
        rows, saved, fetched = _run_get_rows(
            "events",
            [[]],
            should_use_incremental_field=True,
            db_incremental_field_last_value=self.NOW_MS + 10_000,
        )

        assert fetched == []
        assert rows == []
        assert saved == []


class TestPagedRows:
    def _page(self, count: int, page: int, total_hits: int) -> dict[str, Any]:
        return {"items": [{"id": f"p{page}-{i}"} for i in range(count)], "page": page, "totalHits": total_hits}

    def test_first_request_omits_page_and_follows_server_page_number(self) -> None:
        pages = [
            self._page(PAGE_SIZE, page=1, total_hits=PAGE_SIZE + 1),
            self._page(1, page=2, total_hits=PAGE_SIZE + 1),
        ]
        rows, saved, fetched = _run_get_rows("applications", pages)

        assert "page" not in _query(fetched[0])
        assert _query(fetched[0])["pageSize"] == [str(PAGE_SIZE)]
        assert _query(fetched[1])["page"] == ["2"]
        assert [s.next_page for s in saved] == [2]
        assert len(rows) == 2

    def test_zero_indexed_server_does_not_skip_a_page(self) -> None:
        # The spec doesn't document the first page index; the walk must follow the index base the
        # server reports back rather than assuming 1-based.
        pages = [
            self._page(PAGE_SIZE, page=0, total_hits=PAGE_SIZE + 1),
            self._page(1, page=1, total_hits=PAGE_SIZE + 1),
        ]
        _rows, _saved, fetched = _run_get_rows("applications", pages)

        assert _query(fetched[1])["page"] == ["1"]

    def test_short_page_terminates(self) -> None:
        pages = [self._page(3, page=1, total_hits=3)]
        rows, saved, fetched = _run_get_rows("services", pages)

        assert len(fetched) == 1
        assert saved == []
        assert len(rows[0]) == 3

    def test_total_hits_terminates_a_full_final_page(self) -> None:
        pages = [self._page(PAGE_SIZE, page=1, total_hits=PAGE_SIZE)]
        _rows, saved, fetched = _run_get_rows("endpoints", pages)

        assert len(fetched) == 1
        assert saved == []

    def test_resume_starts_at_saved_page(self) -> None:
        pages = [self._page(2, page=5, total_hits=1000)]
        _rows, _saved, fetched = _run_get_rows(
            "applications", pages, can_resume=True, resume_state=InstanaResumeConfig(next_page=5)
        )

        assert _query(fetched[0])["page"] == ["5"]


class TestListRows:
    def test_bare_list_body_is_yielded(self) -> None:
        pages: list[Any] = [[{"id": "w1", "name": "site"}]]
        rows, saved, fetched = _run_get_rows("websites", pages)

        assert len(fetched) == 1
        assert rows == [[{"id": "w1", "name": "site"}]]
        assert saved == []

    def test_snapshots_items_are_extracted_with_window_params(self) -> None:
        pages: list[Any] = [{"items": [{"snapshotId": "s1", "plugin": "host"}]}]
        rows, _saved, fetched = _run_get_rows("infrastructure_snapshots", pages)

        query = _query(fetched[0])
        assert "windowSize" in query
        assert "size" in query
        assert rows == [[{"snapshotId": "s1", "plugin": "host"}]]


class TestErrorBodyLogging:
    def test_large_error_body_is_bounded_in_log(self) -> None:
        # A customer-controlled host can return a huge 4xx body; the log must carry only a bounded
        # preview plus the byte length, never interpolate the whole body (log-flooding guard).
        oversized = b"x" * (inst.ERROR_BODY_LOG_PREVIEW_BYTES + 5000)
        resp = mock.MagicMock()
        resp.status_code = 400
        resp.ok = False
        resp.iter_content.return_value = iter([oversized])
        resp.raise_for_status.side_effect = requests.HTTPError("400", response=resp)

        session = mock.MagicMock()
        session.get.return_value = resp
        logger = mock.MagicMock()

        with pytest.raises(requests.HTTPError):
            inst._fetch(session, f"{BASE_URL}/api/events", logger)

        logged = logger.error.call_args[0][0]
        assert f"body_bytes={len(oversized)}" in logged
        # Only the preview is interpolated, not the full body.
        assert logged.count("x") == inst.ERROR_BODY_LOG_PREVIEW_BYTES


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, (True, 200)),
            (401, (False, 401)),
            (403, (False, 403)),
            (500, (False, 500)),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: tuple[bool, int]) -> None:
        response = mock.MagicMock()
        response.status_code = status_code

        with _patch_host_safe(), mock.patch.object(inst, "make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = response
            assert validate_credentials(BASE_URL, "token", team_id=1) == expected

    def test_transport_error_returns_none_status(self) -> None:
        with _patch_host_safe(), mock.patch.object(inst, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
            assert validate_credentials(BASE_URL, "token", team_id=1) == (False, None)

    def test_blocked_host_raises(self) -> None:
        with mock.patch.object(inst, "_is_host_safe", return_value=(False, "blocked")):
            with pytest.raises(inst.InstanaHostNotAllowedError):
                validate_credentials(BASE_URL, "token", team_id=1)


class TestGetRowsHostCheck:
    def test_blocked_host_fails_the_sync(self) -> None:
        with mock.patch.object(inst, "_is_host_safe", return_value=(False, "blocked")):
            with pytest.raises(inst.InstanaHostNotAllowedError):
                list(
                    inst.get_rows(
                        base_url=BASE_URL,
                        api_token="token",
                        endpoint="websites",
                        team_id=1,
                        logger=mock.MagicMock(),
                        resumable_source_manager=mock.MagicMock(),
                    )
                )


class TestInstanaSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expected_pk"),
        [
            ("events", "eventId"),
            ("applications", "id"),
            ("infrastructure_snapshots", "snapshotId"),
        ],
    )
    def test_source_response_shape(self, endpoint: str, expected_pk: str) -> None:
        response = instana_source(
            base_url=BASE_URL,
            api_token="token",
            endpoint=endpoint,
            team_id=1,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
        )

        assert response.name == endpoint
        assert response.primary_keys == [expected_pk]
        assert response.sort_mode == "asc"
        # Instana timestamps are epoch-ms integers, so tables are unpartitioned.
        assert response.partition_mode is None
