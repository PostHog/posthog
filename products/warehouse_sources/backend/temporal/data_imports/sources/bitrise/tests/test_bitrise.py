import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.bitrise import (
    INCREMENTAL_LOOKBACK,
    BitriseResumeConfig,
    _build_after_param,
    _to_unix_timestamp,
    bitrise_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.settings import (
    BITRISE_ENDPOINTS,
    ENDPOINTS,
)

# The RESTClient builds its session via make_tracked_session in the rest_client module (bitrise
# supplies framework auth, not a pre-built session).
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own probe session in the bitrise module.
BITRISE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.bitrise.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume: BitriseResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: mock.MagicMock, responses: list[Response] | Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session; snapshot each request's query params and URL AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so a copy must be taken when
    each request is prepared rather than inspecting the final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        prepared = mock.MagicMock()
        prepared.url = request.url
        prepared.is_redirect = False
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return bitrise_source("token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


class TestToUnixTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), 1767323045),
            (datetime(2026, 1, 2, 3, 4, 5), 1767323045),
            (date(2026, 1, 2), 1767312000),
            ("2026-01-02T03:04:05Z", 1767323045),
            ("2026-01-02T03:04:05+00:00", 1767323045),
            (1767323045, 1767323045),
            ("not-a-date", None),
        ],
    )
    def test_conversion(self, value, expected):
        assert _to_unix_timestamp(value) == expected


class TestBuildAfterParam:
    def test_subtracts_lookback_from_watermark(self):
        watermark = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        after = _build_after_param(True, watermark)
        assert after == 1767323045 - int(INCREMENTAL_LOOKBACK.total_seconds())

    @pytest.mark.parametrize(
        "should_use_incremental_field, last_value",
        [
            (False, datetime(2026, 1, 2, tzinfo=UTC)),
            (True, None),
            (True, "garbage"),
        ],
    )
    def test_no_filter_when_not_incremental(self, should_use_incremental_field, last_value):
        assert _build_after_param(should_use_incremental_field, last_value) is None


