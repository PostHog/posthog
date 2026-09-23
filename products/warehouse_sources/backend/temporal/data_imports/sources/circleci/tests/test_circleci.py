from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.circleci import (
    COMPONENTS_PAGE_SIZE,
    MAX_PIPELINE_PAGES,
    CircleCIResumeConfig,
    CircleCIRetryableError,
    _build_url,
    _rate_limit_sleep_seconds,
    circleci_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.settings import (
    CIRCLECI_ENDPOINTS,
    ENDPOINTS,
)

PATCH_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.circleci.circleci.make_tracked_session"
)


def _make_manager(resume_state: CircleCIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: dict[str, Any], status_code: int = 200, headers: dict[str, str] | None = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = headers or {}
    response.json.return_value = body
    return response


def _page(items: list[dict[str, Any]], next_token: str | None) -> dict[str, Any]:
    return {"items": items, "next_page_token": next_token}


def _route_session(mock_session: mock.MagicMock, routes: dict[str, Any]) -> None:
    """Route GET calls by path; values are either a body or a list of bodies consumed in order.

    A body that is itself a JSON array therefore has to be wrapped in a one-element list.
    """
    state: dict[str, int] = {}

    def get(url: str, **kwargs: Any) -> mock.MagicMock:
        parsed = urlparse(url)
        path = parsed.path
        body = routes[path]
        if isinstance(body, list):
            index = min(state.get(path, 0), len(body) - 1)
            state[path] = index + 1
            return _response(body[index])
        return _response(body)

    mock_session.return_value.get.side_effect = get


def _requested_urls(mock_session: mock.MagicMock) -> list[str]:
    return [call.args[0] for call in mock_session.return_value.get.call_args_list]


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/me") == "https://circleci.com/api/v2/me"

    def test_drops_none_values_and_encodes(self):
        url = _build_url("/pipeline", {"org-slug": "gh/posthog", "page-token": None})
        assert url == "https://circleci.com/api/v2/pipeline?org-slug=gh%2Fposthog"


class TestRateLimitSleep:
    @parameterized.expand(
        [
            ({"retry-after": "5"}, 5),
            ({"ratelimit-reset": "30"}, 30),
            ({"x-ratelimit-reset": "12"}, 12),
            ({"retry-after": "9999"}, 120),
            ({"retry-after": "-3"}, 0),
            ({"retry-after": "not-a-number"}, 0),
            ({}, 0),
        ]
    )
    def test_sleep_seconds_from_headers(self, headers, expected):
        response = mock.MagicMock()
        response.headers = headers
        assert _rate_limit_sleep_seconds(response) == expected

    def test_retry_after_preferred_over_ratelimit_reset(self):
        response = mock.MagicMock()
        response.headers = {"retry-after": "3", "ratelimit-reset": "60"}
        assert _rate_limit_sleep_seconds(response) == 3


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, 200, True),
            (401, None, False),
            (403, None, False),
            (200, 404, False),
            (200, 403, False),
        ]
    )
    @mock.patch(PATCH_SESSION)
    def test_status_mapping(self, me_status, pipeline_status, expected, mock_session):
        responses = [_response({}, status_code=me_status)]
        if pipeline_status is not None:
            responses.append(_response(_page([], None), status_code=pipeline_status))
        mock_session.return_value.get.side_effect = responses

        is_valid, error = validate_credentials("token", "gh/posthog")

        assert is_valid is expected
        assert (error is None) is expected

    @mock.patch(PATCH_SESSION)
    def test_skips_org_probe_without_org_slug(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=200)

        is_valid, error = validate_credentials("token", None)

        assert is_valid is True
        assert error is None
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(PATCH_SESSION)
    def test_invalid_org_message_mentions_slug(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=200),
            _response({}, status_code=404),
        ]

        is_valid, error = validate_credentials("token", "gh/nope")

        assert is_valid is False
        assert error is not None
        assert "gh/nope" in error

    @mock.patch(PATCH_SESSION)
    def test_swallows_connection_errors(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")

        is_valid, error = validate_credentials("token", "gh/posthog")

        assert is_valid is False
        assert error is not None

    @mock.patch(PATCH_SESSION)
    def test_sends_circle_token_header(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=200)

        validate_credentials("token", None)

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Circle-Token"] == "token"


class TestPipelinesRows:
    @mock.patch(PATCH_SESSION)
    def test_paginates_via_next_page_token(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/pipeline": [
                    _page([{"id": "p1"}, {"id": "p2"}], "token-2"),
                    _page([{"id": "p3"}], None),
                ]
            },
        )

        manager = _make_manager()
        batches = list(get_rows("token", "gh/posthog", "pipelines", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["p1", "p2", "p3"]
        urls = _requested_urls(mock_session)
        assert parse_qs(urlparse(urls[0]).query) == {"org-slug": ["gh/posthog"]}
        assert parse_qs(urlparse(urls[1]).query) == {"org-slug": ["gh/posthog"], "page-token": ["token-2"]}
        # State saved only while a next page exists, with the next page's token.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_page_token == "token-2"

    @mock.patch(PATCH_SESSION)
    def test_resumes_from_saved_state(self, mock_session):
        _route_session(mock_session, {"/api/v2/pipeline": [_page([{"id": "p9"}], None)]})

        manager = _make_manager(CircleCIResumeConfig(next_page_token="resume-token"))
        list(get_rows("token", "gh/posthog", "pipelines", mock.MagicMock(), manager))

        first_url = _requested_urls(mock_session)[0]
        assert parse_qs(urlparse(first_url).query)["page-token"] == ["resume-token"]

    @mock.patch(PATCH_SESSION)
    def test_state_saved_after_yield_not_before(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/pipeline": [
                    _page([{"id": "p1"}], "token-2"),
                    _page([], None),
                ]
            },
        )

        manager = _make_manager()
        rows = get_rows("token", "gh/posthog", "pipelines", mock.MagicMock(), manager)

        next(rows)
        manager.save_state.assert_not_called()
        with pytest.raises(StopIteration):
            next(rows)
        manager.save_state.assert_called_once()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.circleci.circleci.MAX_PIPELINE_PAGES", 2
    )
    @mock.patch(PATCH_SESSION)
    def test_page_cap_stops_pagination_and_logs(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/pipeline": [
                    _page([{"id": "p1"}], "t2"),
                    _page([{"id": "p2"}], "t3"),
                    _page([{"id": "p3"}], "t4"),
                ]
            },
        )
        logger = mock.MagicMock()

        manager = _make_manager()
        batches = list(get_rows("token", "gh/posthog", "pipelines", logger, manager))

        assert len(batches) == 2
        assert mock_session.return_value.get.call_count == 2
        logger.warning.assert_called_once()
        assert "page cap" in logger.warning.call_args.args[0]
        assert "pipelines" in logger.warning.call_args.args[0]

    @mock.patch(PATCH_SESSION)
    def test_empty_response_yields_nothing(self, mock_session):
        _route_session(mock_session, {"/api/v2/pipeline": _page([], None)})

        manager = _make_manager()
        batches = list(get_rows("token", "gh/posthog", "pipelines", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown CircleCI endpoint"):
            list(get_rows("token", "gh/posthog", "nope", mock.MagicMock(), _make_manager()))


class TestRetryBehavior:
    # Patch the sleep tenacity actually uses; the wait time is computed by `_retry_wait`, so a
    # single sleep of exactly `retry_after` proves we honor the header without double-waiting.
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(PATCH_SESSION)
    def test_429_honors_rate_limit_headers_then_retries(self, mock_session, mock_sleep):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=429, headers={"retry-after": "7"}),
            _response(_page([{"id": "p1"}], None)),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "gh/posthog", "pipelines", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["p1"]
        mock_sleep.assert_called_once_with(7)

    @mock.patch(PATCH_SESSION)
    def test_5xx_retries_then_succeeds(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=503),
            _response(_page([{"id": "p1"}], None)),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "gh/posthog", "pipelines", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["p1"]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.circleci.circleci.MAX_RETRIES", 2)
    @mock.patch(PATCH_SESSION)
    def test_persistent_5xx_raises_after_max_retries(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=500)

        with pytest.raises(CircleCIRetryableError):
            list(get_rows("token", "gh/posthog", "pipelines", mock.MagicMock(), _make_manager()))

    @mock.patch(PATCH_SESSION)
    def test_4xx_raises_immediately(self, mock_session):
        response = _response({}, status_code=401)
        response.raise_for_status.side_effect = Exception("401 Client Error")
        mock_session.return_value.get.return_value = response

        with pytest.raises(Exception, match="401 Client Error"):
            list(get_rows("token", "gh/posthog", "pipelines", mock.MagicMock(), _make_manager()))

        assert mock_session.return_value.get.call_count == 1


class TestWorkflowsFanOut:
    @mock.patch(PATCH_SESSION)
    def test_workflows_fetched_per_pipeline(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/pipeline": _page([{"id": "p1"}, {"id": "p2"}], None),
                "/api/v2/pipeline/p1/workflow": _page(
                    [{"id": "w1", "pipeline_id": "p1", "created_at": "2026-01-01T00:00:00Z"}], None
                ),
                "/api/v2/pipeline/p2/workflow": _page(
                    [{"id": "w2", "pipeline_id": "p2", "created_at": "2026-01-02T00:00:00Z"}], None
                ),
            },
        )

        batches = list(get_rows("token", "gh/posthog", "workflows", mock.MagicMock(), _make_manager()))
        rows = [row for batch in batches for row in batch]

        assert [row["id"] for row in rows] == ["w1", "w2"]
        # Workflow rows natively carry their parent pipeline identifier.
        assert [row["pipeline_id"] for row in rows] == ["p1", "p2"]

    @mock.patch(PATCH_SESSION)
    def test_workflow_pagination_per_pipeline(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/pipeline": _page([{"id": "p1"}], None),
                "/api/v2/pipeline/p1/workflow": [
                    _page([{"id": "w1", "pipeline_id": "p1"}], "wf-token"),
                    _page([{"id": "w2", "pipeline_id": "p1"}], None),
                ],
            },
        )

        batches = list(get_rows("token", "gh/posthog", "workflows", mock.MagicMock(), _make_manager()))

        assert [row["id"] for batch in batches for row in batch] == ["w1", "w2"]
        workflow_urls = [url for url in _requested_urls(mock_session) if "/workflow" in url]
        assert parse_qs(urlparse(workflow_urls[1]).query)["page-token"] == ["wf-token"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.circleci.circleci.MAX_WORKFLOW_PAGES_PER_PIPELINE",
        2,
    )
    @mock.patch(PATCH_SESSION)
    def test_child_page_cap_logs_and_moves_on(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/pipeline": _page([{"id": "p1"}], None),
                "/api/v2/pipeline/p1/workflow": [
                    _page([{"id": "wa", "pipeline_id": "p1"}], "t2"),
                    _page([{"id": "wb", "pipeline_id": "p1"}], "t3"),
                    _page([{"id": "wc", "pipeline_id": "p1"}], "t4"),
                ],
            },
        )
        logger = mock.MagicMock()

        batches = list(get_rows("token", "gh/posthog", "workflows", logger, _make_manager()))

        assert len([row for batch in batches for row in batch]) == 2
        logger.warning.assert_called_once()
        assert "page cap" in logger.warning.call_args.args[0]
        assert "p1" in logger.warning.call_args.args[0]

    @mock.patch(PATCH_SESSION)
    def test_saves_pipeline_scan_state_after_fanout_page(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/pipeline": [
                    _page([{"id": "p1"}], "pipeline-token-2"),
                    _page([], None),
                ],
                "/api/v2/pipeline/p1/workflow": _page([{"id": "w1", "pipeline_id": "p1"}], None),
            },
        )

        manager = _make_manager()
        list(get_rows("token", "gh/posthog", "workflows", mock.MagicMock(), manager))

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_page_token == "pipeline-token-2"


