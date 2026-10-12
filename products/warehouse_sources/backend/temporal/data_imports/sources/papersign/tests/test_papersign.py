import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.papersign import (
    PAGE_SIZE,
    PapersignResumeConfig,
    papersign_source,
    validate_credentials,
)

# The RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the papersign module.
PAPERSIGN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.papersign.papersign.make_tracked_session"
)


def _page_response(
    results_key: str,
    rows: list[dict[str, Any]] | None,
    has_more: bool,
    *,
    drop_results: bool = False,
) -> Response:
    body: dict[str, Any] = {"status": "ok", "total": 0, "has_more": has_more, "limit": PAGE_SIZE, "skip": 0}
    if not drop_results:
        body["results"] = {results_key: rows or []}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _docs(count: int, start: int = 0) -> list[dict[str, Any]]:
    return [{"id": f"doc-{start + i}", "created_at_utc": "2026-01-01T00:00:00Z"} for i in range(count)]


def _make_manager(resume_state: PapersignResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return papersign_source(
        api_token="tok",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    def test_resume_uses_saved_skip(self) -> None:
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            params = _wire(session, [_page_response("documents", _docs(2, start=200), has_more=False)])

            _rows(_source("documents", _make_manager(PapersignResumeConfig(skip=200))))

        # First request must continue from the saved offset, not restart at 0.
        assert params[0]["skip"] == 200

    def test_saves_only_already_fetched_offsets(self) -> None:
        # The "save current page, not next" invariant: every persisted offset must be one we've
        # already fetched, so a crash re-fetches (merge dedupes) rather than skipping buffered rows.
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            manager = _make_manager()
            params = _wire(
                session,
                [
                    _page_response("documents", _docs(PAGE_SIZE, start=0), has_more=True),
                    _page_response("documents", _docs(PAGE_SIZE, start=PAGE_SIZE), has_more=True),
                    _page_response("documents", _docs(10, start=2 * PAGE_SIZE), has_more=False),
                ],
            )

            _rows(_source("documents", manager))

        fetched_skips = {p["skip"] for p in params}
        assert manager.save_state.called, "expected a checkpoint after a yielded page"
        saved_skips = [call.args[0].skip for call in manager.save_state.call_args_list]
        assert all(skip in fetched_skips for skip in saved_skips)

    def test_missing_results_key_raises_loudly(self) -> None:
        # A 200 body without `results.documents` means the response shape changed — fail loud,
        # not silently sync 0 rows (which would wipe a full-refresh table).
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            _wire(session, [_page_response("documents", None, has_more=False, drop_results=True)])

            with pytest.raises(ValueError, match="matched nothing"):
                _rows(_source("documents", _make_manager()))


class TestSourceResponse:
    @parameterized.expand(["folders", "spaces"])
    def test_untimestamped_endpoints_are_not_partitioned(self, endpoint: str) -> None:
        # folders and spaces carry no stable datetime field, so they must not declare a datetime
        # partition (partitioning on a missing column would break the sync).
        with mock.patch(CLIENT_SESSION_PATCH):
            response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            (401, "invalid"),
            (403, "papersign api access"),
            (500, "unexpected status"),
        ]
    )
    @mock.patch(PAPERSIGN_SESSION_PATCH)
    def test_returns_false_on_http_status(
        self, status_code: int, expected_substring: str, mock_session: mock.MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        success, error = validate_credentials("tok")

        assert success is False
        assert error is not None
        assert expected_substring.lower() in error.lower()

    @mock.patch(PAPERSIGN_SESSION_PATCH)
    def test_redacts_token_in_tracked_session(self, mock_session: mock.MagicMock) -> None:
        # The bearer token must be passed to redact_values so it's masked in logged URLs and captured
        # HTTP samples. Dropping this would leak customers' API keys into the capture pipeline.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret-token")
        assert mock_session.call_args.kwargs.get("redact_values") == ("secret-token",)

    @mock.patch(PAPERSIGN_SESSION_PATCH)
    def test_returns_false_on_network_error(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")

        success, error = validate_credentials("tok")

        assert success is False
        assert error is not None
        assert "could not reach paperform" in error.lower()
