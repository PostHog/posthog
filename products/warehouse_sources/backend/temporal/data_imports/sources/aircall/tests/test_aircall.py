from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.aircall.aircall import (
    AircallResumeConfig,
    AircallTruncationError,
    _build_params,
    _build_url,
    _to_epoch,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aircall.settings import (
    AIRCALL_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aircall.source import AircallSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aircall import (
    AircallSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(AircallSource(), AircallSourceConfig(api_id="id", api_token="token"))


def _page(items_key: str, items: list[dict[str, Any]], next_link: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"meta": {"next_page_link": next_link}, items_key: items})


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-number", None),
            (True, None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected


class TestBuildParams:
    def test_incremental_endpoint_requests_ascending_order(self):
        params = _build_params(AIRCALL_ENDPOINTS["calls"], from_value=None)
        assert params["order"] == "asc"
        assert params["per_page"] == 50
        assert "from" not in params


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/calls", {}) == "https://api.aircall.io/v1/calls"


class TestValidateCredentials:
    def test_validate_credentials_probes_ping_with_basic_auth(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("id", "token") is True

        assert [request.url for request in network.requests_log] == ["https://api.aircall.io/v1/ping"]
        assert network.requests_log[0].headers["authorization"] == "Basic aWQ6dG9rZW4="
        assert network.session_options[0]["redact_values"] == ("token",)


class TestPagination:
    def test_paginates_via_next_page_link(self) -> None:
        result = _driver().run(
            "users",
            [
                _page("users", [{"id": 1}, {"id": 2}], "https://api.aircall.io/v1/users?page=2"),
                _page("users", [{"id": 3}], None),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.urls[0] == "https://api.aircall.io/v1/users?per_page=50"
        assert result.queries[0] == {"per_page": ("50",)}
        # The next-page URL is self-contained; original params are dropped.
        assert result.urls[1] == "https://api.aircall.io/v1/users?page=2"
        assert result.queries[1] == {"page": ("2",)}
        # State is saved only while a next page exists.
        assert result.saved_states == [AircallResumeConfig(next_url="https://api.aircall.io/v1/users?page=2")]

    def test_resumes_from_saved_state(self) -> None:
        resume_url = "https://api.aircall.io/v1/users?page=5"
        result = _driver().run(
            "users", [_page("users", [{"id": 9}], None)], resume_state=AircallResumeConfig(next_url=resume_url)
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [9]
        assert result.urls == [resume_url]
        assert result.queries == [{"page": ("5",)}]

    def test_reanchors_from_cursor_when_page_chain_ends(self) -> None:
        # First window ends without a next link; the latest started_at is used to issue a
        # fresh `from`-anchored request, then that window ends with no new advancement.
        result = _driver().run(
            "calls",
            [
                _page("calls", [{"id": 1, "started_at": 100}, {"id": 2, "started_at": 200}], None),
                _page("calls", [{"id": 2, "started_at": 200}], None),
            ],
        )

        # Two requests: original window + one re-anchored window.
        assert result.raised is None
        assert len(result.requests) == 2
        assert result.requests[1].param("from") == "200"
        # The re-anchored window URL is checkpointed like a next-page link.
        assert len(result.saved_states) == 1
        assert "from=200" in result.saved_states[0].next_url
        # Boundary row re-emitted; merge on primary key dedupes downstream.
        assert [row["id"] for row in result.rows] == [1, 2, 2]

    def test_reanchors_after_cap_records_when_next_link_has_no_page(self) -> None:
        # A next link the range check can't read (no page number) falls back to counting the
        # records consumed since the window opened.
        pages = [
            _page(
                "contacts",
                [{"id": page * 50 + index, "created_at": page * 50 + index} for index in range(1, 51)],
                "https://api.aircall.io/v1/contacts?cursor=opaque",
            )
            for page in range(200)
        ]
        result = _driver().run("contacts", [*pages, _page("contacts", [{"id": 10000, "created_at": 10000}], None)])

        assert result.raised is None
        assert len(result.requests) == 201
        assert result.requests[200].param("from") == "10000"
        assert len(result.rows) == 10001

    def test_raises_when_a_capped_window_cursor_cannot_advance(self) -> None:
        # Every record in the capped window shares the boundary timestamp, so a re-anchored
        # window would repeat the same query forever and the rest of the window is unreachable.
        # Raise so the run fails visibly instead of finalizing as complete with missing data.
        over_cap_link = "https://api.aircall.io/v1/contacts?order=asc&per_page=50&page=201"
        result = _driver().run(
            "contacts",
            [_page("contacts", [{"id": 1, "created_at": 200}], over_cap_link)],
            incremental_field="created_at",
            db_incremental_field_last_value=200,
        )

        assert isinstance(result.raised, AircallTruncationError)
        assert result.requests[0].param("from") == "200"
        assert result.saved_states == []

    def test_incremental_run_anchors_from_on_watermark(self) -> None:
        result = _driver().run(
            "calls",
            [_page("calls", [{"id": 1, "started_at": 1700000000}], None)],
            incremental_field="started_at",
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.queries[0] == {"per_page": ("50",), "order": ("asc",), "from": ("1700000000",)}
        # started_at did not advance past the watermark, so no re-anchored window is issued.
        assert len(result.requests) == 1


class TestConversationIntelligenceFanout:
    def test_child_rows_carry_call_id_from_parent(self) -> None:
        # The per-call sub-resource is fanned out over the calls list. Each child row must carry
        # the parent call id as `call_id` (the primary key), overriding whatever the body itself
        # holds, so one CI object per call stays uniquely keyed.
        result = _driver().run(
            "call_transcriptions",
            [
                _page("calls", [{"id": 1, "started_at": 100}, {"id": 2, "started_at": 200}], None),
                ScriptedResponse(json={"id": 55, "content": "hi", "call_id": 999}),
                ScriptedResponse(json={"id": 66, "content": "yo"}),
                # The calls paginator re-anchors once the first window ends; an empty window stops it.
                _page("calls", [], None),
            ],
        )

        assert result.raised is None
        assert [(row["call_id"], row["id"], row["content"]) for row in result.rows] == [
            (1, 55, "hi"),
            (2, 66, "yo"),
        ]
        child_paths = [path for path in result.paths if "transcription" in path]
        assert child_paths == ["/v1/calls/1/transcription", "/v1/calls/2/transcription"]

    def test_calls_without_ci_data_are_skipped(self) -> None:
        # A call with no AI data answers 404; that call is skipped rather than sinking the table.
        result = _driver().run(
            "call_evaluations",
            [
                _page("calls", [{"id": 1, "started_at": 100}, {"id": 2, "started_at": 200}], None),
                ScriptedResponse(status=404, json={"error": "not found"}),
                ScriptedResponse(json={"id": 66, "content": "yo"}),
                _page("calls", [], None),
            ],
        )

        assert result.raised is None
        assert [row["call_id"] for row in result.rows] == [2]


class TestAircallSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = AIRCALL_ENDPOINTS[endpoint]
        schema_name = "calls" if config.fanout else endpoint
        result = _driver().run(endpoint, [_page(schema_name, [], None)])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
