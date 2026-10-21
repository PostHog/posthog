from datetime import UTC, date, datetime
from typing import Any, cast

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.beamer import (
    BeamerResumeConfig,
    _format_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.source import BeamerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.beamer import BeamerSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(BeamerSource(), BeamerSourceConfig(api_key="key"))


def _page(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json=rows)


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("forbidden_is_valid_key", 403, True, None),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool, expected_msg: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            ok, message = validate_credentials("key")
        assert network.requests_log
        assert {request.path for request in network.requests_log} == {"/v0/posts"}
        assert {request.param("maxResults") for request in network.requests_log} == {"1"}
        assert {request.headers["beamer-api-key"] for request in network.requests_log} == {"key"}
        assert ok is expected_ok
        if expected_msg is None:
            assert message is None
        else:
            assert message is not None and expected_msg in message

    def test_network_error_is_inconclusive_not_invalid(self) -> None:
        # A transport failure must not be reported as an invalid key.
        with scripted_network(always(requests.ConnectionError("connection reset"))) as network:
            ok, message = validate_credentials("key")
        assert {request.path for request in network.requests_log} == {"/v0/posts"}
        assert ok is False
        assert message is not None and "Could not reach Beamer" in message


class TestTopLevelPagination:
    def test_incremental_adds_datefrom(self) -> None:
        result = _driver().run(
            "posts",
            [_page([{"id": 1, "date": "2026-03-05"}])],
            incremental_field="date",
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.rows == [{"id": 1, "date": "2026-03-05"}]
        assert result.requests[0].param("dateFrom") == "2026-03-04T02:58:14Z"

    def test_resume_starts_from_saved_page(self) -> None:
        result = _driver().run(
            "posts", [_page([{"id": 99, "date": "2026-01-01"}])], resume_state=BeamerResumeConfig(page=3)
        )

        assert result.raised is None
        assert result.rows == [{"id": 99, "date": "2026-01-01"}]
        assert result.requests[0].param("page") == "3"

    def test_full_page_checkpoints_next_page_and_short_page_does_not(self) -> None:
        full_page = [{"id": i, "date": "2026-01-01"} for i in range(10)]
        result = _driver().run("posts", [_page(full_page), _page([{"id": 10, "date": "2026-01-02"}])])

        # The checkpoint fires AFTER a page is yielded and points at the next page, so a crash
        # re-fetches the last checkpointed page (merge dedupes) rather than skipping rows. The
        # short final page leaves no checkpoint behind.
        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.saved_states == [BeamerResumeConfig(page=2)]

    def test_non_list_body_raises_loudly(self) -> None:
        result = _driver().run("posts", [ScriptedResponse(json={"error": "unexpected"})])

        # A 200 body that isn't a bare array means the response shape changed — fail loud, not 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestFanOut:
    def test_injects_parent_id_into_child_rows(self) -> None:
        result = _driver().run(
            "post_comments",
            [
                _page([{"id": "P1"}, {"id": "P2"}]),
                _page([{"id": "C1", "date": "2026-01-01", "text": "hi"}]),
                _page([{"id": "C2", "date": "2026-01-02", "text": "yo"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "C1", "date": "2026-01-01", "text": "hi", "post_id": "P1"},
            {"id": "C2", "date": "2026-01-02", "text": "yo", "post_id": "P2"},
        ]
        assert result.paths == ["/v0/posts", "/v0/posts/P1/comments", "/v0/posts/P2/comments"]
        # Child pages use the child's page size, not the parent's.
        assert result.requests[1].param("maxResults") == "10"
        assert result.requests[1].param("page") == "1"

    def test_numeric_parent_id_is_stringified(self) -> None:
        result = _driver().run("post_comments", [_page([{"id": 42}]), _page([{"id": "C1", "date": "2026-01-01"}])])

        # The composite primary key column keeps the string shape the hand-rolled source produced.
        assert result.raised is None
        assert result.rows == [{"id": "C1", "date": "2026-01-01", "post_id": "42"}]

    def test_feature_request_votes_inject_feature_request_id(self) -> None:
        result = _driver().run(
            "feature_request_votes",
            [_page([{"id": "R1"}]), _page([{"id": "V1", "date": "2026-01-01"}])],
        )

        assert result.raised is None
        assert result.rows == [{"id": "V1", "date": "2026-01-01", "feature_request_id": "R1"}]
        assert result.paths[1] == "/v0/requests/R1/votes"

    def test_deleted_parent_404_is_skipped(self) -> None:
        result = _driver().run(
            "post_comments",
            [
                _page([{"id": "P1"}, {"id": "P2"}]),
                ScriptedResponse(status=404, json={"error": "not found"}),
                _page([{"id": "C2", "date": "2026-01-02"}]),
            ],
        )

        # A parent deleted between enumeration and the child fetch 404s — skip it rather than
        # failing the whole sync; the remaining parents still sync.
        assert result.raised is None
        assert result.rows == [{"id": "C2", "date": "2026-01-02", "post_id": "P2"}]

    def test_non_404_error_propagates(self) -> None:
        result = _driver().run(
            "post_comments",
            [_page([{"id": "P1"}]), ScriptedResponse(status=403, json={"error": "forbidden"})],
        )

        assert isinstance(result.raised, requests.HTTPError)

    def test_resume_skips_completed_parents_and_resumes_child_page(self) -> None:
        result = _driver().run(
            "post_comments",
            [_page([{"id": "P1"}, {"id": "P2"}]), _page([{"id": "C9", "date": "2026-01-09"}])],
            resume_state=BeamerResumeConfig(
                fanout_state={
                    "completed": ["/posts/P1/comments"],
                    "current": "/posts/P2/comments",
                    "child_state": {"page": 2},
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": "C9", "date": "2026-01-09", "post_id": "P2"}]
        assert result.paths == ["/v0/posts", "/v0/posts/P2/comments"]
        assert result.requests[1].param("page") == "2"

    def test_checkpoints_fanout_state_as_parents_complete(self) -> None:
        result = _driver().run(
            "post_comments",
            [
                _page([{"id": "P1"}, {"id": "P2"}]),
                _page([{"id": "C1", "date": "2026-01-01"}]),
                _page([{"id": "C2", "date": "2026-01-02"}]),
            ],
        )

        assert result.raised is None
        assert result.saved_states
        assert all(
            isinstance(state, BeamerResumeConfig) and state.fanout_state is not None for state in result.saved_states
        )
        # The final checkpoint records both parents as fully synced with no child mid-stream.
        final = result.saved_states[-1].fanout_state
        assert final == {
            "completed": ["/posts/P1/comments", "/posts/P2/comments"],
            "current": None,
            "child_state": None,
        }

    def test_old_shape_resume_state_restarts_fanout(self) -> None:
        # A pre-migration bookmark (parent_id) can't seed the framework fan-out — the sync starts
        # that part fresh and merge dedupes the re-pulled rows.
        result = _driver().run(
            "post_comments",
            [
                _page([{"id": "P1"}, {"id": "P2"}]),
                _page([{"id": "C1", "date": "2026-01-01"}]),
                _page([{"id": "C2", "date": "2026-01-02"}]),
            ],
            resume_state=BeamerResumeConfig(page=2, parent_id="P2"),
        )

        assert result.raised is None
        assert [row["post_id"] for row in result.rows] == ["P1", "P2"]
        assert result.requests[1].param("page") == "1"

    def test_old_shape_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — state saved before the
        # migration must still construct.
        state = BeamerResumeConfig(**cast("dict[str, Any]", {"page": 3, "parent_id": "P2"}))
        assert state.page == 3
        assert state.parent_id == "P2"
        assert state.fanout_state is None


class TestBeamerSourceResponse:
    @parameterized.expand(
        [
            ("posts", ["id"], "date", "desc"),
            ("feature_requests", ["id"], "date", "desc"),
            ("nps", ["id"], "date", "desc"),
            ("users", ["beamerId"], "firstSeen", "asc"),
            ("post_comments", ["post_id", "id"], "date", "asc"),
            ("feature_request_votes", ["feature_request_id", "id"], "date", "asc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], partition_key: str, sort_mode: str
    ) -> None:
        result = _driver().run(endpoint, [_page([])])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == sort_mode
