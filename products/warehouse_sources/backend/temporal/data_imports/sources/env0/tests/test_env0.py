import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.env0.env0 import (
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


class TestGetRows:
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

    @pytest.mark.parametrize(
        "endpoint, parents_route, parents, uncovered_path, covered_path, parent_column",
        [
            (
                "environment_costs",
                "organizationId=org-1",
                [{"id": "env-1"}, {"id": "env-2"}],
                "/costs/environments/env-1",
                "/costs/environments/env-2",
                "environment_id",
            ),
            (
                "project_costs",
                "/projects?organizationId=org-1",
                [{"id": "proj-1"}, {"id": "proj-2"}],
                "/costs/projects/proj-1",
                "/costs/projects/proj-2",
                "project_id",
            ),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_costs_inject_the_parent_id_and_skip_404s(
        self, mock_session, endpoint, parents_route, parents, uncovered_path, covered_path, parent_column
    ):
        session = mock_session.return_value
        _wire(
            session,
            [
                ("env0.com/organizations", _response([{"id": "org-1"}])),
                (parents_route, _response(parents)),
                # The first parent has no cost monitoring configured.
                (uncovered_path, _response({"message": "not found"}, status_code=404)),
                (covered_path, _response([{"date": "2026-06-01", "total": 12.5}])),
            ],
        )

        rows = _rows(_source(endpoint, _make_manager()))

        assert rows == [{"date": "2026-06-01", "total": 12.5, parent_column: parents[1]["id"]}]

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


class TestFanOutShaping:
    @mock.patch(SESSION_PATCH)
    def test_organization_users_lifts_the_nested_user_onto_the_row(self, mock_session):
        session = mock_session.return_value
        urls = _wire(
            session,
            [
                ("env0.com/organizations", _response([{"id": "org-1"}])),
                (
                    "/organizations/org-1/users",
                    _response(
                        [
                            {
                                "user": {"user_id": "u-1", "email": "member@example.com"},
                                "role": "Admin",
                                "status": "Active",
                            }
                        ]
                    ),
                ),
            ],
        )

        rows = _rows(_source("organization_users", _make_manager()))

        # user_id is the row's identity and sits one level down, so a nested column would leave the
        # primary key unresolvable.
        assert rows == [
            {
                "user_id": "u-1",
                "email": "member@example.com",
                "role": "Admin",
                "status": "Active",
                "organization_id": "org-1",
            }
        ]
        assert _query(urls[1])["includeApiKeys"] == ["true"]

    @mock.patch(SESSION_PATCH)
    def test_deployment_resources_window_the_parent_walk_not_the_child(self, mock_session):
        session = mock_session.return_value
        urls = _wire(
            session,
            [
                ("env0.com/organizations", _response([{"id": "org-1"}])),
                ("/environments?organizationId=org-1", _response([{"id": "env-1"}])),
                (
                    "/environments/env-1/deployments",
                    _response([{"id": "dep-1", "startedAt": "2026-06-02T10:00:00.000Z"}]),
                ),
                (
                    "/environments/deployments/dep-1/resources",
                    _response([{"provider": "aws", "type": "aws_s3_bucket", "name": "logs", "mode": "managed"}]),
                ),
            ],
        )

        rows = _rows(
            _source(
                "deployment_resources",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            )
        )

        # moduleName is absent for root-module resources but is part of the key, and a NULL key part
        # never matches on merge.
        assert rows == [
            {
                "provider": "aws",
                "type": "aws_s3_bucket",
                "name": "logs",
                "mode": "managed",
                "moduleName": "",
                "deployment_id": "dep-1",
                "deployment_started_at": "2026-06-02T10:00:00.000Z",
            }
        ]
        deployments_query = _query(next(url for url in urls if url.endswith("/deployments") or "/deployments?" in url))
        assert deployments_query["fromDate"] == ["2026-05-31T00:00:00.000Z"]
        # The resources endpoint takes no time filter; only the parent walk is bounded.
        assert _query(next(url for url in urls if "/resources" in url)) == {}


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

    @pytest.mark.parametrize("config", [c for c in ENV0_ENDPOINTS.values() if c.inject_parent_fields])
    def test_fan_out_child_primary_keys_include_parent_id(self, config):
        # Fan-out rows carry no globally-unique id of their own; without the parent id in the key,
        # rows from different parents collapse into one and every later merge multi-matches them.
        assert config.inject_parent_fields["id"] in config.primary_keys
