import json
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana import (
    ASANA_BASE_URL,
    AsanaResumeConfig,
    asana_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asana.settings import ASANA_ENDPOINTS, ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the asana module.
ASANA_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana.make_tracked_session"
)


def _page(items: list[dict[str, Any]], next_uri: Optional[str] = None) -> Response:
    body: dict[str, Any] = {"data": items, "next_page": {"uri": next_uri, "offset": "tok"} if next_uri else None}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: Optional[AsanaResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, routes: list[tuple[str, Response]]) -> list[str]:
    """Wire a mock session that dispatches each request to the first still-unconsumed route whose
    substring appears in the fully-prepared URL. Returns the list of URLs sent, in order.

    Real ``Request.prepare()`` builds the URL (merging path-embedded query with the params dict and
    applying Bearer auth) so fan-out over parents and multi-page pagination route deterministically.
    """
    session.headers = {}
    sent_urls: list[str] = []
    remaining = list(routes)

    def _prepare(request: Any) -> Any:
        return request.prepare()

    def _send(prepared: Any, **kwargs: Any) -> Response:
        sent_urls.append(prepared.url)
        for i, (substr, response) in enumerate(remaining):
            if substr in prepared.url:
                remaining.pop(i)
                return response
        raise AssertionError(f"no route for {prepared.url}")

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return sent_urls


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock) -> Any:
    return asana_source("token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_next_page_uri_and_checkpoints(self, MockSession) -> None:
        session = MockSession.return_value
        next_uri = f"{ASANA_BASE_URL}/workspaces?offset=tok2"
        urls = _wire(
            session,
            [
                ("/workspaces?", _page([{"gid": "1"}, {"gid": "2"}], next_uri=next_uri)),
                ("offset=tok2", _page([{"gid": "3"}])),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("workspaces", manager))

        assert [r["gid"] for r in rows] == ["1", "2", "3"]
        # First request carries the page size and opted-in fields.
        assert "limit=100" in urls[0]
        assert "opt_fields=" in urls[0]
        # Checkpoint saved after the first page (points at the next link); the terminal page saves nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == AsanaResumeConfig(paginator_state={"next_url": next_uri})

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        urls = _wire(session, [("/workspaces", _page([{"gid": "1"}]))])

        manager = _make_manager()
        rows = _rows(_source("workspaces", manager))

        assert [r["gid"] for r in rows] == ["1"]
        assert len(urls) == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_nothing_and_saves_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [("/workspaces", _page([]))])

        manager = _make_manager()
        rows = _rows(_source("workspaces", manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = f"{ASANA_BASE_URL}/workspaces?offset=resume"
        urls = _wire(session, [("offset=resume", _page([{"gid": "9"}]))])

        manager = _make_manager(AsanaResumeConfig(paginator_state={"next_url": resume_url}))
        _rows(_source("workspaces", manager))

        assert urls[0] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_saved_state_starts_from_base_path(self, MockSession) -> None:
        session = MockSession.return_value
        urls = _wire(session, [("/workspaces", _page([{"gid": "1"}]))])

        # State written by the previous hand-rolled implementation deserializes (compat) but carries
        # no framework paginator snapshot, so the sync restarts from the base path (a re-fetch).
        legacy = AsanaResumeConfig(remaining_urls=[f"{ASANA_BASE_URL}/x"], current_url=f"{ASANA_BASE_URL}/y")
        assert legacy.paginator_state is None
        manager = _make_manager(legacy)
        _rows(_source("workspaces", manager))

        assert "offset=" not in urls[0]
        assert "/workspaces" in urls[0]


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_workspace_fan_out_drains_every_parent(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                ("/workspaces?", _page([{"gid": "W1"}, {"gid": "W2"}])),
                ("workspace=W1", _page([{"gid": "a"}])),
                ("workspace=W2", _page([{"gid": "b"}])),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("projects", manager))

        assert [r["gid"] for r in rows] == ["a", "b"]
        # Single-hop fan-out keeps resume: the dependent resource checkpoints per-parent progress.
        assert manager.save_state.called
        assert "completed" in manager.save_state.call_args.args[0].paginator_state

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_parents_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        urls = _wire(session, [("/workspaces", _page([]))])

        manager = _make_manager()
        rows = _rows(_source("projects", manager))

        assert rows == []
        assert len(urls) == 1  # only the (empty) parent list is fetched
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_organization_fan_out_skips_non_org_workspaces(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire(
            session,
            [
                (
                    "/workspaces?",
                    _page([{"gid": "W1", "is_organization": True}, {"gid": "W2", "is_organization": False}]),
                ),
                ("/organizations/W1/teams", _page([{"gid": "team1"}])),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("teams", manager))

        assert [r["gid"] for r in rows] == ["team1"]
        # The non-organization workspace never triggers a teams request.
        assert not any("/organizations/W2/" in url for url in sent)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_project_level_chain_yields_grandchild_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                ("/workspaces?", _page([{"gid": "W1"}])),
                ("workspace=W1", _page([{"gid": "P1"}, {"gid": "P2"}])),
                ("project=P1", _page([{"gid": "t1"}])),
                ("project=P2", _page([{"gid": "t2"}])),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("tasks", manager))

        assert [r["gid"] for r in rows] == ["t1", "t2"]
        # Multi-level fan-out disables resume (one shared hook can't checkpoint two levels);
        # retries re-fetch and the merge dedupes on gid.
        manager.save_state.assert_not_called()


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(ASANA_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response
        assert validate_credentials("token") is expected

    @mock.patch(ASANA_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestAsanaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint) -> None:
        config = ASANA_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ["gid"]
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(ASANA_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config) -> None:
        if config.partition_key:
            assert config.partition_key == "created_at"
            # The partition field must be opted into the response, else partitioning fails.
            assert config.partition_key in config.opt_fields
