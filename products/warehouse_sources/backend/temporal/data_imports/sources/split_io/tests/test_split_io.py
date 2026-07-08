from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.split_io.settings import (
    ENDPOINTS,
    SPLIT_IO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io import (
    BASE_URL,
    PAGE_SIZE,
    SplitIoResumeConfig,
    _extract_items,
    _initial_url,
    _next_url,
    get_rows,
    split_io_source,
    validate_credentials,
)


def _make_manager(resume_state: SplitIoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _resp(payload: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = payload
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    return resp


def _offset_page(items: list[dict[str, Any]], offset: int, total_count: int) -> dict[str, Any]:
    return {"objects": items, "offset": offset, "limit": PAGE_SIZE, "totalCount": total_count}


class TestUrlHelpers:
    def test_initial_url_top_level_includes_limit(self):
        assert _initial_url(SPLIT_IO_ENDPOINTS["workspaces"]) == f"{BASE_URL}/workspaces?limit={PAGE_SIZE}"

    def test_initial_url_formats_workspace_path(self):
        url = _initial_url(SPLIT_IO_ENDPOINTS["feature_flags"], "ws-1")
        assert url == f"{BASE_URL}/splits/ws/ws-1?limit={PAGE_SIZE}"

    def test_initial_url_workspace_query_param(self):
        url = _initial_url(SPLIT_IO_ENDPOINTS["rollout_statuses"], "ws-1")
        assert url == f"{BASE_URL}/rolloutStatuses?wsId=ws-1"

    def test_initial_url_flag_sets_uses_v3_api(self):
        url = _initial_url(SPLIT_IO_ENDPOINTS["flag_sets"], "ws-1")
        assert url == f"https://api.split.io/internal/api/v3/flag-sets?workspace_id=ws-1&limit={PAGE_SIZE}"

    def test_initial_url_unpaginated_endpoint_has_no_limit(self):
        url = _initial_url(SPLIT_IO_ENDPOINTS["environments"], "ws-1")
        assert url == f"{BASE_URL}/environments/ws/ws-1"


class TestExtractItems:
    @pytest.mark.parametrize(
        "payload, data_key, expected",
        [
            ([{"id": "1"}], None, [{"id": "1"}]),
            ({"objects": [{"id": "1"}]}, "objects", [{"id": "1"}]),
            ({"data": [{"id": "1"}]}, "data", [{"id": "1"}]),
            # Envelope-key drift: rows under the other documented key are still found.
            ({"data": [{"id": "1"}]}, "objects", [{"id": "1"}]),
            ({"objects": [{"id": "1"}]}, "data", [{"id": "1"}]),
            ({"unrelated": True}, "objects", []),
        ],
    )
    def test_extract_items(self, payload, data_key, expected):
        assert _extract_items(payload, data_key) == expected


class TestNextUrl:
    def test_offset_advances_by_row_count(self):
        config = SPLIT_IO_ENDPOINTS["workspaces"]
        url = f"{BASE_URL}/workspaces?limit={PAGE_SIZE}"
        items = [{"id": str(i)} for i in range(PAGE_SIZE)]
        next_url = _next_url(config, url, _offset_page(items, 0, PAGE_SIZE * 2), items)
        assert next_url == f"{BASE_URL}/workspaces?limit={PAGE_SIZE}&offset={PAGE_SIZE}"

    def test_offset_stops_at_total_count(self):
        config = SPLIT_IO_ENDPOINTS["workspaces"]
        url = f"{BASE_URL}/workspaces?limit={PAGE_SIZE}&offset={PAGE_SIZE}"
        items = [{"id": "x"}]
        assert _next_url(config, url, _offset_page(items, PAGE_SIZE, PAGE_SIZE + 1), items) is None

    def test_offset_server_clamped_limit_keeps_paginating(self):
        # The server may clamp `limit` below what we requested; totalCount must drive
        # termination, not the short page.
        config = SPLIT_IO_ENDPOINTS["workspaces"]
        url = f"{BASE_URL}/workspaces?limit={PAGE_SIZE}"
        items = [{"id": str(i)} for i in range(10)]
        next_url = _next_url(config, url, _offset_page(items, 0, 30), items)
        assert next_url == f"{BASE_URL}/workspaces?limit={PAGE_SIZE}&offset=10"

    def test_offset_without_total_count_stops_on_short_page(self):
        config = SPLIT_IO_ENDPOINTS["workspaces"]
        url = f"{BASE_URL}/workspaces?limit={PAGE_SIZE}"
        items = [{"id": "1"}]
        assert _next_url(config, url, {"objects": items}, items) is None

    def test_marker_advances_via_next_marker(self):
        config = SPLIT_IO_ENDPOINTS["users"]
        url = f"{BASE_URL}/users?limit={PAGE_SIZE}"
        items = [{"id": "u1"}]
        next_url = _next_url(config, url, {"data": items, "nextMarker": "m2"}, items)
        assert next_url == f"{BASE_URL}/users?limit={PAGE_SIZE}&after=m2"

    @pytest.mark.parametrize("payload", [{"data": [{"id": "u1"}]}, {"data": [{"id": "u1"}], "nextMarker": None}])
    def test_marker_stops_without_next_marker(self, payload):
        config = SPLIT_IO_ENDPOINTS["users"]
        url = f"{BASE_URL}/users?limit={PAGE_SIZE}"
        assert _next_url(config, url, payload, payload["data"]) is None

    def test_marker_stops_when_server_ignores_after_param(self):
        # A repeated marker means the server ignored `after`; stopping avoids an infinite loop.
        config = SPLIT_IO_ENDPOINTS["users"]
        url = f"{BASE_URL}/users?limit={PAGE_SIZE}&after=m2"
        items = [{"id": "u1"}]
        assert _next_url(config, url, {"data": items, "nextMarker": "m2"}, items) is None

    def test_marker_reads_next_marker_from_objects_envelope(self):
        # Groups paginate by marker but wrap rows in `objects` rather than `data`.
        config = SPLIT_IO_ENDPOINTS["groups"]
        url = f"{BASE_URL}/groups?limit={PAGE_SIZE}"
        items = [{"id": "g1"}]
        next_url = _next_url(config, url, {"objects": items, "nextMarker": "m2"}, items)
        assert next_url == f"{BASE_URL}/groups?limit={PAGE_SIZE}&after=m2"

    @pytest.mark.parametrize("payload", [[{"id": "1"}], {"objects": [{"id": "1"}]}])
    def test_unpaginated_endpoint_never_advances(self, payload):
        config = SPLIT_IO_ENDPOINTS["environments"]
        items = _extract_items(payload, config.data_key)
        assert _next_url(config, f"{BASE_URL}/environments/ws/ws-1", payload, items) is None


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 500])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_returns_status_code(self, mock_session, status_code):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("api-key") == status_code

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_returns_none_on_exception(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("api-key") is None

    @pytest.mark.parametrize(
        "endpoint, expected_url",
        [
            # Source-create and fan-out endpoints probe /workspaces (their prerequisite).
            (None, f"{BASE_URL}/workspaces?limit=1"),
            ("feature_flags", f"{BASE_URL}/workspaces?limit=1"),
            # Top-level endpoints probe their own path.
            ("groups", f"{BASE_URL}/groups?limit=1"),
            ("users", f"{BASE_URL}/users?limit=1"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_probes_the_right_endpoint(self, mock_session, endpoint, expected_url):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("api-key", endpoint)
        assert mock_session.return_value.get.call_args.args[0] == expected_url


class TestGetRowsTopLevel:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_paginates_offset_endpoint(self, mock_session):
        first = [{"id": str(i)} for i in range(PAGE_SIZE)]
        mock_session.return_value.get.side_effect = [
            _resp(_offset_page(first, 0, PAGE_SIZE + 1)),
            _resp(_offset_page([{"id": "last"}], PAGE_SIZE, PAGE_SIZE + 1)),
        ]

        manager = _make_manager()
        batches = list(get_rows("api-key", "workspaces", mock.MagicMock(), manager))

        ids = [item["id"] for batch in batches for item in batch]
        assert ids == [str(i) for i in range(PAGE_SIZE)] + ["last"]
        # State saved after every page (final save records the empty next_url marker).
        saved_urls = [call.args[0].next_url for call in manager.save_state.call_args_list]
        assert saved_urls == [f"{BASE_URL}/workspaces?limit={PAGE_SIZE}&offset={PAGE_SIZE}", ""]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_resumes_from_saved_state(self, mock_session):
        mock_session.return_value.get.return_value = _resp(_offset_page([{"id": "9"}], PAGE_SIZE, PAGE_SIZE + 1))

        resume_url = f"{BASE_URL}/workspaces?limit={PAGE_SIZE}&offset={PAGE_SIZE}"
        manager = _make_manager(SplitIoResumeConfig(next_url=resume_url))

        list(get_rows("api-key", "workspaces", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_marker_endpoint_paginates_until_marker_exhausted(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp({"data": [{"id": "u1"}], "nextMarker": "m2"}),
            _resp({"data": [{"id": "u2"}], "nextMarker": None}),
        ]

        batches = list(get_rows("api-key", "users", mock.MagicMock(), _make_manager()))

        assert [item["id"] for batch in batches for item in batch] == ["u1", "u2"]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls == [
            f"{BASE_URL}/users?limit={PAGE_SIZE}",
            f"{BASE_URL}/users?limit={PAGE_SIZE}&after=m2",
        ]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_empty_response_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _resp({"objects": [], "nextMarker": None})

        assert list(get_rows("api-key", "groups", mock.MagicMock(), _make_manager())) == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_identical_page_stops_pagination(self, mock_session):
        # A server that ignores our pagination params but keeps advertising a fresh marker
        # would otherwise loop forever re-yielding the same rows.
        same_page = {"data": [{"id": "u1"}], "nextMarker": "m2"}
        mock_session.return_value.get.side_effect = [
            _resp(same_page),
            _resp({"data": [{"id": "u1"}], "nextMarker": "m3"}),
            _resp({"data": [{"id": "u1"}], "nextMarker": "m4"}),
        ]

        batches = list(get_rows("api-key", "users", mock.MagicMock(), _make_manager()))

        # First page yielded once; the identical follow-up page halts the loop.
        assert [item["id"] for batch in batches for item in batch] == ["u1"]
        assert mock_session.return_value.get.call_count == 2


class TestGetRowsFanout:
    def _workspaces_page(self) -> mock.MagicMock:
        return _resp(_offset_page([{"id": "ws-1"}, {"id": "ws-2"}], 0, 2))

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_iterates_workspaces_and_injects_workspace_id(self, mock_session):
        mock_session.return_value.get.side_effect = [
            self._workspaces_page(),
            _resp([{"id": "e1"}]),
            _resp([{"id": "e2"}]),
        ]

        batches = list(get_rows("api-key", "environments", mock.MagicMock(), _make_manager()))

        rows = [item for batch in batches for item in batch]
        assert rows == [
            {"id": "e1", "_workspace_id": "ws-1"},
            {"id": "e2", "_workspace_id": "ws-2"},
        ]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls == [
            f"{BASE_URL}/workspaces?limit={PAGE_SIZE}",
            f"{BASE_URL}/environments/ws/ws-1",
            f"{BASE_URL}/environments/ws/ws-2",
        ]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_workspace_query_param_fanout(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp(_offset_page([{"id": "ws-1"}], 0, 1)),
            _resp([{"id": "rs1"}]),
        ]

        list(get_rows("api-key", "rollout_statuses", mock.MagicMock(), _make_manager()))

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls[1] == f"{BASE_URL}/rolloutStatuses?wsId=ws-1"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_resume_skips_completed_workspace(self, mock_session):
        # ws-1 finished last run (empty next_url marker); resume must start at ws-2.
        mock_session.return_value.get.side_effect = [
            self._workspaces_page(),
            _resp([{"id": "e2"}]),
        ]
        manager = _make_manager(SplitIoResumeConfig(next_url="", workspace_id="ws-1"))

        batches = list(get_rows("api-key", "environments", mock.MagicMock(), manager))

        rows = [item for batch in batches for item in batch]
        assert rows == [{"id": "e2", "_workspace_id": "ws-2"}]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls == [f"{BASE_URL}/workspaces?limit={PAGE_SIZE}", f"{BASE_URL}/environments/ws/ws-2"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_resume_midworkspace_uses_saved_url(self, mock_session):
        resume_url = f"{BASE_URL}/splits/ws/ws-1?limit={PAGE_SIZE}&offset={PAGE_SIZE}"
        mock_session.return_value.get.side_effect = [
            self._workspaces_page(),
            _resp(_offset_page([{"name": "f1b"}], PAGE_SIZE, PAGE_SIZE + 1)),
            _resp(_offset_page([{"name": "f2"}], 0, 1)),
        ]
        manager = _make_manager(SplitIoResumeConfig(next_url=resume_url, workspace_id="ws-1"))

        list(get_rows("api-key", "feature_flags", mock.MagicMock(), manager))

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls == [
            f"{BASE_URL}/workspaces?limit={PAGE_SIZE}",
            resume_url,
            f"{BASE_URL}/splits/ws/ws-2?limit={PAGE_SIZE}",
        ]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_no_workspaces_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _resp(_offset_page([], 0, 0))

        assert list(get_rows("api-key", "feature_flags", mock.MagicMock(), _make_manager())) == []


class TestRetryAndErrors:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io.make_tracked_session"
    )
    def test_4xx_raises(self, mock_session):
        resp = _resp({}, status_code=403)
        resp.raise_for_status.side_effect = Exception("403 Client Error")
        mock_session.return_value.get.return_value = resp

        with pytest.raises(Exception, match="403 Client Error"):
            list(get_rows("api-key", "workspaces", mock.MagicMock(), _make_manager()))


class TestSplitIoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = SPLIT_IO_ENDPOINTS[endpoint]
        response = split_io_source("api-key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Partitioning is intentionally off (epoch-ms timestamps).
        assert response.partition_mode is None
        assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", ["feature_flags", "segments"])
    def test_workspace_scoped_names_use_composite_primary_key(self, endpoint):
        assert SPLIT_IO_ENDPOINTS[endpoint].primary_keys == ["name", "_workspace_id"]
