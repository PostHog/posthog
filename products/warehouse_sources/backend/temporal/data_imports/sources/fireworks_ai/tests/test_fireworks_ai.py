import json
from collections.abc import Iterable
from typing import Any, cast

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai import fireworks_ai
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.fireworks_ai import (
    FIREWORKS_AI_BASE_URL,
    FireworksAIResumeConfig,
    fireworks_ai_source,
    get_status_code,
    normalize_account_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import (
    FIREWORKS_AI_ENDPOINTS,
    PAGE_SIZE,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: FireworksAIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session; capture each request's params and URL AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting it after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _rows(
    endpoint: str, responses: list[Response], manager: mock.MagicMock, account_id: str = "my-account"
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        params, urls = _wire(session, responses)
        source_response = fireworks_ai_source(
            api_key="fw_test",
            account_id=account_id,
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )
        rows = [row for page in cast("Iterable[Any]", source_response.items()) for row in page]
    return rows, params, urls


class TestNormalizeAccountId:
    @parameterized.expand(
        [
            ("bare_id", "my-account", "my-account"),
            ("resource_prefix", "accounts/my-account", "my-account"),
            ("whitespace_and_slashes", "  accounts/my-account/ ", "my-account"),
        ]
    )
    def test_reduces_input_to_bare_account_id(self, _name: str, entered: str, expected: str) -> None:
        assert normalize_account_id(entered) == expected


class TestPagination:
    def test_single_page_yields_rows_and_saves_no_state(self) -> None:
        manager = _make_manager()
        rows, params, urls = _rows("models", [_response({"models": [{"name": "m-1"}]})], manager)

        assert rows == [{"name": "m-1"}]
        assert urls[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/models"
        assert params[0] == {"pageSize": PAGE_SIZE}
        manager.save_state.assert_not_called()

    def test_follows_next_page_token_and_saves_state_after_each_page(self) -> None:
        manager = _make_manager()
        rows, params, _urls = _rows(
            "models",
            [
                _response({"models": [{"name": "m-1"}], "nextPageToken": "tok-2"}),
                _response({"models": [{"name": "m-2"}], "nextPageToken": "tok-3"}),
                _response({"models": [{"name": "m-3"}]}),
            ],
            manager,
        )

        assert rows == [{"name": "m-1"}, {"name": "m-2"}, {"name": "m-3"}]
        assert [p.get("pageToken") for p in params] == [None, "tok-2", "tok-3"]
        # State is saved after yielding each page (points at the next page), so a crash re-yields
        # the last page rather than skipping it. No save on the final (tokenless) page.
        saved = [call.args[0].page_token for call in manager.save_state.call_args_list]
        assert saved == ["tok-2", "tok-3"]

    def test_empty_next_page_token_terminates(self) -> None:
        manager = _make_manager()
        _rows_out, params, _urls = _rows(
            "models", [_response({"models": [{"name": "m-1"}], "nextPageToken": ""})], manager
        )
        assert len(params) == 1
        manager.save_state.assert_not_called()

    def test_resumes_from_saved_page_token(self) -> None:
        manager = _make_manager(FireworksAIResumeConfig(page_token="tok-9"))
        rows, params, _urls = _rows("models", [_response({"models": [{"name": "m-9"}]})], manager)

        assert rows == [{"name": "m-9"}]
        assert params[0] == {"pageSize": PAGE_SIZE, "pageToken": "tok-9"}

    def test_camel_case_collections_resolve_path_and_data_key(self) -> None:
        manager = _make_manager()
        rows, _params, urls = _rows(
            "supervised_fine_tuning_jobs",
            [_response({"supervisedFineTuningJobs": [{"name": "sft-1"}]})],
            manager,
        )

        assert rows == [{"name": "sft-1"}]
        assert urls[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/supervisedFineTuningJobs"

    def test_pasted_resource_prefix_does_not_double_the_path(self) -> None:
        manager = _make_manager()
        _rows_out, _params, urls = _rows(
            "models", [_response({"models": []})], manager, account_id="accounts/my-account"
        )
        assert urls[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/models"


class TestEmptyPages:
    @parameterized.expand(
        [
            # Proto3 JSON omits empty repeated fields — a missing collection key is an empty page.
            ("collection_key_omitted", {"totalSize": 0}),
            ("empty_collection", {"models": []}),
        ]
    )
    def test_empty_page_yields_no_rows(self, _name: str, body: dict[str, Any]) -> None:
        manager = _make_manager()
        rows, params, _urls = _rows("models", [_response(body)], manager)
        assert rows == []
        assert len(params) == 1
        manager.save_state.assert_not_called()


class TestGetStatusCode:
    def test_default_probe_hits_models_with_bearer_auth(self) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch.object(fireworks_ai, "make_tracked_session", return_value=session):
            status = get_status_code("fw_test", "my-account")

        assert status == 200
        args, kwargs = session.get.call_args
        assert args[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/models"
        assert kwargs["params"] == {"pageSize": 1}
        assert kwargs["headers"]["Authorization"] == "Bearer fw_test"

    def test_schema_probe_hits_that_endpoints_path(self) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch.object(fireworks_ai, "make_tracked_session", return_value=session):
            get_status_code("fw_test", "my-account", "evaluation_jobs")

        args, _kwargs = session.get.call_args
        assert args[0] == f"{FIREWORKS_AI_BASE_URL}/accounts/my-account/evaluationJobs"


class TestFireworksAISourceResponse:
    @parameterized.expand(list(FIREWORKS_AI_ENDPOINTS.keys()))
    def test_source_response_uses_endpoint_primary_keys_and_stable_partition(self, endpoint: str) -> None:
        response = fireworks_ai_source(
            api_key="fw_test",
            account_id="my-account",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )
        cfg = FIREWORKS_AI_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        # Partition on the stable creation timestamp — never updateTime — so partitions
        # don't rewrite on every sync.
        assert response.partition_keys == [cfg.partition_key]
        assert response.partition_mode == "datetime"
