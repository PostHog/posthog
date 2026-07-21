import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.env0.env0 import (
    PAGE_SIZE,
    Env0ResumeConfig,
    _build_date_window_params,
    env0_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.settings import ENDPOINTS, ENV0_ENDPOINTS

# RESTClient uses the session env0_source passes it, which env0 builds via make_tracked_session; both
# the client session and the validate_credentials probe resolve to this one patched factory.
MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.env0.env0"
SESSION_PATCH = f"{MODULE}.make_tracked_session"


def _response(payload: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(payload).encode()
    resp.url = "https://api.env0.com/probe"
    resp.reason = "Error"
    return resp


def _make_manager(resume_state: Env0ResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, routes: list[tuple[str, Response]]) -> list[str]:
    """Dispatch each request to the first still-unconsumed route whose substring appears in the
    fully-prepared URL. Real ``Request.prepare()`` builds the URL (merging the path-embedded query
    with the params dict and applying Basic auth) so fan-out and pagination route deterministically.
    Returns the URLs sent, in order."""
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


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return env0_source(
        "key-id", "key-secret", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestBuildDateWindowParams:
    def test_incremental_deployments_sends_from_and_to_date_together(self):
        watermark = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        params = _build_date_window_params(ENV0_ENDPOINTS["deployments"], True, watermark)

        # env0 rejects fromDate without toDate, so both must always be present together.
        assert params["fromDate"] == "2026-05-31T12:00:00.000Z"  # watermark minus the 24h lookback
        assert params["toDate"].endswith("Z")

    @pytest.mark.parametrize(
        "endpoint, should_use_incremental_field, last_value",
        [
            ("deployments", True, None),
            ("deployments", False, datetime(2026, 6, 1, tzinfo=UTC)),
            ("environments", True, datetime(2026, 6, 1, tzinfo=UTC)),
        ],
    )
    def test_no_window_without_watermark_or_support(self, endpoint, should_use_incremental_field, last_value):
        assert _build_date_window_params(ENV0_ENDPOINTS[endpoint], should_use_incremental_field, last_value) == {}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key-id", "key-secret") is expected

    @mock.patch(SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key-id", "key-secret") is False


class TestGetRows:
    @mock.patch(SESSION_PATCH)
    def test_root_endpoint_fetches_once(self, mock_session):
        session = mock_session.return_value
        urls = _wire(session, [("env0.com/organizations", _response([{"id": "org-1"}, {"id": "org-2"}]))])

        manager = _make_manager()
        rows = _rows(_source("organizations", manager))

        assert [row["id"] for row in rows] == ["org-1", "org-2"]
        assert len(urls) == 1
        manager.save_state.assert_not_called()

    @mock.patch(SESSION_PATCH)
    def test_org_scoped_endpoint_fans_out_over_organizations(self, mock_session):
        session = mock_session.return_value
        urls = _wire(
            session,
            [
                ("env0.com/organizations", _response([{"id": "org-1"}, {"id": "org-2"}])),
                ("organizationId=org-1", _response([{"id": "proj-1"}])),
                ("organizationId=org-2", _response([{"id": "proj-2"}])),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("projects", manager))

        assert [row["id"] for row in rows] == ["proj-1", "proj-2"]
        assert _query(urls[1])["organizationId"] == ["org-1"]
        assert _query(urls[2])["organizationId"] == ["org-2"]
        # Single-hop fan-out keeps resume: the dependent resource checkpoints per-parent progress.
        assert manager.save_state.called
        assert "completed" in manager.save_state.call_args.args[0].paginator_state

    @mock.patch(SESSION_PATCH)
    def test_offset_pagination_advances_until_short_page(self, mock_session):
        session = mock_session.return_value
        full_page = [{"id": f"env-{i}"} for i in range(PAGE_SIZE)]
        urls = _wire(
            session,
            [
                ("env0.com/organizations", _response([{"id": "org-1"}])),
                # latestDeploymentLog embeds deployment variables and injected tokens; it must be
                # dropped even when the server ignores the excludeFields param.
                (
                    "offset=100",
                    _response(
                        [{"id": "env-last", "latestDeploymentLog": {"customEnv0EnvironmentVariables": {"o": "x"}}}]
                    ),
                ),
                ("organizationId=org-1", _response(full_page)),
            ],
        )

        rows = _rows(_source("environments", _make_manager()))

        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1] == {"id": "env-last"}
        # The full first page advances the offset to 100; the short page then terminates.
        first_page = next(url for url in urls if "organizationId=org-1" in url and "offset=100" not in url)
        second_page = next(url for url in urls if "offset=100" in url)
        assert _query(first_page)["offset"] == ["0"]
        assert _query(second_page)["offset"] == ["100"]
        # excludeFields is sent on every environments request even though the field is also stripped.
        assert _query(second_page)["excludeFields"] == ["latestDeploymentLog"]

    @mock.patch(SESSION_PATCH)
    def test_teams_pagination_follows_next_page_key(self, mock_session):
        session = mock_session.return_value
        urls = _wire(
            session,
            [
                ("env0.com/organizations", _response([{"id": "org-1"}])),
                ("offset=key-abc", _response({"teams": [{"id": "team-2"}]})),
                ("/teams/organizations/org-1", _response({"teams": [{"id": "team-1"}], "nextPageKey": "key-abc"})),
            ],
        )

        rows = _rows(_source("teams", _make_manager()))

        assert [row["id"] for row in rows] == ["team-1", "team-2"]
        second_teams = next(url for url in urls if "offset=key-abc" in url)
        assert _query(second_teams)["offset"] == ["key-abc"]

    @mock.patch(SESSION_PATCH)
    def test_deployments_fan_out_strips_heavy_and_secret_fields_and_windows_requests(self, mock_session):
        session = mock_session.return_value
        deployment = {
            "id": "dep-1",
            "status": "SUCCESS",
            "output": "x" * 100,
            "plan": {"big": True},
            "variables": [{"name": "DB_PASSWORD", "value": "hunter2", "isSensitive": False}],
            "customEnv0EnvironmentVariables": {"oidcToken": "eyJ...", "vcsAccessToken": "ghs_..."},
        }
        urls = _wire(
            session,
            [
                ("env0.com/organizations", _response([{"id": "org-1"}])),
                ("organizationId=org-1", _response([{"id": "env-1"}])),
                ("/environments/env-1/deployments", _response([deployment])),
            ],
        )

        manager = _make_manager()
        watermark = datetime(2026, 6, 1, tzinfo=UTC)
        rows = _rows(
            _source(
                "deployments",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )
        )

        assert rows == [{"id": "dep-1", "status": "SUCCESS"}]
        deployments_query = _query(next(url for url in urls if "/deployments" in url))
        assert deployments_query["fromDate"] == ["2026-05-31T00:00:00.000Z"]
        assert "toDate" in deployments_query
        # Multi-level fan-out disables resume (one shared hook can't checkpoint two levels).
        manager.save_state.assert_not_called()

    @mock.patch(SESSION_PATCH)
    def test_costs_inject_environment_id_and_skip_404s(self, mock_session):
        session = mock_session.return_value
        _wire(
            session,
            [
                ("env0.com/organizations", _response([{"id": "org-1"}])),
                ("organizationId=org-1", _response([{"id": "env-1"}, {"id": "env-2"}])),
                # env-1 has no cost monitoring configured.
                ("/costs/environments/env-1", _response({"message": "not found"}, status_code=404)),
                ("/costs/environments/env-2", _response([{"date": "2026-06-01", "total": 12.5}])),
            ],
        )

        rows = _rows(_source("environment_costs", _make_manager()))

        assert rows == [{"date": "2026-06-01", "total": 12.5, "environment_id": "env-2"}]

    @mock.patch(SESSION_PATCH)
    def test_non_404_error_fails_the_sync(self, mock_session):
        session = mock_session.return_value
        _wire(
            session,
            [
                ("env0.com/organizations", _response([{"id": "org-1"}])),
                ("organizationId=org-1", _response([{"id": "env-1"}])),
                ("/costs/environments/env-1", _response({"message": "forbidden"}, status_code=403)),
            ],
        )

        with pytest.raises(requests.HTTPError):
            _rows(_source("environment_costs", _make_manager()))

    @mock.patch(SESSION_PATCH)
    def test_resume_skips_already_processed_parents(self, mock_session):
        session = mock_session.return_value
        urls = _wire(
            session,
            [
                ("env0.com/organizations", _response([{"id": "org-1"}, {"id": "org-2"}])),
                ("organizationId=org-2", _response([{"id": "proj-2"}])),
            ],
        )

        # org-1's child page is already checkpointed as completed, so only org-2 is fetched.
        manager = _make_manager(
            Env0ResumeConfig(paginator_state={"completed": ["/projects?organizationId=org-1"], "current": None})
        )
        rows = _rows(_source("projects", manager))

        assert [row["id"] for row in rows] == ["proj-2"]
        assert len(urls) == 2
        assert _query(urls[1])["organizationId"] == ["org-2"]

    @mock.patch(SESSION_PATCH)
    def test_resume_offset_applies_only_to_bookmarked_parent(self, mock_session):
        session = mock_session.return_value
        urls = _wire(
            session,
            [
                ("env0.com/organizations", _response([{"id": "org-1"}, {"id": "org-2"}])),
                ("organizationId=org-1", _response([{"id": "env-9"}])),
                ("organizationId=org-2", _response([{"id": "env-10"}])),
            ],
        )

        manager = _make_manager(
            Env0ResumeConfig(
                paginator_state={
                    "completed": [],
                    "current": "/environments?organizationId=org-1",
                    "child_state": {"offset": 200},
                }
            )
        )
        _rows(_source("environments", manager))

        org1_url = next(url for url in urls if "organizationId=org-1" in url)
        org2_url = next(url for url in urls if "organizationId=org-2" in url)
        assert _query(org1_url)["offset"] == ["200"]
        # The next parent starts a fresh page chain from offset 0.
        assert _query(org2_url)["offset"] == ["0"]

    @mock.patch(SESSION_PATCH)
    def test_legacy_resume_state_starts_over(self, mock_session):
        session = mock_session.return_value
        urls = _wire(
            session,
            [
                ("env0.com/organizations", _response([{"id": "org-1"}])),
                ("organizationId=org-1", _response([{"id": "proj-1"}])),
            ],
        )

        # State written by the previous hand-rolled implementation still deserializes (compat) but
        # carries no framework paginator snapshot, so the sync restarts from the first parent.
        legacy = Env0ResumeConfig(parent_id="org-deleted", offset="100")
        assert legacy.paginator_state is None
        manager = _make_manager(legacy)
        rows = _rows(_source("projects", manager))

        assert [row["id"] for row in rows] == ["proj-1"]
        assert _query(urls[1])["organizationId"] == ["org-1"]


class TestEnv0SourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, mock_session, endpoint):
        _wire(mock_session.return_value, [])
        config = ENV0_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Unverified API ordering: incremental endpoints must persist their watermark only at
        # successful job end, which "desc" guarantees.
        assert response.sort_mode == ("desc" if config.incremental_fields else "asc")
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_fan_out_child_primary_keys_include_parent_id(self):
        # Cost rows have no globally-unique id of their own; without the environment id in the
        # key, rows from different environments on the same date would merge into one.
        assert ENV0_ENDPOINTS["environment_costs"].primary_keys == ["environment_id", "date"]

    @pytest.mark.parametrize("config", list(ENV0_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "createdAt"