class TestValidateCredentials:
    @mock.patch(BITRISE_SESSION_PATCH)
    def test_valid_personal_access_token(self, mock_session):
        mock_session.return_value.get.return_value = _response({"data": {}})
        assert validate_credentials("token") is True
        # /me succeeded, no fallback probe needed.
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(BITRISE_SESSION_PATCH)
    def test_workspace_token_falls_back_to_apps_probe(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"message": "Unauthorized"}, status_code=401),
            _response({"data": []}),
        ]
        assert validate_credentials("workspace-token") is True

    @mock.patch(BITRISE_SESSION_PATCH)
    def test_invalid_token(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"message": "Unauthorized"}, status_code=401),
            _response({"message": "Unauthorized"}, status_code=401),
        ]
        assert validate_credentials("bad") is False

    @mock.patch(BITRISE_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestApps:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_next_anchor_and_saves_state(self, MockSession):
        session = MockSession.return_value
        params, _urls = _wire(
            session,
            [
                _response({"data": [{"slug": "app1"}], "paging": {"next": "anchor1"}}),
                _response({"data": [{"slug": "app2"}], "paging": {}}),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("apps", manager))

        assert [row["slug"] for row in rows] == ["app1", "app2"]
        # The second page carries the anchor returned by the first.
        assert params[1]["next"] == "anchor1"
        # State saved once, after the first page yielded and only while more pages remain.
        assert [call.args[0] for call in manager.save_state.call_args_list] == [BitriseResumeConfig(next="anchor1")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_anchor(self, MockSession):
        session = MockSession.return_value
        params, _urls = _wire(session, [_response({"data": [{"slug": "app3"}], "paging": {}})])
        manager = _make_manager(BitriseResumeConfig(next="anchor2"))

        rows = _rows(_source("apps", manager))

        assert [row["slug"] for row in rows] == ["app3"]
        assert params[0]["next"] == "anchor2"


class TestBuilds:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_apps_and_injects_app_slug(self, MockSession):
        session = MockSession.return_value
        params, urls = _wire(
            session,
            [
                _response({"data": [{"slug": "app1"}, {"slug": "app2"}], "paging": {}}),
                _response({"data": [{"slug": "b1", "triggered_at": "2026-01-01T00:00:00Z"}], "paging": {}}),
                _response({"data": [{"slug": "b2", "triggered_at": "2026-01-02T00:00:00Z"}], "paging": {}}),
            ],
        )

        rows = _rows(_source("builds", _make_manager()))

        assert [(row["slug"], row["app_slug"]) for row in rows] == [("b1", "app1"), ("b2", "app2")]
        assert urls[1].endswith("/apps/app1/builds")
        assert urls[2].endswith("/apps/app2/builds")
        # The parent app slug binds the path, not the query string.
        assert params[1]["sort_by"] == "created_at"
        assert "app_slug" not in params[1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_passes_after_param(self, MockSession):
        session = MockSession.return_value
        params, _urls = _wire(
            session,
            [
                _response({"data": [{"slug": "app1"}], "paging": {}}),
                _response({"data": [], "paging": {}}),
            ],
        )

        _rows(
            _source(
                "builds",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )

        expected = int(datetime(2026, 1, 2, tzinfo=UTC).timestamp()) - int(INCREMENTAL_LOOKBACK.total_seconds())
        assert params[1]["after"] == expected

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_has_no_after_param(self, MockSession):
        session = MockSession.return_value
        params, _urls = _wire(
            session,
            [
                _response({"data": [{"slug": "app1"}], "paging": {}}),
                _response({"data": [], "paging": {}}),
            ],
        )

        _rows(_source("builds", _make_manager()))

        assert "after" not in params[1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_page_anchor_within_app_and_bookmark_between_apps(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"data": [{"slug": "app1"}, {"slug": "app2"}], "paging": {}}),
                _response({"data": [{"slug": "b1"}], "paging": {"next": "page2"}}),
                _response({"data": [{"slug": "b2"}], "paging": {}}),
                _response({"data": [{"slug": "b3"}], "paging": {}}),
            ],
        )
        manager = _make_manager()

        _rows(_source("builds", manager))

        saved = [call.args[0].fanout_state for call in manager.save_state.call_args_list]
        # A page anchor is checkpointed mid-way through app1 (resume the in-progress app's paging).
        assert {"completed": [], "current": "/apps/app1/builds", "child_state": {"cursor": "page2"}} in saved
        # app1 is bookmarked as completed once finished (skip it on a restart).
        assert any(state["completed"] == ["/apps/app1/builds"] for state in saved)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_bookmarked_app(self, MockSession):
        session = MockSession.return_value
        params, urls = _wire(
            session,
            [
                _response({"data": [{"slug": "app1"}, {"slug": "app2"}], "paging": {}}),
                _response({"data": [{"slug": "b9"}], "paging": {}}),
            ],
        )
        manager = _make_manager(
            BitriseResumeConfig(
                fanout_state={
                    "completed": ["/apps/app1/builds"],
                    "current": "/apps/app2/builds",
                    "child_state": {"cursor": "page3"},
                }
            )
        )

        rows = _rows(_source("builds", manager))

        # app1 is skipped entirely; app2 resumes from its saved page anchor.
        assert [(row["slug"], row["app_slug"]) for row in rows] == [("b9", "app2")]
        assert not any(url.endswith("/apps/app1/builds") for url in urls)
        assert urls[1].endswith("/apps/app2/builds")
        assert params[1]["next"] == "page3"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pre_migration_bookmark_restarts_from_first_app(self, MockSession):
        session = MockSession.return_value
        params, urls = _wire(
            session,
            [
                _response({"data": [{"slug": "app1"}], "paging": {}}),
                _response({"data": [{"slug": "b1"}], "paging": {}}),
            ],
        )
        # Old-shape state (positional app bookmark, no fan-out snapshot) can't be reconstructed, so the
        # fan-out restarts from the first app on a fresh first page.
        manager = _make_manager(BitriseResumeConfig(app_slug="deleted-app", next="page9"))

        rows = _rows(_source("builds", manager))

        assert [row["app_slug"] for row in rows] == ["app1"]
        assert urls[1].endswith("/apps/app1/builds")
        assert "next" not in params[1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_deleted_app_404_is_skipped(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"data": [{"slug": "app1"}, {"slug": "app2"}], "paging": {}}),
                _response({"message": "Not Found"}, status_code=404),
                _response({"data": [{"slug": "b2"}], "paging": {}}),
            ],
        )

        rows = _rows(_source("builds", _make_manager()))

        assert [(row["slug"], row["app_slug"]) for row in rows] == [("b2", "app2")]


class TestWorkflows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_maps_workflow_names_to_rows(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"data": [{"slug": "app1"}], "paging": {}}),
                _response({"data": ["primary", "deploy"]}),
            ],
        )

        rows = _rows(_source("workflows", _make_manager()))

        assert rows == [
            {"app_slug": "app1", "workflow": "primary"},
            {"app_slug": "app1", "workflow": "deploy"},
        ]


class TestArtifacts:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_builds_and_injects_parent_identifiers(self, MockSession):
        session = MockSession.return_value
        _params, urls = _wire(
            session,
            [
                _response({"data": [{"slug": "app1"}], "paging": {}}),
                _response({"data": [{"slug": "b1", "triggered_at": "2026-01-01T00:00:00Z"}], "paging": {}}),
                _response({"data": [{"slug": "art1", "title": "app.ipa"}], "paging": {}}),
            ],
        )

        rows = _rows(_source("artifacts", _make_manager()))

        assert rows == [
            {
                "slug": "art1",
                "title": "app.ipa",
                "app_slug": "app1",
                "build_slug": "b1",
                "build_triggered_at": "2026-01-01T00:00:00Z",
            }
        ]
        assert urls[2].endswith("/apps/app1/builds/b1/artifacts")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filters_parent_builds(self, MockSession):
        session = MockSession.return_value
        params, _urls = _wire(
            session,
            [
                _response({"data": [{"slug": "app1"}], "paging": {}}),
                _response({"data": [], "paging": {}}),
            ],
        )

        _rows(
            _source(
                "artifacts",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )

        # The `after` filter is applied at the parent builds level, not the artifact listing.
        assert "after" in params[1]


class TestUnknownEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_value_error(self, _MockSession):
        with pytest.raises(ValueError):
            _rows(_source("nope", _make_manager()))


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = BITRISE_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Fan-out + newest-first ordering: the watermark must only persist at job end.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    def test_fan_out_endpoints_have_parent_in_primary_key(self):
        assert BITRISE_ENDPOINTS["builds"].primary_keys == ["app_slug", "slug"]
        assert BITRISE_ENDPOINTS["workflows"].primary_keys == ["app_slug", "workflow"]
        assert BITRISE_ENDPOINTS["artifacts"].primary_keys == ["app_slug", "build_slug", "slug"]