class TestJobsFanOut:
    @mock.patch(PATCH_SESSION)
    def test_job_rows_carry_parent_identifiers(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/pipeline": _page([{"id": "p1", "project_slug": "gh/posthog/posthog"}], None),
                "/api/v2/pipeline/p1/workflow": _page(
                    [{"id": "w1", "pipeline_id": "p1", "created_at": "2026-01-01T00:00:00Z"}], None
                ),
                "/api/v2/workflow/w1/job": _page(
                    [
                        {"id": "j1", "job_number": 42, "project_slug": "gh/posthog/posthog", "status": "success"},
                        {"id": "j2", "job_number": None, "project_slug": "gh/posthog/posthog", "status": "blocked"},
                    ],
                    None,
                ),
            },
        )

        batches = list(get_rows("token", "gh/posthog", "jobs", mock.MagicMock(), _make_manager()))
        rows = [row for batch in batches for row in batch]

        assert [row["id"] for row in rows] == ["j1", "j2"]
        for row in rows:
            assert row["pipeline_id"] == "p1"
            assert row["workflow_id"] == "w1"
            assert row["workflow_created_at"] == "2026-01-01T00:00:00Z"
            # Native job fields are preserved alongside the injected parent identifiers.
            assert row["project_slug"] == "gh/posthog/posthog"

    @mock.patch(PATCH_SESSION)
    def test_jobs_traverse_every_workflow_of_every_pipeline(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/pipeline": _page([{"id": "p1"}, {"id": "p2"}], None),
                "/api/v2/pipeline/p1/workflow": _page([{"id": "w1"}, {"id": "w2"}], None),
                "/api/v2/pipeline/p2/workflow": _page([{"id": "w3"}], None),
                "/api/v2/workflow/w1/job": _page([{"id": "j1"}], None),
                "/api/v2/workflow/w2/job": _page([{"id": "j2"}], None),
                "/api/v2/workflow/w3/job": _page([{"id": "j3"}], None),
            },
        )

        batches = list(get_rows("token", "gh/posthog", "jobs", mock.MagicMock(), _make_manager()))
        rows = [row for batch in batches for row in batch]

        assert [(row["id"], row["pipeline_id"], row["workflow_id"]) for row in rows] == [
            ("j1", "p1", "w1"),
            ("j2", "p1", "w2"),
            ("j3", "p2", "w3"),
        ]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.circleci.circleci.MAX_JOB_PAGES_PER_WORKFLOW",
        2,
    )
    @mock.patch(PATCH_SESSION)
    def test_job_page_cap_logs_workflow_identifier(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/pipeline": _page([{"id": "p1"}], None),
                "/api/v2/pipeline/p1/workflow": _page([{"id": "w1"}], None),
                "/api/v2/workflow/w1/job": [
                    _page([{"id": "ja"}], "t2"),
                    _page([{"id": "jb"}], "t3"),
                    _page([{"id": "jc"}], "t4"),
                ],
            },
        )
        logger = mock.MagicMock()

        batches = list(get_rows("token", "gh/posthog", "jobs", logger, _make_manager()))

        assert len([row for batch in batches for row in batch]) == 2
        logger.warning.assert_called_once()
        assert "page cap" in logger.warning.call_args.args[0]
        assert "w1" in logger.warning.call_args.args[0]


