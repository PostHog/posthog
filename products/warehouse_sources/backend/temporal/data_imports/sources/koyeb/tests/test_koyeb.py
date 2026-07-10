from datetime import UTC, datetime
from typing import Any

from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb import koyeb
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.koyeb import (
    KoyebResumeConfig,
    _build_params,
    _has_more,
    get_rows,
    koyeb_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.settings import KOYEB_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: KoyebResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[KoyebResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> KoyebResumeConfig | None:
        return self._state

    def save_state(self, data: KoyebResumeConfig) -> None:
        self.saved.append(data)


class TestBuildParams:
    def test_incremental_endpoint_sends_server_side_time_filter(self) -> None:
        # Dropping the server-side lower bound would make an "incremental" sync page the full history
        # every run — identical API cost to a full refresh.
        params = _build_params(
            KOYEB_ENDPOINTS["instances"],
            offset=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params["order"] == "asc"
        assert params["starting_time"] == "2026-03-04T02:58:14+00:00"

    def test_usage_details_uses_starting_time_param(self) -> None:
        params = _build_params(
            KOYEB_ENDPOINTS["usage_details"],
            offset=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params["starting_time"] == "2026-03-04T00:00:00+00:00"

    @parameterized.expand(["apps", "app_events", "activities"])
    def test_full_refresh_endpoint_never_sends_time_filter(self, endpoint: str) -> None:
        # A time filter on an endpoint that has no server-side support would be silently ignored, but
        # setting `order`/`starting_time` here would falsely imply incremental behavior.
        params = _build_params(
            KOYEB_ENDPOINTS[endpoint],
            offset=100,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "starting_time" not in params
        assert "order" not in params
        assert params["offset"] == 100

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_cursor_is_clamped_to_now(self) -> None:
        # A future-dated cursor would ask for rows newer than the future value forever; clamp so the
        # request stays meaningful and the sync self-heals.
        params = _build_params(
            KOYEB_ENDPOINTS["instances"],
            offset=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 2, 5, tzinfo=UTC),
        )
        assert params["starting_time"] == "2026-06-15T12:00:00+00:00"

    def test_first_incremental_sync_has_no_time_filter(self) -> None:
        # No watermark yet: send order but no lower bound, so the first sync pulls the full window.
        params = _build_params(
            KOYEB_ENDPOINTS["instances"],
            offset=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert params["order"] == "asc"
        assert "starting_time" not in params


class TestHasMore:
    @parameterized.expand(
        [
            ("has_next_true", {"has_next": True}, 100, True),
            ("has_next_false", {"has_next": False}, 100, False),
            # No has_next flag (e.g. secrets/domains/instances replies): fall back to page-size.
            ("no_flag_full_page", {"count": 500}, 100, True),
            ("no_flag_short_page", {"count": 500}, 42, False),
            ("no_flag_empty_page", {}, 0, False),
        ]
    )
    def test_has_more(self, _name: str, page: dict, item_count: int, expected: bool) -> None:
        items = [{"id": str(i)} for i in range(item_count)]
        assert _has_more(page, "apps", items) is expected


class TestGetRows:
    @staticmethod
    def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: list[dict], **incremental: Any) -> list[dict]:
        calls = iter(pages)

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            return next(calls)

        monkeypatch.setattr(koyeb, "_fetch_page", fake_fetch)
        rows: list[dict] = []
        for batch in get_rows(
            api_key="tok",
            endpoint="apps",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **incremental,
        ):
            rows.extend(batch)
        return rows

    def test_paginates_across_offsets_until_short_page(self, monkeypatch: Any) -> None:
        # A full page (100) implies another page; a short page ends iteration. Getting this wrong
        # either loops forever or drops the tail.
        full = {"apps": [{"id": str(i)} for i in range(100)], "has_next": True}
        last = {"apps": [{"id": "100"}, {"id": "101"}], "has_next": False}
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, [full, last])
        assert len(rows) == 102
        # Resume state is saved once, after the first (non-final) page, pointing at the next offset.
        assert manager.saved == [KoyebResumeConfig(offset=100)]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        # A resumed run must start at the persisted offset, not from zero.
        fetched_urls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            fetched_urls.append(url)
            return {"apps": [{"id": "x"}], "has_next": False}

        monkeypatch.setattr(koyeb, "_fetch_page", fake_fetch)
        manager = _FakeResumableManager(KoyebResumeConfig(offset=200))
        list(
            get_rows(
                api_key="tok",
                endpoint="apps",
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
        )
        assert "offset=200" in fetched_urls[0]


class TestKoyebSource:
    @parameterized.expand(
        [
            ("apps", ["id"], "created_at", "asc"),
            ("organization_members", ["id"], "joined_at", "asc"),
            ("app_events", ["id"], "when", "asc"),
            ("usage_details", ["deployment_id", "instance_id", "started_at"], "started_at", "asc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, expected_pk: list[str], partition_key: str, sort_mode: str
    ) -> None:
        # A wrong primary key on usage_details (the one endpoint without a unique id) seeds duplicate
        # rows that make every incremental merge multi-match and eventually OOM the pod.
        response = koyeb_source(
            api_key="tok",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == sort_mode
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ]
    )
    def test_status_maps_to_result(self, status_code: int, expected_ok: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code == 200
        response.json.return_value = {"message": "nope"}
        session = MagicMock()
        session.get.return_value = response
        with patch.object(koyeb, "make_tracked_session", return_value=session):
            ok, _error = validate_credentials("tok")
        assert ok is expected_ok

    def test_forbidden_message_mentions_permission(self) -> None:
        # The source class keys off "permission" in this message to accept a scoped token at create.
        response = MagicMock()
        response.status_code = 403
        response.ok = False
        session = MagicMock()
        session.get.return_value = response
        with patch.object(koyeb, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("tok")
        assert ok is False
        assert error is not None and "permission" in error.lower()
