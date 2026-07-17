from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security import orca_security
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.orca_security import (
    OrcaResumeConfig,
    _build_payload,
    _format_datetime,
    _headers,
    _host,
    _normalize_item,
    get_rows,
    orca_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.settings import (
    ORCA_ENDPOINTS,
    PAGE_SIZE,
)


class FakeManager:
    """Stand-in for ResumableSourceManager that records saved state in memory."""

    def __init__(self, initial: OrcaResumeConfig | None = None):
        self._state = initial
        self.saved: list[OrcaResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> OrcaResumeConfig | None:
        return self._state

    def save_state(self, data: OrcaResumeConfig) -> None:
        self.saved.append(data)


class TestHost:
    @parameterized.expand(
        [
            ("global", "https://api.orcasecurity.io/api"),
            ("us", "https://app.us.orcasecurity.io/api"),
            ("eu", "https://app.eu.orcasecurity.io/api"),
            ("", "https://api.orcasecurity.io/api"),
            ("unknown", "https://api.orcasecurity.io/api"),
        ]
    )
    def test_host_mapping(self, region: str, expected: str) -> None:
        assert _host(region) == expected


class TestHeaders:
    def test_token_header(self) -> None:
        headers = _headers("abc123")
        assert headers["Authorization"] == "Token abc123"
        assert headers["Content-Type"] == "application/json"


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("aware", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "cursor", "cursor"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestBuildPayload:
    def test_full_refresh_has_no_filter_or_order(self) -> None:
        payload = _build_payload(
            ORCA_ENDPOINTS["assets"], start_at_index=0, incremental_field=None, formatted_last_value=None
        )
        assert payload["query"] == {"models": ["Inventory"], "type": "object_set"}
        assert payload["limit"] == PAGE_SIZE
        assert payload["start_at_index"] == 0
        assert "with" not in payload["query"]
        assert "order_by[]" not in payload

    def test_incremental_stream_always_sorts(self) -> None:
        payload = _build_payload(
            ORCA_ENDPOINTS["alerts"], start_at_index=0, incremental_field=None, formatted_last_value=None
        )
        # Even on first sync (no watermark), the incremental stream requests ascending order so the
        # pipeline watermark advances correctly.
        assert payload["order_by[]"] == ["CreatedAt"]
        assert "with" not in payload["query"]

    def test_incremental_filter_applied(self) -> None:
        payload = _build_payload(
            ORCA_ENDPOINTS["alerts"],
            start_at_index=100,
            incremental_field="CreatedAt",
            formatted_last_value="2026-01-01T00:00:00+00:00",
        )
        assert payload["start_at_index"] == 100
        with_clause = payload["query"]["with"]
        assert with_clause["operator"] == "and"
        value = with_clause["values"][0]
        assert value["key"] == "CreatedAt"
        assert value["operator"] == "date_gte"
        assert value["values"] == ["2026-01-01T00:00:00+00:00"]

    def test_incremental_field_override(self) -> None:
        payload = _build_payload(
            ORCA_ENDPOINTS["alerts"],
            start_at_index=0,
            incremental_field="LastSeen",
            formatted_last_value="2026-01-01T00:00:00+00:00",
        )
        assert payload["query"]["with"]["values"][0]["key"] == "LastSeen"


class TestNormalizeItem:
    def test_unwraps_value_fields(self) -> None:
        item = {
            "id": "acc_1_alert_1",
            "type": "Alert",
            "data": {
                "AlertId": {"value": "alert_1"},
                "Category": {"value": "IAM misconfigurations"},
                "Labels": {"value": ["a", "b"]},
            },
        }
        row = _normalize_item(item)
        assert row == {
            "id": "acc_1_alert_1",
            "type": "Alert",
            "AlertId": "alert_1",
            "Category": "IAM misconfigurations",
            "Labels": ["a", "b"],
        }

    def test_keeps_unwrapped_field(self) -> None:
        row = _normalize_item({"id": "x", "data": {"Raw": {"nested": 1}}})
        assert row["Raw"] == {"nested": 1}

    def test_missing_data(self) -> None:
        assert _normalize_item({"id": "x", "type": "Alert"}) == {"id": "x", "type": "Alert"}


class TestGetRows:
    def _page(self, ids: list[str], next_token: int | None) -> dict:
        return {
            "data": [{"id": i, "type": "Alert", "data": {"AlertId": {"value": i}}} for i in ids],
            "next_page_token": next_token,
        }

    def test_paginates_until_short_page(self) -> None:
        manager = FakeManager()
        pages = [
            self._page([str(n) for n in range(PAGE_SIZE)], PAGE_SIZE),
            self._page(["last"], None),
        ]
        with (
            mock.patch.object(orca_security, "make_tracked_session"),
            mock.patch.object(orca_security, "_fetch_page", side_effect=pages),
        ):
            batches = list(
                get_rows("tok", "us", "alerts", mock.MagicMock(), manager)  # type: ignore[arg-type]
            )
        # Two pages yielded, each normalized.
        assert len(batches) == 2
        assert batches[1][0]["id"] == "last"
        # State saved once (after first full page) with the advanced offset.
        assert manager.saved == [OrcaResumeConfig(start_at_index=PAGE_SIZE)]

    def test_stops_on_empty_page(self) -> None:
        manager = FakeManager()
        with (
            mock.patch.object(orca_security, "make_tracked_session"),
            mock.patch.object(orca_security, "_fetch_page", return_value={"data": [], "next_page_token": None}),
        ):
            batches = list(get_rows("tok", "us", "alerts", mock.MagicMock(), manager))  # type: ignore[arg-type]
        assert batches == []
        assert manager.saved == []

    def test_resumes_from_saved_offset(self) -> None:
        manager = FakeManager(initial=OrcaResumeConfig(start_at_index=PAGE_SIZE))
        captured: list[int] = []

        def fake_fetch(session, url, headers, payload, logger):
            captured.append(payload["start_at_index"])
            return {"data": [{"id": "r", "type": "Alert", "data": {}}], "next_page_token": None}

        with (
            mock.patch.object(orca_security, "make_tracked_session"),
            mock.patch.object(orca_security, "_fetch_page", side_effect=fake_fetch),
        ):
            list(get_rows("tok", "us", "alerts", mock.MagicMock(), manager))  # type: ignore[arg-type]

        # First fetch continues from the saved offset rather than 0.
        assert captured[0] == PAGE_SIZE

    def test_incremental_value_only_formatted_when_used(self) -> None:
        manager = FakeManager()
        captured: list[dict] = []

        def fake_fetch(session, url, headers, payload, logger):
            captured.append(payload)
            return {"data": [], "next_page_token": None}

        with (
            mock.patch.object(orca_security, "make_tracked_session"),
            mock.patch.object(orca_security, "_fetch_page", side_effect=fake_fetch),
        ):
            list(
                get_rows(
                    "tok",
                    "us",
                    "alerts",
                    mock.MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
        assert captured[0]["query"]["with"]["values"][0]["values"] == ["2026-01-01T00:00:00+00:00"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
            (401, False),
            (403, False),
        ]
    )
    def test_status_mapping(self, status: int, expected: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status
        response.ok = status == 200
        session = mock.MagicMock()
        session.post.return_value = response
        with mock.patch.object(orca_security, "make_tracked_session", return_value=session):
            ok, _err = validate_credentials("tok", "us")
        assert ok is expected

    def test_network_error_is_failure(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = Exception("boom")
        with mock.patch.object(orca_security, "make_tracked_session", return_value=session):
            ok, err = validate_credentials("tok", "us")
        assert ok is False
        assert err is not None


class TestOrcaSource:
    def test_alerts_is_partitioned_and_ascending(self) -> None:
        response = orca_source("tok", "us", "alerts", mock.MagicMock(), FakeManager())  # type: ignore[arg-type]
        assert response.name == "alerts"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["CreatedAt"]

    def test_full_refresh_stream_has_no_partition(self) -> None:
        response = orca_source("tok", "us", "assets", mock.MagicMock(), FakeManager())  # type: ignore[arg-type]
        assert response.partition_mode is None
        assert response.partition_keys is None
