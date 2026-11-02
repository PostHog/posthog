from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.papersign import (
    PapersignSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.papersign import (
    PAGE_SIZE,
    PapersignResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.source import PapersignSource


def _driver() -> SourceDriver:
    return SourceDriver(PapersignSource(), PapersignSourceConfig(api_token="tok"))


def _page_response(
    results_key: str,
    rows: list[dict[str, Any]] | None,
    has_more: bool,
    *,
    drop_results: bool = False,
) -> ScriptedResponse:
    body: dict[str, Any] = {"status": "ok", "total": 0, "has_more": has_more, "limit": PAGE_SIZE, "skip": 0}
    if not drop_results:
        body["results"] = {results_key: rows or []}
    return ScriptedResponse(json=body)


def _docs(count: int, start: int = 0) -> list[dict[str, Any]]:
    return [{"id": f"doc-{start + i}", "created_at_utc": "2026-01-01T00:00:00Z"} for i in range(count)]


class TestPagination:
    def test_resume_uses_saved_skip(self) -> None:
        result = _driver().run(
            "documents",
            [_page_response("documents", _docs(2, start=200), has_more=False)],
            resume_state=PapersignResumeConfig(skip=200),
        )

        # First request must continue from the saved offset, not restart at 0.
        assert result.raised is None
        assert result.params("skip") == ["200"]
        assert result.rows == _docs(2, start=200)

    def test_saves_only_already_fetched_offsets(self) -> None:
        # The "save current page, not next" invariant: every persisted offset must be one we've
        # already fetched, so a crash re-fetches (merge dedupes) rather than skipping buffered rows.
        result = _driver().run(
            "documents",
            [
                _page_response("documents", _docs(PAGE_SIZE, start=0), has_more=True),
                _page_response("documents", _docs(PAGE_SIZE, start=PAGE_SIZE), has_more=True),
                _page_response("documents", _docs(10, start=2 * PAGE_SIZE), has_more=False),
            ],
        )

        assert result.raised is None
        assert result.params("skip") == ["0", str(PAGE_SIZE), str(2 * PAGE_SIZE)]
        assert result.params("limit") == [str(PAGE_SIZE)] * 3
        assert result.params("sort") == ["ASC", "ASC", "ASC"]
        assert len(result.rows) == 2 * PAGE_SIZE + 10
        fetched_skips = set(result.params("skip"))
        assert result.saved_states, "expected a checkpoint after a yielded page"
        assert all(str(state.skip) in fetched_skips for state in result.saved_states)

    def test_missing_results_key_raises_loudly(self) -> None:
        # A 200 body without `results.documents` means the response shape changed — fail loud,
        # not silently sync 0 rows (which would wipe a full-refresh table).
        result = _driver().run("documents", [_page_response("documents", None, has_more=False, drop_results=True)])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestSourceResponse:
    @parameterized.expand(["folders", "spaces"])
    def test_untimestamped_endpoints_are_not_partitioned(self, endpoint: str) -> None:
        # folders and spaces carry no stable datetime field, so they must not declare a datetime
        # partition (partitioning on a missing column would break the sync).
        result = _driver().run(endpoint, [_page_response(endpoint, [], has_more=False)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            (401, "invalid"),
        ]
    )
    def test_returns_false_on_http_status(self, status_code: int, expected_substring: str) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            success, error = validate_credentials("tok")

        assert network.requests_log[0].path == "/v1/papersign/spaces"
        assert network.requests_log[0].param("limit") == "1"
        assert success is False
        assert error is not None
        assert expected_substring.lower() in error.lower()

    def test_redacts_token_in_tracked_session(self) -> None:
        # The bearer token must be passed to redact_values so it's masked in logged URLs and captured
        # HTTP samples. Dropping this would leak customers' API keys into the capture pipeline.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            success, error = validate_credentials("secret-token")

        assert (success, error) == (True, None)
        assert network.session_options[0]["redact_values"] == ("secret-token",)
        assert network.requests_log[0].headers["authorization"] == "Bearer secret-token"

    def test_returns_false_on_network_error(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            success, error = validate_credentials("tok")

        assert {request.path for request in network.requests_log} == {"/v1/papersign/spaces"}
        assert success is False
        assert error is not None
        assert "could not reach paperform" in error.lower()
