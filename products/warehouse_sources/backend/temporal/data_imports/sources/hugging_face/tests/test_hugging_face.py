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


def _route(session: mock.MagicMock, routes: dict[tuple[str, int | None], Response]) -> list[tuple[str, Any]]:
    """Wire a mock session that answers by URL and ``p`` page param; return the requests sent, in order."""
    session.headers = {}
    sent: list[tuple[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        prepared = mock.MagicMock()
        prepared.key = (request.url, (request.params or {}).get("p"))
        return prepared

    def _send(prepared: Any, **_kwargs: Any) -> Response:
        sent.append(prepared.key)
        return routes[prepared.key]

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return sent


def _discussion(repo: str, repo_type: str, num: int) -> dict[str, Any]:
    return {"num": num, "repo": {"name": repo, "type": repo_type}, "createdAt": "2024-01-01T00:00:00.000Z"}


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

    @parameterized.expand(
        [("models", "author"), ("datasets", "author"), ("spaces", "author"), ("collections", "owner")]
    )
    def test_every_endpoint_is_scoped_to_author(self, endpoint: str, param: str) -> None:
        params = _build_initial_params(HUGGING_FACE_ENDPOINTS[endpoint], author="acme")
        assert params[param] == "acme"


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


class TestLikes:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_link_past_empty_page_and_flattens_repo(self, MockSession) -> None:
        # The Hub filters likes after paging, so an empty page can still carry a next link.
        session = MockSession.return_value
        page2 = "https://huggingface.co/api/users/acme/likes?cursor=2"
        page3 = "https://huggingface.co/api/users/acme/likes?cursor=3"
        snapshots = _wire(
            session,
            [
                _response([], next_url=page2),
                _response(
                    [{"createdAt": "2024-01-01T00:00:00.000Z", "repo": {"name": "x/y", "type": "model"}}],
                    next_url=page3,
                ),
                _response([{"createdAt": "2024-01-02T00:00:00.000Z", "repo": {"name": "x/y", "type": "dataset"}}]),
            ],
        )

        rows = _rows(
            hugging_face_source(
                "hf_token", "likes", "acme", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert snapshots[0]["url"] == f"{HUGGING_FACE_BASE_URL}/api/users/acme/likes"
        assert [(r["repo_type"], r["repo_name"]) for r in rows] == [("model", "x/y"), ("dataset", "x/y")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_organization_namespace_syncs_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "This user does not exist"}, status=404)])

        rows = _rows(
            hugging_face_source(
                "hf_token", "likes", "acme", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert rows == []


class TestTags:
    @parameterized.expand([("model_tags", "/api/models-tags-by-type"), ("dataset_tags", "/api/datasets-tags-by-type")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flattens_tags_grouped_by_type(self, endpoint: str, path: str, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response(
                    {
                        "library": [{"id": "pytorch", "label": "PyTorch", "type": "library"}],
                        "license": [
                            {"id": "license:mit", "label": "mit", "type": "license"},
                            {"id": "license:apache-2.0", "label": "apache-2.0", "type": "license"},
                        ],
                    }
                )
            ],
        )

        rows = _rows(
            hugging_face_source(
                "hf_token", endpoint, "acme", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert snapshots[0]["url"] == f"{HUGGING_FACE_BASE_URL}{path}"
        assert [(r["type"], r["id"]) for r in rows] == [
            ("library", "pytorch"),
            ("license", "license:mit"),
            ("license", "license:apache-2.0"),
        ]
        assert session.send.call_count == 1


class TestDiscussions:
    def _routes(self) -> dict[tuple[str, int | None], Response]:
        base = HUGGING_FACE_BASE_URL
        return {
            (f"{base}/api/models", None): _response([{"id": "acme/m1"}, {"id": "acme/m2"}]),
            (f"{base}/api/datasets", None): _response([{"id": "acme/d1"}]),
            (f"{base}/api/spaces", None): _response([]),
            (f"{base}/api/models/acme/m1/discussions", 0): _response(
                {
                    "discussions": [_discussion("acme/m1", "model", 3), _discussion("acme/m1", "model", 2)],
                    "count": 3,
                    "start": 0,
                }
            ),
            (f"{base}/api/models/acme/m1/discussions", 1): _response(
                {"discussions": [_discussion("acme/m1", "model", 1)], "count": 3, "start": 2}
            ),
            (f"{base}/api/models/acme/m2/discussions", 0): _response(
                {"error": "Discussions are disabled for this repo"}, status=403
            ),
            (f"{base}/api/datasets/acme/d1/discussions", 0): _response(
                {"discussions": [_discussion("acme/d1", "dataset", 1)], "count": 1, "start": 0}
            ),
        }

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_every_repo_kind(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _route(session, self._routes())

        rows = _rows(
            hugging_face_source(
                "hf_token", "discussions", "acme", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert [(r["repo_type"], r["repo_name"], r["num"]) for r in rows] == [
            ("model", "acme/m1", 3),
            ("model", "acme/m1", 2),
            ("model", "acme/m1", 1),
            ("dataset", "acme/d1", 1),
        ]
        # Pagination stops at the reported count, so no repo pays a trailing empty-page request.
        assert (f"{HUGGING_FACE_BASE_URL}/api/models/acme/m1/discussions", 2) not in sent
        assert (f"{HUGGING_FACE_BASE_URL}/api/datasets/acme/d1/discussions", 1) not in sent

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_repos_already_synced(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _route(session, self._routes())
        manager = _make_manager(
            HuggingFaceResumeConfig(
                fanout_state={"completed": ["/api/models/acme/m1/discussions"], "current": None, "child_state": None}
            )
        )

        rows = _rows(
            hugging_face_source(
                "hf_token", "discussions", "acme", team_id=1, job_id="j", resumable_source_manager=manager
            )
        )

        assert [(r["repo_name"], r["num"]) for r in rows] == [("acme/d1", 1)]
        assert not any(url.endswith("/acme/m1/discussions") for url, _ in sent)
        assert manager.save_state.call_args.args[0].fanout_state["completed"] == [
            "/api/datasets/acme/d1/discussions",
            "/api/models/acme/m1/discussions",
            "/api/models/acme/m2/discussions",
        ]


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