class TestProjectsRows:
    @mock.patch(PATCH_SESSION)
    def test_distinct_project_slugs_resolved_once(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/pipeline": _page(
                    [
                        {"id": "p1", "project_slug": "gh/posthog/posthog"},
                        {"id": "p2", "project_slug": "gh/posthog/posthog"},
                        {"id": "p3", "project_slug": "gh/posthog/posthog.com"},
                        {"id": "p4"},
                    ],
                    None,
                ),
                "/api/v2/project/gh/posthog/posthog": {"id": "proj-1", "slug": "gh/posthog/posthog"},
                "/api/v2/project/gh/posthog/posthog.com": {"id": "proj-2", "slug": "gh/posthog/posthog.com"},
            },
        )

        batches = list(get_rows("token", "gh/posthog", "projects", mock.MagicMock(), _make_manager()))
        rows = [row for batch in batches for row in batch]

        assert [row["id"] for row in rows] == ["proj-1", "proj-2"]
        project_urls = [url for url in _requested_urls(mock_session) if "/project/" in url]
        assert len(project_urls) == 2


COLLABORATIONS_PATH = "/api/v2/me/collaborations"
COLLABORATIONS = [[{"id": "org-uuid", "slug": "gh/posthog", "name": "PostHog"}]]


class TestComponentsRows:
    @mock.patch(PATCH_SESSION)
    def test_org_slug_resolved_to_org_id_and_paginated(self, mock_session):
        _route_session(
            mock_session,
            {
                COLLABORATIONS_PATH: COLLABORATIONS,
                "/api/v2/deploy/components": [
                    _page([{"id": "c1"}], "components-token-2"),
                    _page([{"id": "c2"}], None),
                ],
            },
        )

        manager = _make_manager()
        batches = list(get_rows("token", "gh/posthog", "components", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["c1", "c2"]
        component_urls = [url for url in _requested_urls(mock_session) if "/deploy/components" in url]
        assert parse_qs(urlparse(component_urls[0]).query) == {
            "org-id": ["org-uuid"],
            "page-size": [str(COMPONENTS_PAGE_SIZE)],
        }
        # The required page size is repeated on every page, not just the first.
        assert parse_qs(urlparse(component_urls[1]).query) == {
            "org-id": ["org-uuid"],
            "page-size": [str(COMPONENTS_PAGE_SIZE)],
            "page-token": ["components-token-2"],
        }
        assert manager.save_state.call_args.args[0].next_page_token == "components-token-2"

    @mock.patch(PATCH_SESSION)
    def test_resumes_from_saved_component_page_token(self, mock_session):
        _route_session(
            mock_session,
            {
                COLLABORATIONS_PATH: COLLABORATIONS,
                "/api/v2/deploy/components": [_page([{"id": "c9"}], None)],
            },
        )

        manager = _make_manager(CircleCIResumeConfig(next_page_token="resume-token"))
        list(get_rows("token", "gh/posthog", "components", mock.MagicMock(), manager))

        component_url = next(url for url in _requested_urls(mock_session) if "/deploy/components" in url)
        assert parse_qs(urlparse(component_url).query)["page-token"] == ["resume-token"]

    @parameterized.expand(
        [
            ("slug not visible to the token", [[{"id": "other-uuid", "slug": "gh/other"}]]),
            ("collaboration without an id", [[{"id": None, "slug": "gh/posthog"}]]),
        ]
    )
    @mock.patch(PATCH_SESSION)
    def test_unresolvable_org_raises_with_slug(self, _name, collaborations, mock_session):
        _route_session(mock_session, {COLLABORATIONS_PATH: collaborations})

        with pytest.raises(ValueError, match="gh/posthog"):
            list(get_rows("token", "gh/posthog", "components", mock.MagicMock(), _make_manager()))


class TestComponentVersionsFanOut:
    @mock.patch(PATCH_SESSION)
    def test_versions_carry_component_id_and_never_null_merge_keys(self, mock_session):
        _route_session(
            mock_session,
            {
                COLLABORATIONS_PATH: COLLABORATIONS,
                "/api/v2/deploy/components": _page([{"id": "c1"}, {"id": "c2"}], None),
                "/api/v2/deploy/components/c1/versions": _page(
                    [
                        {
                            "name": "1.0.0",
                            "environment_id": "env-1",
                            "namespace": "default",
                            "is_live": True,
                            "last_deployed_at": "2026-01-01T00:00:00Z",
                        },
                        {"name": "1.0.1", "environment_id": None},
                    ],
                    None,
                ),
                "/api/v2/deploy/components/c2/versions": _page([{"name": "2.0.0", "environment_id": "env-2"}], None),
            },
        )

        batches = list(get_rows("token", "gh/posthog", "component_versions", mock.MagicMock(), _make_manager()))
        rows = [row for batch in batches for row in batch]

        assert [(row["component_id"], row["name"]) for row in rows] == [
            ("c1", "1.0.0"),
            ("c1", "1.0.1"),
            ("c2", "2.0.0"),
        ]
        # Native fields survive the injection.
        assert rows[0]["is_live"] is True
        assert rows[0]["namespace"] == "default"
        # A missing part of the composite key becomes "" so merges match instead of re-inserting.
        assert rows[1]["environment_id"] == ""
        assert rows[1]["namespace"] == ""

    @mock.patch(PATCH_SESSION)
    def test_repeated_page_token_fails_the_run(self, mock_session):
        # The versions endpoint documents no page-token param; if it ignores ours it hands
        # back the same token forever. Truncating there would publish a partial table.
        _route_session(
            mock_session,
            {
                COLLABORATIONS_PATH: COLLABORATIONS,
                "/api/v2/deploy/components": _page([{"id": "c1"}], None),
                "/api/v2/deploy/components/c1/versions": _page([{"name": "1.0.0"}], "same-token"),
            },
        )

        with pytest.raises(ValueError, match="same page token twice"):
            list(get_rows("token", "gh/posthog", "component_versions", mock.MagicMock(), _make_manager()))


class TestUsersRows:
    @mock.patch(PATCH_SESSION)
    def test_distinct_actor_ids_resolved_once(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/pipeline": _page([{"id": "p1"}], None),
                "/api/v2/pipeline/p1/workflow": _page(
                    [
                        {"id": "w1", "started_by": "u1", "canceled_by": "u2"},
                        {"id": "w2", "started_by": "u1", "errored_by": "u3"},
                        {"id": "w3", "started_by": None},
                    ],
                    None,
                ),
                "/api/v2/user/u1": {"id": "u1", "login": "one"},
                "/api/v2/user/u2": {"id": "u2", "login": "two"},
                "/api/v2/user/u3": {"id": "u3", "login": "three"},
            },
        )

        batches = list(get_rows("token", "gh/posthog", "users", mock.MagicMock(), _make_manager()))

        assert [row["id"] for batch in batches for row in batch] == ["u1", "u2", "u3"]
        assert len([url for url in _requested_urls(mock_session) if "/user/" in url]) == 3

    @mock.patch(PATCH_SESSION)
    def test_deleted_actor_is_skipped(self, mock_session):
        missing = _response({}, status_code=404)
        missing.raise_for_status.side_effect = requests.HTTPError("404 Client Error", response=missing)
        bodies = {
            "/api/v2/pipeline": _page([{"id": "p1"}], None),
            "/api/v2/pipeline/p1/workflow": _page([{"id": "w1", "started_by": "gone", "canceled_by": "u2"}], None),
            "/api/v2/user/u2": {"id": "u2", "login": "two"},
        }

        def get(url: str, **kwargs: Any) -> mock.MagicMock:
            path = urlparse(url).path
            return missing if path == "/api/v2/user/gone" else _response(bodies[path])

        mock_session.return_value.get.side_effect = get

        batches = list(get_rows("token", "gh/posthog", "users", mock.MagicMock(), _make_manager()))

        assert [row["id"] for batch in batches for row in batch] == ["u2"]


class TestCircleCISourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CIRCLECI_ENDPOINTS[endpoint]
        response = circleci_source("token", "gh/posthog", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == list(config.primary_keys)
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @parameterized.expand([(config,) for config in CIRCLECI_ENDPOINTS.values()])
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"created_at", "workflow_created_at"}

    def test_pipeline_page_cap_is_bounded(self):
        assert MAX_PIPELINE_PAGES <= 1000
