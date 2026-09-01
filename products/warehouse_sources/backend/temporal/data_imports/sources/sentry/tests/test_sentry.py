from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized
from requests.exceptions import HTTPError, JSONDecodeError, RequestException

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent import (
    ParentTableRef,
    WarehouseParentTableNotFoundError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sentry import SentrySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry import (
    SentryPaginator,
    SentryResumeConfig,
    SentryStatsSummaryRejectedError,
    _custom_endpoint_rows,
    _issues_parent_row_filter,
    _normalize_api_base_url,
    _normalize_organization_slug,
    _parse_next_link,
    _retention_bounded_start_param,
    _retry_wait_seconds,
    _start_param_for_sentry,
    get_resource,
    sentry_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sentry.settings import (
    REQUIRED_SENTRY_SCOPES,
    SENTRY_ENDPOINTS,
    SENTRY_FANOUT_PARENT_WINDOW,
    SENTRY_RETENTION_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sentry.source import SentrySource

CUSTOM_ITERATOR_ENDPOINTS = [
    name for name, config in SENTRY_ENDPOINTS.items() if config.custom_iterator and name != "issue_tag_values"
]


def _response(payload, status_code: int = 200, link_header: str = "") -> Mock:
    response = Mock()
    response.status_code = status_code
    response.headers = {"Link": link_header}
    response.json.return_value = payload
    response.text = "error"

    def _raise_for_status() -> None:
        if status_code >= 400:
            raise HTTPError(f"{status_code} Server Error", response=response)

    response.raise_for_status = _raise_for_status
    return response


def _make_fake_manager(
    can_resume: bool = False, state: SentryResumeConfig | None = None
) -> ResumableSourceManager[SentryResumeConfig]:
    manager = Mock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return cast(ResumableSourceManager[SentryResumeConfig], manager)


class _FakeDltResource:
    """Lightweight stand-in for a DltResource returned by rest_api_resources.

    ``process_parent_data_item`` injects parent fields as
    ``_<parent_resource>_<field>`` (see ``make_parent_key_name``), so test
    data should include those prefixed keys to exercise the row mappers.
    """

    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


class _RaisingResource:
    """Fan-out resource stand-in that raises an HTTPError when iterated."""

    def __init__(self, status_code: int) -> None:
        self._status_code = status_code

    def __iter__(self):
        response = Mock()
        response.status_code = self._status_code
        raise HTTPError(f"{self._status_code} Client Error", response=response)


class TestSentryTransport:
    def test_normalize_api_base_url(self) -> None:
        assert _normalize_api_base_url(None) == "https://sentry.io"
        assert _normalize_api_base_url("https://us.sentry.io/") == "https://us.sentry.io"

    @parameterized.expand(
        [
            ("bare_slug", "acme", "acme"),
            ("bare_slug_trims_whitespace", "  acme  ", "acme"),
            ("org_subdomain_url", "https://acme.sentry.io/", "acme"),
            ("org_subdomain_url_no_scheme", "acme.sentry.io", "acme"),
            ("org_subdomain_with_path", "https://acme.sentry.io/issues/", "acme"),
            ("organizations_deep_link", "https://sentry.io/organizations/acme/issues/", "acme"),
            ("organizations_deep_link_no_scheme", "sentry.io/organizations/acme", "acme"),
            # No slug to extract: return the input as-is rather than guessing the literal "organizations".
            ("organizations_path_without_slug", "https://sentry.io/organizations/", "https://sentry.io/organizations/"),
        ]
    )
    def test_normalize_organization_slug_extracts_slug(self, _name: str, value: str, expected: str) -> None:
        assert _normalize_organization_slug(value) == expected

    def test_start_param_for_sentry_formats_datetime(self) -> None:
        value = datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC)
        assert _start_param_for_sentry(value) == "2025-01-01T10:30:00"

    def test_start_param_for_sentry_caps_future_datetime(self) -> None:
        value = datetime(2999, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert _start_param_for_sentry(value) != "2999-01-01T00:00:00"

    @parameterized.expand(
        [
            (
                "has_next",
                '<https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0>; rel="next"; results="true"',
                True,
            ),
            (
                "no_more_results",
                '<https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0>; rel="next"; results="false"',
                False,
            ),
            ("missing_link", "", False),
        ]
    )
    def test_paginator_update_state(self, _name, link_header, expected_has_next) -> None:
        paginator = SentryPaginator()
        response = Mock()
        response.headers = {"Link": link_header}

        paginator.update_state(response)

        assert paginator.has_next_page == expected_has_next

    def test_paginator_update_request_sets_next_url(self) -> None:
        paginator = SentryPaginator()
        response = Mock()
        response.headers = {
            "Link": '<https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0>; rel="next"; results="true"'
        }
        paginator.update_state(response)

        request = Mock()
        request.url = "/api/0/organizations/acme/issues/"
        request.params = {"limit": 100}
        paginator.update_request(request)

        assert request.url == "https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0"
        assert request.params == {}

    def test_paginator_get_resume_state_returns_next_url_when_has_next(self) -> None:
        paginator = SentryPaginator()
        response = Mock()
        response.headers = {
            "Link": '<https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0>; rel="next"; results="true"'
        }
        paginator.update_state(response)

        assert paginator.get_resume_state() == {
            "next_url": "https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0"
        }

    def test_paginator_get_resume_state_returns_none_when_exhausted(self) -> None:
        paginator = SentryPaginator()
        response = Mock()
        response.headers = {"Link": ""}
        paginator.update_state(response)

        assert paginator.get_resume_state() is None

    def test_paginator_set_resume_state_seeds_initial_request(self) -> None:
        paginator = SentryPaginator()
        paginator.set_resume_state({"next_url": "https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:2"})

        assert paginator.has_next_page is True

        request = Mock()
        request.url = "https://sentry.io/api/0/organizations/acme/issues/"
        request.params = {"limit": 100}
        paginator.init_request(request)

        assert request.url == "https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:2"
        assert request.params == {}

    def test_get_resource_incremental_issues(self) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(
                endpoint="issues",
                organization_slug="acme",
                should_use_incremental_field=True,
                incremental_field="lastSeen",
            ),
        )

        assert resource["name"] == "issues"
        assert resource["write_disposition"]["disposition"] == "merge"
        assert resource["endpoint"]["params"]["query"] == ""
        assert resource["endpoint"]["params"]["sort"] == "date"
        assert "start" not in resource["endpoint"]["params"]
        assert resource["endpoint"]["incremental"]["start_param"] == "start"
        assert resource["endpoint"]["incremental"]["end_param"] == "end"
        assert resource["endpoint"]["incremental"]["cursor_path"] == "lastSeen"

    @parameterized.expand(
        [
            ("issue_events",),
            ("project_events",),
        ]
    )
    def test_events_endpoints_default_to_date_received(self, endpoint) -> None:
        # Both endpoints fetch full event bodies (child_params full=true), which carry a
        # `dateReceived` timestamp rather than the `dateCreated` field the lightweight
        # issue/event list serializers use. Defaulting to `dateCreated` here made every
        # incremental sync of these tables fail with IncrementalFieldMissingFromDataError.
        config = SENTRY_ENDPOINTS[endpoint]
        assert config.default_incremental_field == "dateReceived"
        assert [incremental_field["field"] for incremental_field in config.incremental_fields] == ["dateReceived"]

    @parameterized.expand(
        [
            ("projects", "/organizations/acme/projects/"),
            ("teams", "/organizations/acme/teams/"),
            ("members", "/organizations/acme/members/"),
            ("releases", "/organizations/acme/releases/"),
            ("environments", "/organizations/acme/environments/"),
            ("monitors", "/organizations/acme/monitors/"),
        ]
    )
    def test_get_resource_non_fanout_shape(self, endpoint, expected_path) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(
                endpoint=endpoint,
                organization_slug="acme",
                should_use_incremental_field=False,
            ),
        )

        assert resource["name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == expected_path
        assert resource["table_format"] == "delta"

    @parameterized.expand(
        [
            ("project_events",),
            ("project_users",),
            ("project_client_keys",),
            ("project_service_hooks",),
            ("issue_events",),
            ("issue_hashes",),
            ("issue_tag_values",),
            ("release_deploys",),
            ("release_commits",),
            ("repo_commits",),
            ("monitor_checkins",),
            ("project_user_feedback",),
            ("project_filters",),
            ("sessions",),
            ("organization_stats",),
            ("organization_stats_summary",),
            ("trace_item_attributes",),
            ("trace_item_stats",),
            ("project_ownership",),
            ("project_stats",),
        ]
    )
    def test_get_resource_rejects_fanout_endpoints(self, endpoint) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(
                endpoint=endpoint,
                organization_slug="acme",
                should_use_incremental_field=False,
            )

    def test_validate_credentials_rejects_unknown_api_base_url(self) -> None:
        result = validate_credentials(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://example.sentry.invalid",
        )

        assert result == (
            False,
            "API base URL must be one of https://sentry.io, https://us.sentry.io, or https://de.sentry.io.",
        )

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_validate_credentials_401_tells_user_to_reconnect(self, mock_session) -> None:
        mock_session.return_value.get.return_value = _response(None, status_code=401)

        valid, error = validate_credentials(auth_token="token", organization_slug="acme")

        assert not valid
        assert error == "Invalid Sentry auth token. Please update your token and reconnect."

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_validate_credentials_403_names_required_scopes(self, mock_session) -> None:
        mock_session.return_value.get.return_value = _response(None, status_code=403)

        valid, error = validate_credentials(auth_token="token", organization_slug="acme")

        assert not valid
        assert error is not None
        assert error.startswith("Sentry token is missing required scopes")
        for scope in REQUIRED_SENTRY_SCOPES:
            assert scope in error

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_validate_credentials_404_does_not_echo_org_slug(self, mock_session) -> None:
        mock_session.return_value.get.return_value = _response(None, status_code=404)

        valid, error = validate_credentials(auth_token="token", organization_slug="secret-org-slug")

        assert not valid
        assert error == "Sentry organization not found. Verify your organization slug, then reconnect."
        assert "secret-org-slug" not in (error or "")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_validate_credentials_unexpected_status_hides_vendor_detail(self, mock_session) -> None:
        # `_response` sets `response.text = "error"` — the raw body must never reach the customer.
        mock_session.return_value.get.return_value = _response({"detail": "internal sentry detail"}, status_code=500)

        valid, error = validate_credentials(auth_token="token", organization_slug="acme")

        assert not valid
        assert error == "Could not connect to Sentry. Check your auth token and organization slug, then reconnect."

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_validate_credentials_request_error_hides_exception_text(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = RequestException("connection refused to https://sentry.io")

        valid, error = validate_credentials(auth_token="token", organization_slug="acme")

        assert not valid
        assert error == "Could not reach Sentry to validate your credentials. Check your connection, then try again."

    def test_sentry_source_rejects_unknown_api_base_url_at_runtime(self) -> None:
        with pytest.raises(
            ValueError,
            match="API base URL must be one of https://sentry.io, https://us.sentry.io, or https://de.sentry.io.",
        ):
            sentry_source(
                auth_token="token",
                organization_slug="acme",
                api_base_url="https://example.sentry.invalid",
                endpoint="issues",
                team_id=123,
                job_id="job-id",
            )


class TestSentrySourceValidation:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.source.validate_sentry_credentials")
    def test_validate_credentials_rejects_unknown_api_base_url(self, mock_validate) -> None:
        source = SentrySource()
        config = SentrySourceConfig(
            auth_token="token",
            organization_slug="acme",
            api_base_url=cast(Any, "https://example.sentry.invalid"),
        )

        result = source.validate_credentials(config, team_id=1)

        assert result == (
            False,
            "API base URL must be one of https://sentry.io, https://us.sentry.io, or https://de.sentry.io.",
        )
        mock_validate.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.source.validate_sentry_credentials")
    def test_validate_credentials_defaults_missing_api_base_url(self, mock_validate) -> None:
        source = SentrySource()
        config = SentrySourceConfig(
            auth_token="token",
            organization_slug="acme",
        )
        mock_validate.return_value = (True, None)

        result = source.validate_credentials(config, team_id=1)

        assert result == (True, None)
        mock_validate.assert_called_once_with(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
        )

    def test_parse_config_normalizes_pasted_org_url(self) -> None:
        config = SentrySource().parse_config({"auth_token": "token", "organization_slug": "https://acme.sentry.io/"})

        assert config.organization_slug == "acme"

    def test_retryable_errors_match_exhausted_connection_retries(self) -> None:
        # `_request_with_retry` (sentry.py) already retries a dropped connection or read timeout;
        # once that budget is exhausted, urllib3 re-raises with this stable "Max retries exceeded"
        # wording regardless of cause. Without a matching entry here, a transient Sentry-side blip
        # would be reported to error tracking as a bug instead of logged as a benign retry.
        error_msg = (
            "HTTPSConnectionPool(host='sentry.io', port=443): Max retries exceeded with "
            'url: /api/0/organizations/acme/projects/?limit=100 (Caused by ReadTimeoutError("HTTPS'
            "ConnectionPool(host='sentry.io', port=443): Read timed out. (read timeout=30)\"))"
        )

        assert any(pattern in error_msg for pattern in SentrySource().get_retryable_errors())

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.rest_api_resource")
    def test_sentry_source_builds_response(self, mock_rest_api_resource) -> None:
        mock_resource = Mock()
        mock_rest_api_resource.return_value = mock_resource

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issues",
            team_id=123,
            job_id="job-id",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 1, 1, 10, 30, 0),
            incremental_field="lastSeen",
        )

        assert resp.name == "issues"
        assert resp.primary_keys == ["id"]
        assert resp.partition_mode == "datetime"

    # ----- Project fan-out (dependent resources) -----

    @parameterized.expand(
        [
            ("project_events", {"eventID": "evt-1", "_projects_id": "1", "_projects_slug": "web"}),
            ("project_users", {"id": "usr-1", "_projects_id": "1", "_projects_slug": "web"}),
            ("project_client_keys", {"id": "key-1", "_projects_id": "1", "_projects_slug": "web"}),
            ("project_service_hooks", {"id": "hook-1", "_projects_id": "1", "_projects_slug": "web"}),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_project_fanout_row_format(self, endpoint, child_row, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("projects", [{"id": "1", "slug": "web"}]),
            _FakeDltResource(endpoint, [child_row]),
        ]

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint=endpoint,
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        row = rows[0]
        assert row["project_id"] == "1"
        assert row["project_slug"] == "web"
        assert "_projects_id" not in row
        assert "_projects_slug" not in row

    # ----- Project service hooks: graceful skip on org-gated 403 -----

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.build_dependent_resource")
    def test_project_service_hooks_skips_on_forbidden(self, mock_build) -> None:
        # Sentry 403s the service hooks endpoint for orgs without the feature,
        # even with full scopes. The schema should complete empty, not error.
        mock_build.return_value = _RaisingResource(403)

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="project_service_hooks",
            team_id=123,
            job_id="job-id",
        )

        assert list(cast(Any, resp.items())) == []

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.build_dependent_resource")
    def test_project_service_hooks_propagates_non_forbidden(self, mock_build) -> None:
        # A server error is not the org-gate signal — it must still propagate.
        mock_build.return_value = _RaisingResource(500)

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="project_service_hooks",
            team_id=123,
            job_id="job-id",
        )

        with pytest.raises(HTTPError):
            list(cast(Any, resp.items()))

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.build_dependent_resource")
    def test_other_fanout_endpoint_propagates_forbidden(self, mock_build) -> None:
        # A 403 on a non-servicehooks fan-out endpoint is a genuine scope error
        # and must still reach the non-retryable handler.
        mock_build.return_value = _RaisingResource(403)

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="project_users",
            team_id=123,
            job_id="job-id",
        )

        with pytest.raises(HTTPError):
            list(cast(Any, resp.items()))

    # ----- Issue fan-out: dependent resources (issue_events, issue_hashes) -----

    @parameterized.expand(
        [
            ("issue_events", {"eventID": "evt-1", "_issues_id": "100"}),
            ("issue_hashes", {"id": "hash-1", "hash": "abc", "_issues_id": "100"}),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_issue_fanout_dependent_resource_row_format(self, endpoint, child_row, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("issues", [{"id": "100"}]),
            _FakeDltResource(endpoint, [child_row]),
        ]

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint=endpoint,
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        row = rows[0]
        assert row["issue_id"] == "100"
        assert "_issues_id" not in row

    @parameterized.expand(
        [
            ("issue_events", "issues"),
            ("project_events", "projects"),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_event_fanout_requests_full_event_bodies(self, endpoint, parent_name, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource(parent_name, []),
            _FakeDltResource(endpoint, []),
        ]

        sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint=endpoint,
            team_id=123,
            job_id="job-id",
        )

        config = mock_rest_api_resources.call_args.args[0]
        child_resource = next(r for r in config["resources"] if r["name"] == endpoint)
        assert child_resource["endpoint"]["params"]["full"] == "true"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_issue_hashes_tolerates_child_not_found(self, mock_rest_api_resources) -> None:
        # An issue can be deleted/merged between the `issues` listing and this per-issue hashes
        # fetch, which 404s. That single-issue 404 must not fail the whole schema (see
        # SentrySource.get_non_retryable_errors' generic "404 Client Error" mapping).
        mock_rest_api_resources.return_value = [
            _FakeDltResource("issues", [{"id": "100"}]),
            _FakeDltResource("issue_hashes", []),
        ]

        sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_hashes",
            team_id=123,
            job_id="job-id",
        )

        config = mock_rest_api_resources.call_args.args[0]
        child_resource = next(r for r in config["resources"] if r["name"] == "issue_hashes")
        assert child_resource["endpoint"]["response_actions"] == [{"status_code": 404, "action": "ignore"}]

    # ----- Issue fan-out: custom iterator (issue_tag_values) -----

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_issue_tag_values_custom_fanout_row_format(self, mock_get) -> None:
        seen_issues_params: list[dict | None] = []
        seen_values_params: list[dict | None] = []

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                seen_issues_params.append(params)
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                seen_values_params.append(params)
                return _response([{"value": "Chrome", "timesSeen": 1}])
            return _response([])

        mock_get.return_value.get.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        row = rows[0]
        assert row["issue_id"] == "100"
        assert row["tag_key"] == "browser"
        assert seen_issues_params == [{"limit": 100, "query": "", "sort": "date"}]
        assert seen_values_params == [{"limit": 100, "sort": "-date"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_issue_tag_values_incremental_stops_at_last_seen_cutoff(self, mock_get) -> None:
        cutoff = datetime(2026, 3, 3, 0, 0, 0, tzinfo=UTC)

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response(
                    [
                        {"value": "Chrome", "lastSeen": "2026-03-05T12:00:00Z"},
                        {"value": "Firefox", "lastSeen": "2026-03-01T09:00:00Z"},
                    ],
                    link_header='<https://sentry.io/api/0/organizations/acme/issues/100/tags/browser/values/?cursor=0:100:0>; rel="next"; results="true"',
                )
            if "tags/browser/values/?cursor=0:100:0" in url:
                raise AssertionError("should not request the next page after reaching cutoff")
            return _response([])

        mock_get.return_value.get.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            should_use_incremental_field=True,
            db_incremental_field_last_value=cutoff,
            incremental_field="lastSeen",
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [
            {"value": "Chrome", "lastSeen": "2026-03-05T12:00:00Z", "issue_id": "100", "tag_key": "browser"}
        ]

    # Patch _request_with_retry directly so the test exercises the iterator's
    # skip logic without incurring the real (post-exhaustion) retry sleeps.
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_issue_tag_values_skips_tag_on_persistent_server_error(self, mock_request) -> None:
        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "bad tag"}, {"key": "browser"}])
            if "tags/bad%20tag/values/" in url:
                # Sentry persistently 500s for this tag's values endpoint.
                return _response(None, status_code=500)
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response([{"value": "Chrome"}])
            return _response([])

        mock_request.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
        )

        # The 500 on the "bad tag" values endpoint is skipped; the healthy
        # "browser" tag still yields its values instead of the whole sync crashing.
        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Chrome", "issue_id": "100", "tag_key": "browser"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_issue_tag_values_skips_tag_on_unparseable_ok_body(self, mock_request) -> None:
        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "bad tag"}, {"key": "browser"}])
            if "tags/bad%20tag/values/" in url:
                # Sentry returns a 200 with an empty/unparseable body for this tag.
                bad = _response([])
                bad.json.side_effect = JSONDecodeError("Expecting value", "", 0)
                return bad
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response([{"value": "Chrome"}])
            return _response([])

        mock_request.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
        )

        # The unparseable 200 on the "bad tag" values endpoint is skipped; the
        # healthy "browser" tag still yields its values instead of crashing.
        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Chrome", "issue_id": "100", "tag_key": "browser"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_issue_tag_values_skips_tag_on_forbidden(self, mock_request) -> None:
        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "dart.name"}, {"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/dart.name/values/"):
                # Sentry gates this tag's values at the org level (data scrubbing).
                return _response(None, status_code=403)
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response([{"value": "Chrome"}])
            return _response([])

        mock_request.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
        )

        # The 403 on the gated tag is skipped; the healthy "browser" tag still
        # yields its values instead of the whole sync failing.
        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Chrome", "issue_id": "100", "tag_key": "browser"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_issue_tag_values_propagates_non_forbidden_client_error(self, mock_request) -> None:
        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                # A revoked token (401) is a genuine failure — it must still propagate.
                return _response(None, status_code=401)
            return _response([])

        mock_request.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
        )

        with pytest.raises(HTTPError):
            list(cast(Any, resp.items()))


