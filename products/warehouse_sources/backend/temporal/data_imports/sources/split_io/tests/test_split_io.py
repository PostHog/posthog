from typing import Any

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.splitio import (
    SplitIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.split_io.settings import (
    ENDPOINTS,
    SPLIT_IO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.split_io.source import SplitIoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io import (
    BASE_URL,
    PAGE_SIZE,
    SplitIoResumeConfig,
    _extract_items,
    _next_url,
    validate_credentials,
)


def _resp(payload: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=payload)


def _offset_page(items: list[dict[str, Any]], offset: int, total_count: int) -> dict[str, Any]:
    return {"objects": items, "offset": offset, "limit": PAGE_SIZE, "totalCount": total_count}


def _run(endpoint: str, script: Script, resume_state: SplitIoResumeConfig | None = None) -> DriveResult:
    config = SplitIoSourceConfig(api_key="api-key")
    return SourceDriver(SplitIoSource(), config).run(endpoint, script, resume_state=resume_state)


def _ids(result: DriveResult) -> list[Any]:
    return [item["id"] for item in result.rows]


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
    def test_offset_without_total_count_stops_on_short_page(self):
        config = SPLIT_IO_ENDPOINTS["workspaces"]
        url = f"{BASE_URL}/workspaces?limit={PAGE_SIZE}"
        items = [{"id": "1"}]
        assert _next_url(config, url, {"objects": items}, items) is None

    def test_marker_stops_when_server_ignores_after_param(self):
        # A repeated marker means the server ignored `after`; stopping avoids an infinite loop.
        config = SPLIT_IO_ENDPOINTS["users"]
        url = f"{BASE_URL}/users?limit={PAGE_SIZE}&after=m2"
        items = [{"id": "u1"}]
        assert _next_url(config, url, {"data": items, "nextMarker": "m2"}, items) is None

    @pytest.mark.parametrize("payload", [[{"id": "1"}], {"objects": [{"id": "1"}]}])
    def test_unpaginated_endpoint_never_advances(self, payload):
        config = SPLIT_IO_ENDPOINTS["environments"]
        items = _extract_items(payload, config.data_key)
        assert _next_url(config, f"{BASE_URL}/environments/ws/ws-1", payload, items) is None


class TestValidateCredentials:
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
    def test_probes_the_right_endpoint(self, endpoint, expected_url):
        with scripted_network([_resp({})]) as network:
            validate_credentials("api-key", endpoint)
        assert network.requests_log[0].url == expected_url


class TestGetRowsTopLevel:
    def test_paginates_offset_endpoint(self):
        first = [{"id": str(i)} for i in range(PAGE_SIZE)]

        result = _run(
            "workspaces",
            [
                _resp(_offset_page(first, 0, PAGE_SIZE + 1)),
                _resp(_offset_page([{"id": "last"}], PAGE_SIZE, PAGE_SIZE + 1)),
            ],
        )

        assert _ids(result) == [str(i) for i in range(PAGE_SIZE)] + ["last"]
        # State saved after every page (final save records the empty next_url marker).
        saved_urls = [state.next_url for state in result.saved_states]
        assert saved_urls == [f"{BASE_URL}/workspaces?limit={PAGE_SIZE}&offset={PAGE_SIZE}", ""]

    def test_resumes_from_saved_state(self):
        resume_url = f"{BASE_URL}/workspaces?limit={PAGE_SIZE}&offset={PAGE_SIZE}"

        result = _run(
            "workspaces",
            [_resp(_offset_page([{"id": "9"}], PAGE_SIZE, PAGE_SIZE + 1))],
            resume_state=SplitIoResumeConfig(next_url=resume_url),
        )

        assert result.urls[0] == resume_url

    def test_marker_endpoint_paginates_until_marker_exhausted(self):
        result = _run(
            "users",
            [
                _resp({"data": [{"id": "u1"}], "nextMarker": "m2"}),
                _resp({"data": [{"id": "u2"}], "nextMarker": None}),
            ],
        )

        assert _ids(result) == ["u1", "u2"]
        assert result.urls == [
            f"{BASE_URL}/users?limit={PAGE_SIZE}",
            f"{BASE_URL}/users?limit={PAGE_SIZE}&after=m2",
        ]

    def test_identical_page_stops_pagination(self):
        # A server that ignores our pagination params but keeps advertising a fresh marker
        # would otherwise loop forever re-yielding the same rows.
        result = _run(
            "users",
            [
                _resp({"data": [{"id": "u1"}], "nextMarker": "m2"}),
                _resp({"data": [{"id": "u1"}], "nextMarker": "m3"}),
                _resp({"data": [{"id": "u1"}], "nextMarker": "m4"}),
            ],
        )

        # First page yielded once; the identical follow-up page halts the loop.
        assert _ids(result) == ["u1"]
        assert len(result.requests) == 2


class TestGetRowsFanout:
    def _workspaces_page(self) -> ScriptedResponse:
        return _resp(_offset_page([{"id": "ws-1"}, {"id": "ws-2"}], 0, 2))

    def test_iterates_workspaces_and_injects_workspace_id(self):
        result = _run(
            "environments",
            [
                self._workspaces_page(),
                _resp([{"id": "e1"}]),
                _resp([{"id": "e2"}]),
            ],
        )

        assert result.rows == [
            {"id": "e1", "_workspace_id": "ws-1"},
            {"id": "e2", "_workspace_id": "ws-2"},
        ]
        assert result.urls == [
            f"{BASE_URL}/workspaces?limit={PAGE_SIZE}",
            f"{BASE_URL}/environments/ws/ws-1",
            f"{BASE_URL}/environments/ws/ws-2",
        ]

    def test_workspace_query_param_fanout(self):
        result = _run(
            "rollout_statuses",
            [
                _resp(_offset_page([{"id": "ws-1"}], 0, 1)),
                _resp([{"id": "rs1"}]),
            ],
        )

        assert result.urls[1] == f"{BASE_URL}/rolloutStatuses?wsId=ws-1"

    def test_resume_skips_completed_workspace(self):
        # ws-1 finished last run (empty next_url marker); resume must start at ws-2.
        result = _run(
            "environments",
            [
                self._workspaces_page(),
                _resp([{"id": "e2"}]),
            ],
            resume_state=SplitIoResumeConfig(next_url="", workspace_id="ws-1"),
        )

        assert result.rows == [{"id": "e2", "_workspace_id": "ws-2"}]
        assert result.urls == [f"{BASE_URL}/workspaces?limit={PAGE_SIZE}", f"{BASE_URL}/environments/ws/ws-2"]

    def test_resume_midworkspace_uses_saved_url(self):
        resume_url = f"{BASE_URL}/splits/ws/ws-1?limit={PAGE_SIZE}&offset={PAGE_SIZE}"

        result = _run(
            "feature_flags",
            [
                self._workspaces_page(),
                _resp(_offset_page([{"name": "f1b"}], PAGE_SIZE, PAGE_SIZE + 1)),
                _resp(_offset_page([{"name": "f2"}], 0, 1)),
            ],
            resume_state=SplitIoResumeConfig(next_url=resume_url, workspace_id="ws-1"),
        )

        assert result.urls == [
            f"{BASE_URL}/workspaces?limit={PAGE_SIZE}",
            resume_url,
            f"{BASE_URL}/splits/ws/ws-2?limit={PAGE_SIZE}",
        ]

    def test_no_workspaces_yields_nothing(self):
        result = _run("feature_flags", [_resp(_offset_page([], 0, 0))])

        assert result.rows == []


class TestRetryAndErrors:
    def test_4xx_raises(self):
        result = _run("workspaces", [_resp({}, status_code=403)])

        assert isinstance(result.raised, HTTPError)
        assert "403 Client Error" in str(result.raised)


class TestSplitIoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = SPLIT_IO_ENDPOINTS[endpoint]
        response = _run(endpoint, always(_resp([]))).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Partitioning is intentionally off (epoch-ms timestamps).
        assert response.partition_mode is None
        assert response.partition_keys is None
