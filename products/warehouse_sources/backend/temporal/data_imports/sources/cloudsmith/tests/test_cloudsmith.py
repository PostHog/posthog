from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.cloudsmith import (
    INVALID_WORKSPACE_ERROR,
    CloudsmithPaginator,
    CloudsmithResumeConfig,
    _cloudsmith_incremental_window,
    _format_uploaded_filter,
    cloudsmith_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.settings import CLOUDSMITH_ENDPOINTS


class _FakeResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


def _make_manager(resume_state: CloudsmithResumeConfig | None = None) -> Mock:
    manager = Mock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(page_total: str | None) -> Mock:
    response = Mock()
    response.headers = {} if page_total is None else {"X-Pagination-PageTotal": page_total}
    return response


class TestCloudsmithTransport:
    @parameterized.expand(
        [
            # Cloudsmith answers a page past the last one with 404, so the header - not an
            # empty page - has to be what stops the walk.
            ("more_pages", "3", 100, True),
            ("last_page", "1", 100, False),
            ("empty_page", "5", 0, False),
            # Header missing or unparseable: fall back to the short-page heuristic.
            ("no_header_full_page", None, 100, True),
            ("no_header_short_page", None, 42, False),
            ("garbage_header_full_page", "not-a-number", 100, True),
            ("garbage_header_short_page", "not-a-number", 7, False),
        ]
    )
    def test_paginator_termination(self, _name, page_total, row_count, expected_has_next) -> None:
        paginator = CloudsmithPaginator(page_size=100)
        request = Mock()
        request.params = {}
        paginator.init_request(request)
        assert request.params["page"] == 1

        data = [{"slug_perm": str(i)} for i in range(row_count)]
        paginator.update_state(_response(page_total), data=data)

        assert paginator.has_next_page is expected_has_next

    def test_paginator_advances_page_number(self) -> None:
        paginator = CloudsmithPaginator(page_size=100)
        request = Mock()
        request.params = {"sort": "date"}
        paginator.init_request(request)

        paginator.update_state(_response("3"), data=[{"slug_perm": str(i)} for i in range(100)])
        paginator.update_request(request)

        assert request.params["page"] == 2
        assert request.params["sort"] == "date"

    def test_paginator_stops_after_walking_every_page(self) -> None:
        # A full last page still has to stop the walk: requesting the page after it is a 404,
        # not an empty page, so the inherited empty-page check never gets a chance to fire.
        paginator = CloudsmithPaginator(page_size=100)
        full_page = [{"slug_perm": str(i)} for i in range(100)]

        paginator.update_state(_response("2"), data=full_page)
        assert paginator.has_next_page is True

        paginator.update_state(_response("2"), data=full_page)
        assert paginator.has_next_page is False

    def test_paginator_resume_state_roundtrip(self) -> None:
        paginator = CloudsmithPaginator(page_size=100)
        paginator.update_state(_response("9"), data=[{"slug_perm": str(i)} for i in range(100)])

        state = paginator.get_resume_state()
        assert state == {"page": 2}

        resumed = CloudsmithPaginator(page_size=100)
        resumed.set_resume_state(cast(dict[str, Any], state))
        request = Mock()
        request.params = {}
        resumed.init_request(request)
        assert request.params["page"] == 2

    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45, 999999), "uploaded:>=2026-03-01T12:30:45Z"),
            ("aware_datetime", datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC), "uploaded:>=2026-03-01T12:30:45Z"),
            ("passthrough_string", "1970-01-01T00:00:00Z", "uploaded:>=1970-01-01T00:00:00Z"),
        ]
    )
    def test_format_uploaded_filter(self, _name, value, expected) -> None:
        # Cloudsmith rejects an unparseable search expression with a 400, and truncating to
        # whole seconds keeps the lower bound inclusive rather than skipping a package
        # uploaded in the same second as the watermark.
        assert _format_uploaded_filter(value) == expected

    def test_incremental_window_filters_server_side_via_query(self) -> None:
        # The filter only bounds the fetched pages if it rides the `query` search param;
        # any other param name is silently ignored and every sync refetches everything.
        window = _cloudsmith_incremental_window("uploaded_at")
        assert window["start_param"] == "query"
        assert window["cursor_path"] == "uploaded_at"
        assert window["convert"] is _format_uploaded_filter
        assert window["initial_value"] == "1970-01-01T00:00:00Z"

    @parameterized.expand(
        [
            (200, None, True, None),
            (
                401,
                None,
                False,
                "Cloudsmith rejected the API key. Check the key in your Cloudsmith user settings and try again.",
            ),
            # A key only has access to some repositories, so a 403 must not block source
            # creation - only a per-table check.
            (403, None, True, None),
            (403, "packages", False, "Your Cloudsmith API key does not have permission to read this data."),
            (404, None, False, "Cloudsmith workspace 'acme' was not found, or this API key cannot see it."),
            (500, None, False, "Cloudsmith returned an unexpected response (HTTP 500)."),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.cloudsmith.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(
        self, status, schema_name, expected_valid, expected_message, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status)

        result = validate_credentials(api_key="key", workspace="acme", schema_name=schema_name)

        assert result == (expected_valid, expected_message)
        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.cloudsmith.io/v1/namespaces/acme/"
        assert call.kwargs["headers"]["X-Api-Key"] == "key"

    @parameterized.expand([("../../user", None), ("acme/repo", None), ("", None), ("with space", None)])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.cloudsmith.make_tracked_session"
    )
    def test_validate_credentials_rejects_unsafe_workspace(self, workspace, _unused, mock_session) -> None:
        # The workspace is interpolated straight into the request path, so a slug carrying
        # path separators has to be rejected before any request is made.
        assert validate_credentials(api_key="key", workspace=workspace) == (False, INVALID_WORKSPACE_ERROR)
        mock_session.assert_not_called()

    def test_cloudsmith_source_rejects_unsafe_workspace(self) -> None:
        with pytest.raises(ValueError, match="valid Cloudsmith workspace slug"):
            cloudsmith_source(
                api_key="key",
                workspace="../other",
                endpoint="repositories",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(),
            )

    @parameterized.expand(
        [
            ("repositories", "/repos/acme/", {"sort": "created_at"}),
            ("vulnerabilities", "/vulnerabilities/acme/", {}),
            ("audit_log", "/audit-log/acme/", {}),
            ("members", "/orgs/acme/members/", {"sort": "user_name"}),
            ("teams", "/orgs/acme/teams/", {"sort": "name"}),
        ]
    )
    def test_get_resource_binds_workspace_into_path(self, endpoint, expected_path, expected_extra_params) -> None:
        resource = cast(dict[str, Any], get_resource(CLOUDSMITH_ENDPOINTS[endpoint], "acme"))

        assert resource["name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["table_format"] == "delta"
        assert resource["endpoint"]["path"] == expected_path
        assert resource["endpoint"]["params"] == {"page_size": 100, **expected_extra_params}
        assert isinstance(resource["endpoint"]["paginator"], CloudsmithPaginator)
        assert resource["endpoint"]["data_selector_required"] is True

    @parameterized.expand([("packages",), ("entitlements",), ("webhooks",)])
    def test_get_resource_rejects_fanout_endpoints(self, endpoint) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(CLOUDSMITH_ENDPOINTS[endpoint], "acme")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.cloudsmith.rest_api_resource")
    def test_top_level_source_response(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()

        response = cloudsmith_source(
            api_key="key",
            workspace="acme",
            endpoint="repositories",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        assert response.name == "repositories"
        assert response.primary_keys == ["slug_perm"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.cloudsmith.rest_api_resource")
    def test_top_level_source_resumes_from_saved_state(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_manager(CloudsmithResumeConfig(paginator_state={"page": 4}))

        cloudsmith_source(
            api_key="key",
            workspace="acme",
            endpoint="repositories",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"page": 4}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.cloudsmith.rest_api_resource")
    def test_source_saves_checkpoints_after_batches(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_manager()

        cloudsmith_source(
            api_key="key",
            workspace="acme",
            endpoint="repositories",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]
        resume_hook({"page": 3})
        manager.save_state.assert_called_once_with(CloudsmithResumeConfig(paginator_state={"page": 3}))

        # A terminal (None) checkpoint is not persisted - the Redis TTL handles cleanup.
        manager.save_state.reset_mock()
        resume_hook(None)
        manager.save_state.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_packages_fanout_row_format(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeResource("repositories", [{"slug": "prod"}]),
            _FakeResource("packages", [{"slug_perm": "abc", "name": "tool", "_repositories_slug": "prod"}]),
        ]

        response = cloudsmith_source(
            api_key="key",
            workspace="acme",
            endpoint="packages",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        assert list(cast(Any, response.items())) == [{"slug_perm": "abc", "name": "tool", "repository_slug": "prod"}]
        # `slug_perm` is only documented as unique within a repository, and this table
        # aggregates every repository in the workspace.
        assert response.primary_keys == ["repository_slug", "slug_perm"]
        assert response.partition_keys == ["uploaded_at"]
        # Fan-out interleaves repositories, so rows never arrive globally ascending: desc mode
        # keeps a partial run from advancing the watermark past repositories it never reached.
        assert response.sort_mode == "desc"

    @parameterized.expand(
        [
            # The entitlement token is a live download credential.
            (
                "entitlements",
                {"slug_perm": "tok", "name": "ci", "token": "secret", "_repositories_slug": "prod"},
                {"slug_perm": "tok", "name": "ci", "repository_slug": "prod"},
            ),
            # `target_url` can embed an auth token and `templates` carries rendered request bodies.
            (
                "webhooks",
                {
                    "slug_perm": "wh",
                    "target_url": "https://example.com/hook?token=secret",
                    "templates": [{"event": "package.created", "template": "{}"}],
                    "is_active": True,
                    "_repositories_slug": "prod",
                },
                {"slug_perm": "wh", "is_active": True, "repository_slug": "prod"},
            ),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_fanout_strips_secret_fields(self, endpoint, raw_row, expected_row, mock_rest_api_resources) -> None:
        # Credential-bearing fields must never land in a warehouse table any project member can query.
        mock_rest_api_resources.return_value = [
            _FakeResource("repositories", [{"slug": "prod"}]),
            _FakeResource(endpoint, [raw_row]),
        ]

        response = cloudsmith_source(
            api_key="key",
            workspace="acme",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        assert list(cast(Any, response.items())) == [expected_row]

    @parameterized.expand(
        [
            ("packages", {"sort": "date"}),
            ("entitlements", {"sort": "name"}),
            ("webhooks", None),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.cloudsmith.build_dependent_resource"
    )
    def test_fanout_wiring(self, endpoint, expected_child_params, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = _FakeResource(endpoint, [])
        manager = _make_manager(CloudsmithResumeConfig(paginator_state={"completed": [], "current": None}))

        cloudsmith_source(
            api_key="key",
            workspace="acme",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["child_endpoint"] == endpoint
        assert kwargs["page_size_param"] == "page_size"
        # `{owner}` has to be pre-formatted: the fan-out helper only substitutes `{repo}`.
        assert kwargs["path_format_values"] == {"owner": "acme"}
        assert kwargs["fanout"].resolve_param == "repo"
        assert kwargs["fanout"].resolve_field == "slug"
        assert isinstance(kwargs["parent_endpoint_extra"]["paginator"], CloudsmithPaginator)
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], CloudsmithPaginator)
        assert kwargs["child_params_extra"] == expected_child_params
        assert kwargs["incremental_config_factory"] is _cloudsmith_incremental_window
        assert kwargs["resume_hook"] is not None
        assert kwargs["initial_paginator_state"] == {"completed": [], "current": None}

    @parameterized.expand(
        [
            ("incremental", True, datetime(2026, 3, 1, tzinfo=UTC)),
            ("first_sync", True, None),
            ("non_incremental", False, datetime(2026, 3, 1, tzinfo=UTC)),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.cloudsmith.build_dependent_resource"
    )
    def test_packages_passes_watermark(
        self, _name, should_use_incremental_field, last_value, mock_build_dependent_resource
    ) -> None:
        mock_build_dependent_resource.return_value = _FakeResource("packages", [])

        cloudsmith_source(
            api_key="key",
            workspace="acme",
            endpoint="packages",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
            incremental_field="uploaded_at",
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is should_use_incremental_field
        assert kwargs["db_incremental_field_last_value"] == last_value
        assert kwargs["incremental_field"] == "uploaded_at"