class TestSentrySourceResumable:
    """Resume behaviour for flat endpoints (rest_api_resource path)."""

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.rest_api_resource")
    def test_fresh_run_passes_resume_hook_and_no_initial_state(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_fake_manager(can_resume=False)

        sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="projects",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        _, kwargs = mock_rest_api_resource.call_args
        assert kwargs["initial_paginator_state"] is None
        assert callable(kwargs["resume_hook"])

        # save_checkpoint should forward the next page into manager.save_state
        kwargs["resume_hook"]({"next_url": "https://sentry.io/api/0/organizations/acme/projects/?cursor=0:100:0"})
        cast(Mock, manager.save_state).assert_called_once_with(
            SentryResumeConfig(next_url="https://sentry.io/api/0/organizations/acme/projects/?cursor=0:100:0")
        )

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.rest_api_resource")
    def test_resume_run_seeds_initial_paginator_state_from_loaded_config(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        resume_url = "https://sentry.io/api/0/organizations/acme/projects/?cursor=0:100:2"
        manager = _make_fake_manager(can_resume=True, state=SentryResumeConfig(next_url=resume_url))

        sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="projects",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        _, kwargs = mock_rest_api_resource.call_args
        assert kwargs["initial_paginator_state"] == {"next_url": resume_url}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.rest_api_resource")
    def test_resume_hook_noop_when_no_next_page(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_fake_manager(can_resume=False)

        sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="projects",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        _, kwargs = mock_rest_api_resource.call_args
        kwargs["resume_hook"](None)
        kwargs["resume_hook"]({})
        cast(Mock, manager.save_state).assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.rest_api_resource")
    def test_no_manager_disables_resume(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()

        sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="projects",
            team_id=123,
            job_id="job-id",
        )

        _, kwargs = mock_rest_api_resource.call_args
        assert kwargs["initial_paginator_state"] is None
        assert kwargs["resume_hook"] is None


class TestIssueTagValuesResumable:
    @pytest.fixture(autouse=True)
    def _fresh_issues_snapshot(self):
        # These cases predate the snapshot cap and assert on the rows the fan-out emits, so pin
        # the parent snapshot ahead of every fixture timestamp to leave that set unchanged.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.parent_snapshot_covers_through",
            return_value=datetime(2999, 1, 1, tzinfo=UTC),
        ):
            yield

    """Resume behaviour for the two-level issue_tag_values fan-out loop."""

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_fresh_run_saves_state_pointing_to_next_values_page(self, mock_get) -> None:
        next_values_link = (
            "<https://sentry.io/api/0/organizations/acme/issues/100/tags/browser/values/?cursor=0:100:2>; "
            'rel="next"; results="true"'
        )

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response([{"value": "Chrome"}], link_header=next_values_link)
            # Second values page returns empty + no link header to end the loop
            return _response([])

        mock_get.return_value.get.side_effect = side_effect
        manager = _make_fake_manager(can_resume=False)

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        assert rows[0]["issue_id"] == "100"
        assert rows[0]["tag_key"] == "browser"

        saved_calls = cast(Mock, manager.save_state).call_args_list
        assert len(saved_calls) == 1
        saved_state = saved_calls[0].args[0]
        assert saved_state == SentryResumeConfig(
            issue_id="100",
            tag_key="browser",
            values_next_url="https://sentry.io/api/0/organizations/acme/issues/100/tags/browser/values/?cursor=0:100:2",
        )

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.resolve_parent_table_ref",
        return_value=ParentTableRef(uri="s3://bucket/team_123_sentry_x/issues", version=3),
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.iter_parent_pages_from_warehouse",
        return_value=iter([[{"id": "100"}]]),
    )
    def test_warehouse_mode_stamps_the_checkpoint_with_the_pinned_version(
        self, _mock_reader, _mock_resolve, mock_get
    ) -> None:
        # A checkpoint is a position in an iteration order, so it has to record which one:
        # without the pin, a later attempt reading a different parent would fast-forward past
        # issues its own order never reached, and the watermark would still advance.
        next_values_link = (
            "<https://sentry.io/api/0/organizations/acme/issues/100/tags/browser/values/?cursor=0:100:2>; "
            'rel="next"; results="true"'
        )

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response([{"value": "Chrome"}], link_header=next_values_link)
            return _response([])

        mock_get.return_value.get.side_effect = side_effect
        manager = _make_fake_manager(can_resume=False)

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            source_id="source-1",
            use_warehouse_parent=True,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2020-01-01T00:00:00Z",
            resumable_source_manager=manager,
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        saved_state = cast(Mock, manager.save_state).call_args_list[0].args[0]
        assert saved_state.parent_version == 3

    @parameterized.expand(
        [
            # A watermark inside the window is the tighter floor, so the scan stops there.
            ("watermark_inside_window", timedelta(days=2), timedelta(days=2)),
            # A watermark older than the window can't widen it back out.
            ("watermark_older_than_window", timedelta(days=120), None),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.resolve_parent_table_ref",
        return_value=ParentTableRef(uri="s3://bucket/team_123_sentry_x/issues", version=3),
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.iter_parent_pages_from_warehouse",
        return_value=iter([[{"id": "100", "lastSeen": "2026-08-17T00:00:00Z"}]]),
    )
    def test_warehouse_scan_is_floored_by_the_watermark_and_the_list_window(
        self, _name, watermark_ago, expected_floor_ago, mock_reader, _mock_resolve, mock_get
    ) -> None:
        # Without a floor the scan reads every issue ever synced and discards most of them
        # per row, which is the fan-out inflation the retention findings traced.
        mock_get.return_value.get.side_effect = lambda url, **kwargs: _response([])
        watermark = (datetime.now(UTC) - watermark_ago).isoformat()

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            source_id="source-1",
            use_warehouse_parent=True,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )
        list(cast(Any, resp.items()))

        row_filter = mock_reader.call_args.kwargs["row_filter"]
        assert row_filter.field == "lastSeen"
        now = datetime.now(UTC)
        expected_floor = now - (expected_floor_ago if expected_floor_ago is not None else SENTRY_FANOUT_PARENT_WINDOW)
        assert abs(row_filter.floor(now) - expected_floor) < timedelta(seconds=5)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.try_resolve_parent_table"
    )
    def test_full_refresh_takes_the_api_parent_even_with_the_flag_on(self, mock_resolve, mock_get) -> None:
        # No watermark means the only floor is our window constant, and Sentry clamps its own
        # listing to the org's plan retention below it, so the snapshot can't reproduce the
        # API's row set. The run must not even resolve the warehouse table.
        mock_get.return_value.get.side_effect = lambda url, **kwargs: _response([])

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            source_id="source-1",
            use_warehouse_parent=True,
        )
        list(cast(Any, resp.items()))

        mock_resolve.assert_not_called()
        issues_urls = [c.args[0] for c in mock_get.return_value.get.call_args_list if c.args[0].endswith("/issues/")]
        assert issues_urls, "expected the API issues listing to drive the fan-out"

    @parameterized.expand(
        [
            # Written over the API listing, read by a warehouse run.
            ("api_checkpoint_in_warehouse_run", None, True),
            # Written over a different pinned version than this run resolved (parent re-synced).
            ("other_version_checkpoint", 2, True),
            # Written over a warehouse scan, read by a run that fell back to the API.
            ("warehouse_checkpoint_in_api_run", 3, False),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.resolve_parent_table_ref",
        return_value=ParentTableRef(uri="s3://bucket/team_123_sentry_x/issues", version=3),
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.iter_parent_pages_from_warehouse",
        return_value=iter([[{"id": "100"}]]),
    )
    def test_checkpoint_from_a_different_issue_order_is_refused_and_cleared(
        self, _name, stored_parent_version, use_warehouse_parent, _mock_reader, _mock_resolve, mock_get
    ) -> None:
        # Applying it would skip issues the new order never reached; leaving it in Redis would
        # make the pipeline append chunk 0 onto the previous attempt's rows.
        mock_get.return_value.get.side_effect = lambda url, **kwargs: _response([])
        manager = _make_fake_manager(
            can_resume=True,
            state=SentryResumeConfig(
                issue_id="999",
                tag_key="browser",
                values_next_url="https://x",
                parent_version=stored_parent_version,
            ),
        )

        sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            source_id="source-1",
            use_warehouse_parent=use_warehouse_parent,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2020-01-01T00:00:00Z",
            resumable_source_manager=manager,
        )

        cast(Mock, manager.clear_state).assert_called_once()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_resume_fetches_saved_values_url_and_skips_earlier_pairs(self, mock_get) -> None:
        seen_urls: list[str] = []
        resume_url = "https://sentry.io/api/0/organizations/acme/issues/100/tags/browser/values/?cursor=0:100:2"

        def side_effect(url, headers=None, params=None, timeout=None):
            seen_urls.append(url)
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "99"}, {"id": "100"}, {"id": "101"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "os"}, {"key": "browser"}])
            if url == resume_url:
                return _response([{"value": "Firefox"}])
            # Any other URL shouldn't be hit on resume; fall back to empty
            return _response([])

        mock_get.return_value.get.side_effect = side_effect
        manager = _make_fake_manager(
            can_resume=True,
            state=SentryResumeConfig(issue_id="100", tag_key="browser", values_next_url=resume_url),
        )

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Firefox", "issue_id": "100", "tag_key": "browser"}]

        # We should have fetched the resume values URL directly, and NOT
        # issued the initial page for that (issue, tag) pair.
        assert resume_url in seen_urls
        initial_values_url = "https://sentry.io/api/0/organizations/acme/issues/100/tags/browser/values/"
        assert initial_values_url not in seen_urls

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._RESUME_ISSUE_SKIP_LIMIT", 2)
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_stale_checkpoint_falls_through_after_skip_limit(self, mock_get) -> None:
        """If the checkpoint issue was deleted between runs, bounded skipping
        falls through so subsequent issues still get processed."""

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                # None of these match the checkpoint issue_id=999.
                return _response([{"id": "100"}, {"id": "101"}, {"id": "102"}])
            if url.endswith("/organizations/acme/issues/102/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/102/tags/browser/values/"):
                return _response([{"value": "Chrome"}])
            return _response([])

        mock_get.return_value.get.side_effect = side_effect
        manager = _make_fake_manager(
            can_resume=True,
            state=SentryResumeConfig(
                issue_id="999",
                tag_key="browser",
                values_next_url="https://sentry.io/api/0/organizations/acme/issues/999/tags/browser/values/?cursor=0:100:2",
            ),
        )

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        rows = list(cast(Any, resp.items()))
        # With skip limit 2, issues 100 and 101 are skipped; on 102 we exceed
        # the limit, clear the markers, and process it fresh.
        assert rows == [{"value": "Chrome", "issue_id": "102", "tag_key": "browser"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_partial_resume_state_falls_through_to_fresh_run(self, mock_get) -> None:
        """Only activate resume when the full (issue_id, tag_key, values_next_url)
        triple is present; partial state must fall through to a fresh run."""

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response([{"value": "Chrome"}])
            return _response([])

        mock_get.return_value.get.side_effect = side_effect
        # issue_id set, but tag_key + values_next_url are missing → partial state.
        manager = _make_fake_manager(
            can_resume=True,
            state=SentryResumeConfig(issue_id="100"),
        )

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Chrome", "issue_id": "100", "tag_key": "browser"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_resume_with_empty_state_falls_through_to_fresh_run(self, mock_get) -> None:
        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response([{"value": "Chrome"}])
            return _response([])

        mock_get.return_value.get.side_effect = side_effect
        # can_resume=True but state.issue_id is None — should fall through.
        manager = _make_fake_manager(can_resume=True, state=SentryResumeConfig())

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Chrome", "issue_id": "100", "tag_key": "browser"}]


class TestHelpers:
    @parameterized.expand(
        [
            ("has_next", '<https://a.io/next>; rel="next"; results="true"', "https://a.io/next"),
            ("no_results", '<https://a.io/next>; rel="next"; results="false"', None),
            ("empty", "", None),
            ("only_prev", '<https://a.io/prev>; rel="previous"; results="true"', None),
        ]
    )
    def test_parse_next_link(self, _name, link_header, expected) -> None:
        assert _parse_next_link(link_header) == expected

    def test_retry_wait_uses_exponential_fallback_for_non_429(self) -> None:
        state = Mock()
        state.attempt_number = 3
        state.outcome = Mock()
        state.outcome.failed = False
        state.outcome.result.return_value = Mock(status_code=500)

        assert _retry_wait_seconds(state) == 4.0

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.datetime")
    def test_retry_wait_uses_rate_limit_reset_header_for_429(self, mock_datetime) -> None:
        now = datetime(2026, 3, 6, 12, 0, 0, tzinfo=UTC)
        mock_datetime.now.return_value = now

        state = Mock()
        state.attempt_number = 2
        state.outcome = Mock()
        state.outcome.failed = False
        state.outcome.result.return_value = Mock(
            status_code=429,
            headers={"X-Sentry-Rate-Limit-Reset": str(int(now.timestamp()) + 9)},
        )

        assert _retry_wait_seconds(state) == 9.0


class TestSentryRetentionWindow:
    @parameterized.expand(
        [
            ("no_watermark", None),
            ("pre_retention_watermark", datetime(2001, 1, 1, tzinfo=UTC)),
            ("pre_retention_string", "2001-01-01T00:00:00Z"),
        ]
    )
    def test_start_param_floors_to_retention(self, _name, value) -> None:
        # Sentry rejects a range reaching further back than retention, so a missing or
        # stale watermark must not produce the 1970 sentinel the issues endpoints tolerate.
        floor = datetime.now(UTC) - timedelta(days=SENTRY_RETENTION_DAYS)

        parsed = datetime.strptime(_retention_bounded_start_param(value), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)

        assert abs((parsed - floor).total_seconds()) < 60

    def test_start_param_keeps_watermark_inside_retention(self) -> None:
        value = datetime.now(UTC) - timedelta(days=3)

        parsed = datetime.strptime(_retention_bounded_start_param(value), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)

        assert abs((parsed - value).total_seconds()) < 2

    def test_start_param_caps_future_watermark_at_now(self) -> None:
        now = datetime.now(UTC)

        parsed = datetime.strptime(
            _retention_bounded_start_param(datetime(2999, 1, 1, tzinfo=UTC)), "%Y-%m-%dT%H:%M:%S"
        ).replace(tzinfo=UTC)

        assert abs((parsed - now).total_seconds()) < 60


class TestSentryNewFlatEndpoints:
    @parameterized.expand(
        [
            ("repos", "/organizations/acme/repos/", None, None),
            ("dashboards", "/organizations/acme/dashboards/", "per_page", None),
            ("discover_saved_queries", "/organizations/acme/discover/saved/", "per_page", None),
            ("workflows", "/organizations/acme/workflows/", None, None),
            ("detectors", "/organizations/acme/detectors/", None, None),
            ("organization_tags", "/organizations/acme/tags/", None, None),
            ("integrations", "/organizations/acme/integrations/", None, None),
            ("sentry_app_installations", "/organizations/acme/sentry-app-installations/", None, None),
            ("replays", "/organizations/acme/replays/", "per_page", "data"),
            ("organization_events", "/organizations/acme/events/", "per_page", "data"),
        ]
    )
    def test_resource_path_page_size_and_selector(self, endpoint, expected_path, page_size_param, selector) -> None:
        # Sending `limit` where Sentry documents `per_page` silently ignores the page size,
        # and dropping the selector on a `{"data": [...]}` payload yields zero rows.
        resource = cast(
            dict[str, Any],
            get_resource(endpoint=endpoint, organization_slug="acme", should_use_incremental_field=False),
        )

        params = resource["endpoint"]["params"]
        assert resource["endpoint"]["path"] == expected_path
        assert resource["table_format"] == "delta"
        assert resource["endpoint"].get("data_selector") == selector
        assert "limit" not in params or page_size_param == "limit"
        if page_size_param:
            assert params[page_size_param] == 100
        else:
            assert "per_page" not in params

    def test_replays_requests_ascending_sort(self) -> None:
        # sort_mode is "asc" for replays, so the request must ask for ascending
        # started_at or the incremental watermark advances to the newest row immediately.
        resource = cast(
            dict[str, Any],
            get_resource(endpoint="replays", organization_slug="acme", should_use_incremental_field=False),
        )

        assert resource["endpoint"]["params"]["sort"] == "started_at"
        assert SENTRY_ENDPOINTS["replays"].sort_mode == "asc"

    def test_organization_events_requests_discover_projection(self) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(endpoint="organization_events", organization_slug="acme", should_use_incremental_field=False),
        )

        params = resource["endpoint"]["params"]
        assert params["dataset"] == "errors"
        assert params["field"] == ["id", "timestamp", "transaction"]
        assert params["sort"] == "timestamp"

    @parameterized.expand(
        [
            ("replays", "started_at"),
            ("organization_events", "timestamp"),
        ]
    )
    def test_incremental_window_is_retention_bounded(self, endpoint, cursor_path) -> None:
        # These endpoints 400 on a pre-retention `start`, so the first incremental sync
        # must not fall back to the 1970 sentinel used by the issues endpoints.
        resource = cast(
            dict[str, Any],
            get_resource(endpoint=endpoint, organization_slug="acme", should_use_incremental_field=True),
        )

        incremental = resource["endpoint"]["incremental"]
        assert incremental["cursor_path"] == cursor_path
        assert incremental["start_param"] == "start"
        assert incremental["end_param"] == "end"
        assert incremental["initial_value"] != "1970-01-01T00:00:00"
        floor = datetime.now(UTC) - timedelta(days=SENTRY_RETENTION_DAYS)
        parsed = datetime.strptime(incremental["initial_value"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        assert abs((parsed - floor).total_seconds()) < 60
        assert resource["write_disposition"]["disposition"] == "merge"


class TestSentryNewFanoutEndpoints:
    @parameterized.expand(
        [
            (
                "release_deploys",
                "releases",
                {"version": "1.0.0"},
                {"id": "d1", "_releases_version": "1.0.0"},
                {"release_version": "1.0.0"},
            ),
            (
                "release_commits",
                "releases",
                {"version": "1.0.0"},
                {"id": "c1", "_releases_version": "1.0.0"},
                {"release_version": "1.0.0"},
            ),
            (
                "repo_commits",
                "repos",
                {"id": "77"},
                {"id": "c1", "_repos_id": "77"},
                {"repo_id": "77"},
            ),
            (
                "monitor_checkins",
                "monitors",
                {"id": "55"},
                {"id": "ci1", "_monitors_id": "55"},
                {"monitor_id": "55"},
            ),
            (
                "project_user_feedback",
                "projects",
                {"id": "1", "slug": "web"},
                {"id": "f1", "_projects_id": "1", "_projects_slug": "web"},
                {"project_id": "1", "project_slug": "web"},
            ),
            (
                "project_filters",
                "projects",
                {"id": "1", "slug": "web"},
                {"id": "browser-extensions", "_projects_id": "1", "_projects_slug": "web"},
                {"project_id": "1", "project_slug": "web"},
            ),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_parent_identifier_lands_in_the_row(
        self, endpoint, parent_name, parent_row, child_row, expected, mock_rest_api_resources
    ) -> None:
        # The parent identifier is part of each of these tables' composite primary key,
        # so losing the rename leaves a non-unique key and duplicate rows on every merge.
        mock_rest_api_resources.return_value = [
            _FakeDltResource(parent_name, [parent_row]),
            _FakeDltResource(endpoint, [child_row]),
        ]

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint=endpoint,
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        row = rows[0]
        for key, value in expected.items():
            assert row[key] == value
        assert not any(key.startswith("_") for key in row)
        assert set(resp.primary_keys or []) <= set(row)


class TestSentryCustomIteratorEndpoints:
    @parameterized.expand([(endpoint,) for endpoint in CUSTOM_ITERATOR_ENDPOINTS])
    def test_every_custom_iterator_endpoint_is_routed(self, endpoint) -> None:
        # An endpoint marked custom_iterator with no matching branch would only blow up
        # mid-sync, once the pipeline pulls the first row.
        rows = _custom_endpoint_rows(
            endpoint=endpoint,
            base_api_url="https://sentry.io/api/0",
            headers={},
            organization_slug="acme",
        )

        assert iter(rows) is not None

    def test_unknown_custom_iterator_endpoint_raises(self) -> None:
        with pytest.raises(ValueError, match="No custom iterator registered"):
            _custom_endpoint_rows(
                endpoint="not_an_endpoint",
                base_api_url="https://sentry.io/api/0",
                headers={},
                organization_slug="acme",
            )

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_sessions_flattens_series_into_one_row_per_interval(self, mock_request) -> None:
        seen_params: list[dict | None] = []

        def side_effect(url, headers=None, params=None, timeout=None):
            seen_params.append(params)
            return _response(
                {
                    "intervals": ["2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"],
                    "groups": [
                        {
                            "by": {
                                "project": 1,
                                "release": "1.0.0",
                                "environment": "prod",
                                "session.status": "healthy",
                            },
                            "series": {"sum(session)": [5, 7], "count_unique(user)": [2, 3]},
                            "totals": {"sum(session)": 12},
                        },
                        {
                            "by": {"project": 1, "environment": "prod", "session.status": "crashed"},
                            "series": {"sum(session)": [1, 0]},
                            "totals": {"sum(session)": 1},
                        },
                    ],
                }
            )

        mock_request.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="sessions",
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [
            {
                "interval_start": "2026-03-01T00:00:00Z",
                "project": "1",
                "release": "1.0.0",
                "environment": "prod",
                "session_status": "healthy",
                "sum_session": 5,
                "count_unique_user": 2,
            },
            {
                "interval_start": "2026-03-02T00:00:00Z",
                "project": "1",
                "release": "1.0.0",
                "environment": "prod",
                "session_status": "healthy",
                "sum_session": 7,
                "count_unique_user": 3,
            },
            # An absent dimension becomes "" — a null would never match on merge.
            {
                "interval_start": "2026-03-01T00:00:00Z",
                "project": "1",
                "release": "",
                "environment": "prod",
                "session_status": "crashed",
                "sum_session": 1,
                "count_unique_user": None,
            },
            {
                "interval_start": "2026-03-02T00:00:00Z",
                "project": "1",
                "release": "",
                "environment": "prod",
                "session_status": "crashed",
                "sum_session": 0,
                "count_unique_user": None,
            },
        ]
        assert seen_params[0] is not None
        assert seen_params[0]["groupBy"] == ["project", "release", "environment", "session.status"]
        assert seen_params[0]["interval"] == "1d"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_organization_stats_flattens_series_and_excludes_project_grouping(self, mock_request) -> None:
        seen_params: list[dict | None] = []

        def side_effect(url, headers=None, params=None, timeout=None):
            seen_params.append(params)
            return _response(
                {
                    "intervals": ["2026-03-01T00:00:00Z"],
                    "groups": [
                        {
                            "by": {"outcome": "accepted", "category": "error", "reason": "none"},
                            "series": {"sum(quantity)": [42]},
                            "totals": {"sum(quantity)": 42},
                        }
                    ],
                }
            )

        mock_request.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="organization_stats",
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [
            {
                "interval_start": "2026-03-01T00:00:00Z",
                "outcome": "accepted",
                "category": "error",
                "reason": "none",
                "quantity": 42,
            }
        ]
        # Grouping by project collapses the series into a single period total, which
        # would make the interval column meaningless.
        assert seen_params[0] is not None
        assert "project" not in seen_params[0]["groupBy"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_stats_summary_yields_one_row_per_project_category(self, mock_request) -> None:
        mock_request.return_value = _response(
            {
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-03-01T00:00:00Z",
                "projects": [
                    {
                        "id": "1",
                        "slug": "web",
                        "stats": [
                            {"category": "error", "outcomes": {"accepted": 5}, "totals": {"sum(quantity)": 5}},
                            {"category": "transaction", "outcomes": {"accepted": 2}, "totals": {"sum(quantity)": 2}},
                        ],
                    }
                ],
            }
        )

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="organization_stats_summary",
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert [(row["project_id"], row["category"]) for row in rows] == [("1", "error"), ("1", "transaction")]
        assert rows[0]["project_slug"] == "web"
        assert rows[0]["quantity"] == 5
        assert rows[0]["period_start"] == "2026-01-01T00:00:00Z"
        assert rows[0]["period_end"] == "2026-03-01T00:00:00Z"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_stats_summary_requests_a_clamped_window_not_a_boundary_stats_period(self, mock_request) -> None:
        # A relative statsPeriod of the full retention length lands on the retention boundary,
        # which Sentry rejects with a 400 — the request must send an explicit clamped window.
        seen_params: list[dict | None] = []

        def side_effect(url, headers=None, params=None, timeout=None):
            seen_params.append(params)
            return _response({"start": "s", "end": "e", "projects": []})

        mock_request.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="organization_stats_summary",
            team_id=123,
            job_id="job-id",
        )

        list(cast(Any, resp.items()))

        assert seen_params[0] is not None
        assert "statsPeriod" not in seen_params[0]
        assert seen_params[0]["start"] and seen_params[0]["end"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_stats_summary_skips_when_token_has_no_project_access(self, mock_request) -> None:
        # The requesting token's user can be a member of the org without being a
        # member of any project's team — Sentry 400s this specific endpoint rather
        # than returning an empty result.
        mock_request.return_value = _response({"detail": "No projects available"}, status_code=400)

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="organization_stats_summary",
            team_id=123,
            job_id="job-id",
        )

        assert list(cast(Any, resp.items())) == []

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_stats_summary_other_400_is_classified_non_retryable(self, mock_request) -> None:
        # Any stats-summary 400 that isn't the skipped no-projects case is deterministic, so it must
        # fail fast with a credential-safe message the source classifies non-retryable — not burn
        # retries on the raw HTTPError (whose URL embeds the org slug).
        mock_request.return_value = _response({"detail": 'Invalid field: "bogus"'}, status_code=400)

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="organization_stats_summary",
            team_id=123,
            job_id="job-id",
        )

        with pytest.raises(SentryStatsSummaryRejectedError) as exc_info:
            list(cast(Any, resp.items()))

        message = str(exc_info.value)
        assert "acme" not in message and "sentry.io" not in message
        assert error_message_matches(message, SentrySource().get_non_retryable_errors())

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_trace_item_attributes_stamps_dataset_and_skips_unavailable_ones(self, mock_request) -> None:
        def side_effect(url, headers=None, params=None, timeout=None):
            dataset = (params or {}).get("dataset")
            if dataset == "spans":
                return _response([{"key": "browser.name", "attributeType": "string"}])
            if dataset == "preprod":
                # Not every organization has every trace item dataset enabled.
                return _response(None, status_code=400)
            return _response([])

        mock_request.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="trace_item_attributes",
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [{"key": "browser.name", "attributeType": "string", "dataset": "spans"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_trace_item_stats_flattens_attribute_distributions(self, mock_request) -> None:
        def side_effect(url, headers=None, params=None, timeout=None):
            if (params or {}).get("itemType") == "spans":
                return _response(
                    {
                        "data": [
                            {
                                "attributeDistributions": {
                                    "data": {
                                        "sentry.device": [
                                            {"label": "mobile", "value": 3},
                                            {"label": "desktop", "value": 1},
                                        ]
                                    }
                                }
                            }
                        ]
                    }
                )
            return _response(None, status_code=403)

        mock_request.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="trace_item_stats",
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [
            {"item_type": "spans", "attribute": "sentry.device", "label": "mobile", "value": 3},
            {"item_type": "spans", "attribute": "sentry.device", "label": "desktop", "value": 1},
        ]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_project_ownership_yields_one_row_per_project_and_skips_missing_config(self, mock_request) -> None:
        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/projects/"):
                return _response([{"id": "1", "slug": "web"}, {"id": "2", "slug": "api"}])
            if url.endswith("/projects/acme/web/ownership/"):
                return _response({"raw": "*.py @backend", "fallthrough": True})
            return _response(None, status_code=404)

        mock_request.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="project_ownership",
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [{"raw": "*.py @backend", "fallthrough": True, "project_id": "1", "project_slug": "web"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_project_stats_flattens_point_pairs(self, mock_request) -> None:
        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/projects/"):
                return _response([{"id": "1", "slug": "web"}])
            if (params or {}).get("stat") == "received":
                return _response([[1772409600, 12], [1772496000, 8]])
            return _response([])

        mock_request.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="project_stats",
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [
            {"stat": "received", "timestamp": 1772409600, "value": 12, "project_id": "1", "project_slug": "web"},
            {"stat": "received", "timestamp": 1772496000, "value": 8, "project_id": "1", "project_slug": "web"},
        ]

    @parameterized.expand(
        [
            ("pre_retention_watermark", 946684800, True),
            ("no_watermark", None, True),
            ("recent_watermark", None, False),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    def test_project_stats_since_never_predates_retention(self, _name, watermark, expect_floor, mock_request) -> None:
        seen_params: list[dict | None] = []
        recent = int((datetime.now(UTC) - timedelta(days=2)).timestamp())

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/projects/"):
                return _response([{"id": "1", "slug": "web"}])
            seen_params.append(params)
            return _response([])

        mock_request.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="project_stats",
            team_id=123,
            job_id="job-id",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark if expect_floor else recent,
        )

        list(cast(Any, resp.items()))

        floor = int((datetime.now(UTC) - timedelta(days=SENTRY_RETENTION_DAYS)).timestamp())
        assert seen_params
        since = seen_params[0]["since"] if seen_params[0] else None
        assert since is not None
        assert since >= floor - 60
        if expect_floor:
            assert abs(since - floor) < 60
        else:
            assert abs(since - recent) < 60


class TestWarehouseParentReuse:
    @pytest.fixture(autouse=True)
    def _fresh_issues_snapshot(self):
        # These cases predate the snapshot cap and assert on the rows the fan-out emits, so pin
        # the parent snapshot ahead of every fixture timestamp to leave that set unchanged.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.parent_snapshot_covers_through",
            return_value=datetime(2999, 1, 1, tzinfo=UTC),
        ):
            yield

    @parameterized.expand(
        [
            ("issue_events", []),
            ("issue_hashes", []),
            ("issue_tag_values", ["issues"]),
            ("issues", []),
            ("projects", []),
            ("project_events", []),
        ]
    )
    def test_get_required_parent_schemas(self, endpoint: str, expected: list[str]) -> None:
        assert SentrySource().get_required_parent_schemas(endpoint) == expected

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.resolve_parent_table_ref",
        side_effect=WarehouseParentTableNotFoundError("issues table is gone"),
    )
    def test_issue_tag_values_falls_back_to_the_api_when_the_table_is_unreadable(self, _mock_resolve, mock_get) -> None:
        # issues reports a completed sync but its table can't be read, so the iterator has to
        # walk the issues endpoint exactly as it does with the feature off.
        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100", "lastSeen": "2026-03-05T12:00:00Z"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response([{"value": "Chrome", "timesSeen": 1}])
            return _response([])

        mock_get.return_value.get.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            source_id="source-1",
            use_warehouse_parent=True,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2020-01-01T00:00:00Z",
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Chrome", "timesSeen": 1, "issue_id": "100", "tag_key": "browser"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.resolve_parent_table_ref",
        return_value=ParentTableRef(uri="s3://bucket/team_123_sentry_x/issues", version=3),
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.iter_parent_pages_from_warehouse"
    )
    def test_issue_tag_values_reads_issues_from_warehouse(self, mock_reader, _mock_resolve, mock_get) -> None:
        mock_reader.return_value = iter([[{"id": "100", "lastSeen": "2026-03-05T12:00:00Z"}]])

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                raise AssertionError("warehouse-parent issue_tag_values must not fetch the issues endpoint")
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response([{"value": "Chrome", "timesSeen": 1}])
            return _response([])

        mock_get.return_value.get.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            source_id="source-1",
            use_warehouse_parent=True,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2020-01-01T00:00:00Z",
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Chrome", "timesSeen": 1, "issue_id": "100", "tag_key": "browser"}]
        mock_reader.assert_called_once_with(
            table=ParentTableRef(uri="s3://bucket/team_123_sentry_x/issues", version=3),
            parent_name="issues",
            # lastSeen is always projected because it carries the scan floor.
            columns=["id", "lastSeen"],
            page_size=100,
            schema_name="issue_tag_values",
            row_filter=_issues_parent_row_filter(datetime(2020, 1, 1, tzinfo=UTC)),
        )

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.parent_snapshot_covers_through",
        return_value=datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC),
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.try_resolve_parent_table",
        return_value=None,
    )
    def test_api_fallback_keeps_values_newer_than_the_stale_snapshot(
        self, _mock_resolve, _mock_snapshot, mock_get
    ) -> None:
        cutoff = datetime(2026, 3, 3, 0, 0, 0, tzinfo=UTC)

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "200", "lastSeen": "2026-03-06T00:00:00Z"}])
            if url.endswith("/organizations/acme/issues/200/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/200/tags/browser/values/"):
                return _response([{"value": "Firefox", "lastSeen": "2026-03-06T00:00:00Z"}])
            return _response([])

        mock_get.return_value.get.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            source_id="source-1",
            use_warehouse_parent=True,
            should_use_incremental_field=True,
            db_incremental_field_last_value=cutoff,
            incremental_field="lastSeen",
        )

        # The live listing has no snapshot behind it, so the stale cap must not apply.
        assert [row["value"] for row in cast(Any, resp.items())] == ["Firefox"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.parent_snapshot_covers_through",
        return_value=datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC),
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.resolve_parent_table_ref",
        return_value=ParentTableRef(uri="s3://bucket/team_123_sentry_x/issues", version=3),
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.iter_parent_pages_from_warehouse"
    )
    def test_issue_tag_values_drops_values_newer_than_the_issues_snapshot(
        self, mock_reader, _mock_resolve, _mock_snapshot, mock_get
    ) -> None:
        cutoff = datetime(2026, 3, 3, 0, 0, 0, tzinfo=UTC)
        mock_reader.return_value = iter([[{"id": "200", "lastSeen": "2026-03-05T00:00:00Z"}]])

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/200/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/200/tags/browser/values/"):
                return _response(
                    [
                        {"value": "Firefox", "lastSeen": "2026-03-06T00:00:00Z"},
                        {"value": "Chrome", "lastSeen": "2026-03-03T12:00:00Z"},
                    ]
                )
            return _response([])

        mock_get.return_value.get.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            source_id="source-1",
            use_warehouse_parent=True,
            should_use_incremental_field=True,
            db_incremental_field_last_value=cutoff,
            incremental_field="lastSeen",
        )

        # Firefox is newer than the snapshot, so emitting it would carry the watermark past
        # issues the snapshot has not shown yet. Chrome sits inside the snapshot and still ships.
        assert [row["value"] for row in cast(Any, resp.items())] == ["Chrome"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.resolve_parent_table_ref",
        return_value=ParentTableRef(uri="s3://bucket/team_123_sentry_x/issues", version=3),
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.iter_parent_pages_from_warehouse"
    )
    def test_issue_tag_values_warehouse_cutoff_filters_instead_of_breaking(
        self, mock_reader, _mock_resolve, mock_get
    ) -> None:
        cutoff = datetime(2026, 3, 3, 0, 0, 0, tzinfo=UTC)
        # Unordered warehouse scan: a stale issue arrives BEFORE a fresh one. API mode breaks
        # on the first stale row (sorted input); warehouse mode must filter and keep scanning.
        mock_reader.return_value = iter(
            [
                [
                    {"id": "100", "lastSeen": "2026-03-01T00:00:00Z"},
                    {"id": "200", "lastSeen": "2026-03-05T00:00:00Z"},
                ]
            ]
        )

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/100/tags/"):
                raise AssertionError("stale issue must be filtered out, not fanned out")
            if url.endswith("/organizations/acme/issues/200/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/200/tags/browser/values/"):
                return _response([{"value": "Chrome", "lastSeen": "2026-03-05T00:00:00Z"}])
            return _response([])

        mock_get.return_value.get.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            source_id="source-1",
            use_warehouse_parent=True,
            should_use_incremental_field=True,
            db_incremental_field_last_value=cutoff,
            incremental_field="lastSeen",
        )

        rows = list(cast(Any, resp.items()))
        assert [row["issue_id"] for row in rows] == ["200"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.resolve_parent_table_ref",
        return_value=ParentTableRef(uri="s3://bucket/team_123_sentry_x/issues", version=3),
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.iter_parent_pages_from_warehouse"
    )
    def test_issue_tag_values_warehouse_skips_issue_deleted_upstream(
        self, mock_reader, _mock_resolve, mock_get
    ) -> None:
        mock_reader.return_value = iter([[{"id": "100", "lastSeen": None}, {"id": "200", "lastSeen": None}]])

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([], status_code=404)
            if url.endswith("/organizations/acme/issues/200/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/200/tags/browser/values/"):
                return _response([{"value": "Chrome"}])
            return _response([])

        mock_get.return_value.get.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            source_id="source-1",
            use_warehouse_parent=True,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2020-01-01T00:00:00Z",
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Chrome", "issue_id": "200", "tag_key": "browser"}]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.resolve_parent_table_ref",
        return_value=ParentTableRef(uri="s3://bucket/team_123_sentry_x/issues", version=3),
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.iter_parent_pages_from_warehouse"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry._request_with_retry")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.make_tracked_session")
    def test_issue_tag_values_warehouse_skips_tag_when_values_endpoint_404s(
        self, mock_get, mock_request, mock_reader, _mock_resolve
    ) -> None:
        # An issue deleted upstream between the tags listing and the values fetch 404s only on
        # the values endpoint — the sync must skip that tag, not fail.
        mock_reader.return_value = iter([[{"id": "100"}, {"id": "200"}]])

        def request_side_effect(url, headers=None, params=None):
            if url.endswith("/tags/"):
                return _response([{"key": "browser"}])
            if "/issues/100/tags/browser/values/" in url:
                return _response([], status_code=404)
            if "/issues/200/tags/browser/values/" in url:
                return _response([{"value": "Chrome"}])
            return _response([])

        mock_request.side_effect = request_side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            source_id="source-1",
            use_warehouse_parent=True,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2020-01-01T00:00:00Z",
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Chrome", "issue_id": "200", "tag_key": "browser"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sentry.sentry.build_dependent_resource")
    def test_fanout_endpoint_threads_warehouse_flag(self, mock_build) -> None:
        mock_build.return_value = iter([])

        sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_hashes",
            team_id=123,
            job_id="job-id",
            source_id="source-1",
            use_warehouse_parent=True,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2020-01-01T00:00:00Z",
        )

        kwargs = mock_build.call_args.kwargs
        assert kwargs["source_id"] == "source-1"
        assert kwargs["use_warehouse_parent"] is True


def test_no_sentry_endpoint_reads_its_parent_from_the_warehouse():
    # Sentry's issue listing is clamped by per-org event retention, a bound a snapshot scan
    # cannot reproduce, so config-driven warehouse fan-out shipped 3-5x row inflation on
    # aged orgs. Re-enabling parent_source="warehouse" here needs a parity story first —
    # see SENTRY_FANOUT_PARENT_WINDOW in settings.
    warehouse_children = [
        name
        for name, config in SENTRY_ENDPOINTS.items()
        if config.fanout is not None and config.fanout.parent_source == "warehouse"
    ]
    assert warehouse_children == []
