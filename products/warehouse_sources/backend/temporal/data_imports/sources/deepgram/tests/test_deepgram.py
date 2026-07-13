from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram import deepgram
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.deepgram import (
    DeepgramResumeConfig,
    _build_request_params,
    _format_start_value,
    _transform_row,
    deepgram_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.settings import DEEPGRAM_ENDPOINTS


class TestFormatStartValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_start_value(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        # A +00:00 offset (isoformat default) is not the ISO shape we send; assert we emit the Z form.
        assert "+00:00" not in _format_start_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_clamped_to_now(self) -> None:
        # Asking for requests created after "now" is pointless; cap it so we don't skip the window.
        assert _format_start_value(datetime(2027, 1, 1, tzinfo=UTC)) == "2026-06-15T12:00:00.000Z"


class TestBuildRequestParams:
    def test_incremental_sets_start_and_page_size(self) -> None:
        params = _build_request_params(
            DEEPGRAM_ENDPOINTS["requests"],
            page=3,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params["page"] == 3
        assert params["limit"] == deepgram.REQUESTS_PAGE_SIZE
        assert params["start"] == "2026-03-04T02:58:14.000Z"

    def test_non_incremental_omits_start(self) -> None:
        params = _build_request_params(
            DEEPGRAM_ENDPOINTS["requests"],
            page=0,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert "start" not in params


class TestTransformRow:
    def test_injects_project_id(self) -> None:
        row = _transform_row({"member_id": "m1"}, "proj-1", DEEPGRAM_ENDPOINTS["members"])
        assert row["project_id"] == "proj-1"
        assert row["member_id"] == "m1"

    def test_flattens_nested_key_to_root(self) -> None:
        # /keys nests the key under "api_key"; api_key_id must land at the row root or the composite
        # primary key can't be built and the delta merge multi-matches duplicate rows.
        row = _transform_row(
            {"api_key": {"api_key_id": "k1", "comment": "ci"}, "member": {"email": "a@b.co"}},
            "proj-1",
            DEEPGRAM_ENDPOINTS["keys"],
        )
        assert row["api_key_id"] == "k1"
        assert row["comment"] == "ci"
        assert row["project_id"] == "proj-1"
        assert row["member"] == {"email": "a@b.co"}
        assert "api_key" not in row

    @parameterized.expand(
        [
            ("basic_auth", "https://user:pass@hooks.example.com/cb", "https://hooks.example.com/cb"),
            ("no_creds", "https://hooks.example.com/cb", "https://hooks.example.com/cb"),
            ("not_a_url", "not-a-url", "not-a-url"),
        ]
    )
    def test_redacts_callback_userinfo(self, _name: str, callback: str, expected: str) -> None:
        # A callback URL can embed Basic Auth creds; they must not reach the warehouse.
        row = _transform_row({"request_id": "r1", "callback": callback}, "proj-1", DEEPGRAM_ENDPOINTS["requests"])
        assert row["callback"] == expected

    def test_missing_primary_key_raises(self) -> None:
        # A row missing request_id would let the merge overwrite unrelated rows; fail instead of emit.
        with pytest.raises(ValueError, match="request_id"):
            _transform_row({"created": "2026-01-01"}, "proj-1", DEEPGRAM_ENDPOINTS["requests"])


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status)
        with patch.object(deepgram, "make_tracked_session", return_value=session):
            assert validate_credentials("token") is expected

    def test_network_error_is_false(self) -> None:
        with patch.object(deepgram, "make_tracked_session", side_effect=Exception("boom")):
            assert validate_credentials("token") is False


def _fake_manager(resume: DeepgramResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestGetRows:
    def _run(self, endpoint: str, fetch_side_effect: Any, manager: MagicMock, **kwargs: Any) -> list[list[dict]]:
        with (
            patch.object(deepgram, "make_tracked_session", return_value=MagicMock()),
            patch.object(deepgram, "_fetch_json", side_effect=fetch_side_effect),
        ):
            return list(
                get_rows(
                    api_key="token",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    **kwargs,
                )
            )

    def test_project_list_yields_projects_without_fan_out(self) -> None:
        projects = [{"project_id": "p1"}, {"project_id": "p2"}]

        def fetch(_session, url, _headers, _logger, params=None):
            assert url.endswith("/projects")
            return {"projects": projects}

        batches = self._run("projects", fetch, _fake_manager())
        assert batches == [projects]

    def test_fan_out_injects_project_id_per_row(self) -> None:
        def fetch(_session, url, _headers, _logger, params=None):
            if url.endswith("/projects"):
                return {"projects": [{"project_id": "p1"}, {"project_id": "p2"}]}
            return {"members": [{"member_id": "m1"}]}

        batches = self._run("members", fetch, _fake_manager())
        project_ids = {row["project_id"] for batch in batches for row in batch}
        assert project_ids == {"p1", "p2"}

    def test_paginated_requests_terminate_on_short_page(self) -> None:
        # limit is patched to 2, so a page returning fewer than 2 rows ends pagination for a project.
        pages = {0: [{"request_id": "r1"}, {"request_id": "r2"}], 1: [{"request_id": "r3"}]}

        def fetch(_session, url, _headers, _logger, params):
            if url.endswith("/projects"):
                return {"projects": [{"project_id": "p1"}]}
            return {"requests": pages[params["page"]]}

        with patch.object(deepgram, "REQUESTS_PAGE_SIZE", 2):
            batches = self._run(
                "requests",
                fetch,
                _fake_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
            )
        request_ids = [row["request_id"] for batch in batches for row in batch]
        assert request_ids == ["r1", "r2", "r3"]

    def test_resume_starts_from_saved_project(self) -> None:
        def fetch(_session, url, _headers, _logger, params=None):
            if url.endswith("/projects"):
                return {"projects": [{"project_id": "p1"}, {"project_id": "p2"}]}
            return {"members": [{"member_id": f"m-{url.split('/projects/')[1].split('/')[0]}"}]}

        manager = _fake_manager(DeepgramResumeConfig(project_id="p2", page=None))
        batches = self._run("members", fetch, manager)
        project_ids = {row["project_id"] for batch in batches for row in batch}
        assert project_ids == {"p2"}  # p1 skipped — already synced before the crash

    def test_state_saved_advances_page_after_yield(self) -> None:
        pages = {0: [{"request_id": "r1"}, {"request_id": "r2"}], 1: [{"request_id": "r3"}]}

        def fetch(_session, url, _headers, _logger, params):
            if url.endswith("/projects"):
                return {"projects": [{"project_id": "p1"}]}
            return {"requests": pages[params["page"]]}

        manager = _fake_manager()
        with patch.object(deepgram, "REQUESTS_PAGE_SIZE", 2):
            self._run(
                "requests", fetch, manager, should_use_incremental_field=True, db_incremental_field_last_value=None
            )
        # After yielding page 0 we persist page 1 so a crash re-fetches page 1 rather than restarting.
        saved_pages = [call.args[0].page for call in manager.save_state.call_args_list]
        assert 1 in saved_pages


class TestDeepgramSource:
    @parameterized.expand(
        [
            ("requests_is_incremental", "requests", "desc", ["project_id", "request_id"]),
            ("members_full_refresh", "members", "asc", ["project_id", "member_id"]),
            ("projects_top_level", "projects", "asc", ["project_id"]),
        ]
    )
    def test_source_response_shape(self, _name: str, endpoint: str, sort_mode: str, primary_keys: list[str]) -> None:
        response = deepgram_source(
            api_key="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode

    def test_partitioned_only_when_partition_key_set(self) -> None:
        # requests has a stable `created` partition key; members has none.
        assert deepgram_source("t", "requests", MagicMock(), MagicMock()).partition_mode == "datetime"
        assert deepgram_source("t", "members", MagicMock(), MagicMock()).partition_mode is None
