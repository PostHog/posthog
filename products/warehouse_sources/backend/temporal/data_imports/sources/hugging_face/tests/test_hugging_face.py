import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.hugging_face import (
    HUGGING_FACE_BASE_URL,
    HuggingFaceResumeConfig,
    _build_initial_params,
    hugging_face_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.settings import (
    HUGGING_FACE_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the hugging_face module.
HF_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.hugging_face.make_tracked_session"
)
# tenacity sleeps between retries; silence it so retry tests don't wait.
TENACITY_SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(items: Any, *, next_url: str | None = None, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(items).encode()
    if next_url:
        resp.headers["Link"] = f'<{next_url}>; rel="next"'
    return resp


def _make_manager(resume_state: HuggingFaceResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's url+params AT SEND TIME.

    The paginator mutates the single ``Request`` in place across pages (setting ``request.url`` and
    clearing ``request.params`` for the next-page link), so inspect a snapshot at prepare time.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestBuildInitialParams:
    def test_models_params_are_scoped_sorted_and_full(self) -> None:
        params = _build_initial_params(HUGGING_FACE_ENDPOINTS["models"], author="huggingface")
        assert params["author"] == "huggingface"
        # createdAt is immutable, so ascending pages don't shift mid-sync.
        assert params["sort"] == "createdAt"
        assert params["direction"] == 1
        assert params["limit"] == 1000
        assert params["full"] == "true"

    @parameterized.expand([("models",), ("datasets",), ("spaces",)])
    def test_every_endpoint_is_scoped_to_author(self, endpoint: str) -> None:
        params = _build_initial_params(HUGGING_FACE_ENDPOINTS[endpoint], author="acme")
        assert params["author"] == "acme"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_link_header_pagination(self, MockSession) -> None:
        session = MockSession.return_value
        page2 = "https://huggingface.co/api/models?cursor=2"
        snapshots = _wire(
            session,
            [
                _response([{"id": "acme/a"}, {"id": "acme/b"}], next_url=page2),
                _response([{"id": "acme/c"}], next_url=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(
            hugging_face_source("hf_token", "models", "acme", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert [r["id"] for r in rows] == ["acme/a", "acme/b", "acme/c"]
        # First request is the scoped list endpoint; the second follows the self-contained next link.
        assert snapshots[0]["url"] == f"{HUGGING_FACE_BASE_URL}/api/models"
        assert snapshots[0]["params"]["author"] == "acme"
        assert snapshots[0]["params"]["limit"] == 1000
        assert snapshots[1]["url"] == page2
        assert snapshots[1]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_next_page_after_yield(self, MockSession) -> None:
        # Save the next page's self-contained link after yielding, so a resumed run continues there.
        session = MockSession.return_value
        page2 = "https://huggingface.co/api/models?cursor=2"
        _wire(session, [_response([{"id": "acme/a"}], next_url=page2), _response([{"id": "acme/b"}], next_url=None)])

        manager = _make_manager()
        _rows(
            hugging_face_source("hf_token", "models", "acme", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        # Only the first page has a next link, so exactly one checkpoint — pointing at the next page.
        assert manager.save_state.call_count == 1
        assert manager.save_state.call_args.args[0] == HuggingFaceResumeConfig(resume_url=page2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "acme/a"}, {"id": "acme/b"}], next_url=None)])

        manager = _make_manager()
        rows = _rows(
            hugging_face_source("hf_token", "models", "acme", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert [r["id"] for r in rows] == ["acme/a", "acme/b"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession) -> None:
        session = MockSession.return_value
        page2 = "https://huggingface.co/api/models?cursor=2"
        snapshots = _wire(session, [_response([{"id": "acme/b"}], next_url=None)])

        manager = _make_manager(HuggingFaceResumeConfig(resume_url=page2))
        rows = _rows(
            hugging_face_source("hf_token", "models", "acme", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        # Resuming starts at the saved page and skips the already-synced first page.
        assert [r["id"] for r in rows] == ["acme/b"]
        assert snapshots[0]["url"] == page2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates_even_with_next_link(self, MockSession) -> None:
        # An empty page ends the stream even if a stray next link is present (no unbounded loop).
        session = MockSession.return_value
        _wire(session, [_response([], next_url="https://huggingface.co/api/datasets?cursor=2")])

        manager = _make_manager()
        rows = _rows(
            hugging_face_source("hf_token", "datasets", "acme", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert rows == []
        assert session.send.call_count == 1


class TestRetries:
    @mock.patch(TENACITY_SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status=429), _response([{"id": "acme/a"}], next_url=None)])

        manager = _make_manager()
        rows = _rows(
            hugging_face_source("hf_token", "models", "acme", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert [r["id"] for r in rows] == ["acme/a"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unauthorized_raises_http_error(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "unauthorized"}, status=401)])

        manager = _make_manager()
        with pytest.raises(HTTPError):
            _rows(
                hugging_face_source(
                    "hf_token", "models", "acme", team_id=1, job_id="j", resumable_source_manager=manager
                )
            )


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(HF_SESSION_PATCH)
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("hf_token") is expected

    @mock.patch(HF_SESSION_PATCH)
    def test_network_error_is_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("hf_token") is False


class TestHuggingFaceSourceResponse:
    @parameterized.expand([("models",), ("datasets",), ("spaces",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], next_url=None)])

        response = hugging_face_source(
            "hf_token", endpoint, "acme", team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]
