from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import Mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.cloudsmith import (
    INVALID_WORKSPACE_ERROR,
    CloudsmithPaginator,
    CloudsmithResumeConfig,
    _cloudsmith_incremental_window,
    _format_uploaded_filter,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.settings import CLOUDSMITH_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.source import CloudsmithSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudsmith import (
    CloudsmithSourceConfig,
)


def _response(page_total: str | None) -> Mock:
    response = Mock()
    response.headers = {} if page_total is None else {"X-Pagination-PageTotal": page_total}
    return response


class TestCloudsmithTransport:
    @staticmethod
    def _driver(workspace: str = "acme") -> SourceDriver:
        return SourceDriver(CloudsmithSource(), CloudsmithSourceConfig(api_key="key", workspace=workspace))

    @staticmethod
    def _page(rows: list[dict[str, Any]], total: str = "1") -> ScriptedResponse:
        return ScriptedResponse(json=rows, headers={"X-Pagination-PageTotal": total})

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
    def test_validate_credentials_status_mapping(
        self, status: int, schema_name: str | None, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            result = validate_credentials(api_key="key", workspace="acme", schema_name=schema_name)

        assert result == (expected_valid, expected_message)
        assert network.requests_log
        assert all(request.url == "https://api.cloudsmith.io/v1/namespaces/acme/" for request in network.requests_log)
        assert all(request.headers["x-api-key"] == "key" for request in network.requests_log)
        assert network.session_options == [{"redact_values": ("key",), "capture": False}]

    @parameterized.expand([("../../user", None), ("acme/repo", None), ("", None), ("with space", None)])
    def test_validate_credentials_rejects_unsafe_workspace(self, workspace: str, _unused: None) -> None:
        # The workspace is interpolated straight into the request path, so a slug carrying
        # path separators has to be rejected before any request is made.
        with scripted_network([]) as network:
            assert validate_credentials(api_key="key", workspace=workspace) == (False, INVALID_WORKSPACE_ERROR)
        assert network.requests_log == []
        assert network.session_options == []

    def test_cloudsmith_source_rejects_unsafe_workspace(self) -> None:
        result = self._driver(workspace="../other").run("repositories", [])

        assert isinstance(result.raised, ValueError)
        assert "valid Cloudsmith workspace slug" in str(result.raised)
        assert result.requests == []

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

    @parameterized.expand(
        [("packages",), ("entitlements",), ("webhooks",), ("repository_audit_log",), ("package_dependencies",)]
    )
    def test_get_resource_rejects_fanout_endpoints(self, endpoint) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(CLOUDSMITH_ENDPOINTS[endpoint], "acme")

    def test_source_saves_checkpoints_after_batches(self) -> None:
        result = self._driver().run(
            "repositories",
            [
                self._page([{"slug_perm": "first"}], "3"),
                self._page([{"slug_perm": "second"}], "3"),
                self._page([{"slug_perm": "third"}], "3"),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2", "3"]
        assert result.saved_states == [
            CloudsmithResumeConfig(paginator_state={"page": 2}),
            CloudsmithResumeConfig(paginator_state={"page": 3}),
        ]
        assert result.committed_states == result.saved_states
        # A terminal (None) checkpoint is not persisted - the Redis TTL handles cleanup.
        assert all(state.paginator_state for state in result.saved_states)

    @parameterized.expand(
        [
            # The entitlement token is a live download credential.
            (
                "entitlements",
                {"slug_perm": "tok", "name": "ci", "token": "secret"},
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
                },
                {"slug_perm": "wh", "is_active": True, "repository_slug": "prod"},
            ),
        ]
    )
    def test_fanout_strips_secret_fields(
        self, endpoint: str, raw_row: dict[str, Any], expected_row: dict[str, Any]
    ) -> None:
        # Credential-bearing fields must never land in a warehouse table any project member can query.
        result = self._driver().run(
            endpoint,
            [self._page([{"slug": "prod"}]), self._page([raw_row])],
        )

        assert result.raised is None
        assert result.rows == [expected_row]

    @parameterized.expand(
        [
            ("packages", {"sort": "date"}),
            ("entitlements", {"sort": "name"}),
            ("webhooks", None),
            ("repository_audit_log", None),
        ]
    )
    def test_fanout_wiring(self, endpoint: str, expected_child_params: dict[str, str] | None) -> None:
        child_prefix = CLOUDSMITH_ENDPOINTS[endpoint].path.split("/")[1]
        skipped_path = f"/{child_prefix}/acme/skip/"
        child_path = f"/{child_prefix}/acme/prod/"
        result = self._driver().run(
            endpoint,
            [self._page([{"slug": "skip"}, {"slug": "prod"}]), self._page([{"slug_perm": "item"}])],
            resume_state=CloudsmithResumeConfig(paginator_state={"completed": [skipped_path], "current": None}),
        )

        assert result.raised is None
        assert result.paths == ["/v1/repos/acme/", f"/v1{child_path}"]
        assert result.params("page_size") == ["100", "100"]
        # `{owner}` has to be pre-formatted: the fan-out helper only substitutes `{repo}`.
        assert result.params("page") == ["1", "1"]
        assert result.requests[0].param("sort") == "created_at"
        assert result.requests[1].param("sort") == (expected_child_params or {}).get("sort")
        assert result.rows == [{"slug_perm": "item", "repository_slug": "prod"}]
        assert result.saved_states[-1].paginator_state["completed"] == [child_path, skipped_path]

    @parameterized.expand(
        [
            ("incremental", True, datetime(2026, 3, 1, tzinfo=UTC)),
            ("first_sync", True, None),
            ("non_incremental", False, datetime(2026, 3, 1, tzinfo=UTC)),
        ]
    )
    def test_packages_passes_watermark(
        self, _name: str, should_use_incremental_field: bool, last_value: datetime | None
    ) -> None:
        result = self._driver().run(
            "packages",
            [self._page([{"slug": "prod"}]), self._page([{"slug_perm": "item"}])],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
            incremental_field="uploaded_at" if should_use_incremental_field else None,
        )

        assert result.raised is None
        assert result.paths == ["/v1/repos/acme/", "/v1/packages/acme/prod/"]
        assert result.requests[0].param("query") is None
        assert result.requests[1].param("query") == (
            f"uploaded:>={last_value:%Y-%m-%dT%H:%M:%SZ}"
            if should_use_incremental_field and last_value is not None
            else "uploaded:>=1970-01-01T00:00:00Z"
            if should_use_incremental_field
            else None
        )

    def test_quota_history_reads_rows_from_single_object_response(self) -> None:
        periods = [
            {"start": "2026-08-01T00:00:00Z", "end": "2026-08-31T23:59:59Z", "plan": "Pro", "days": 31},
            {"start": "2026-09-01T00:00:00Z", "end": "2026-09-30T23:59:59Z", "plan": "Pro", "days": 30},
        ]
        result = self._driver().run("quota_history", [ScriptedResponse(json={"history": periods})])

        assert result.raised is None
        assert result.paths == ["/v1/quota/history/acme/"]
        # The endpoint is not paginated, so no page params are sent.
        assert result.params("page") == [None]
        assert result.params("page_size") == [None]
        assert result.rows == periods

    def test_package_dependencies_chains_repositories_then_packages(self) -> None:
        result = self._driver().run(
            "package_dependencies",
            [
                self._page([{"slug": "prod"}]),
                self._page([{"slug_perm": "pkg1", "repository": "prod"}, {"slug_perm": "gone", "repository": "prod"}]),
                ScriptedResponse(
                    json={
                        "dependencies": [
                            {"name": "requests", "version": "2.31", "operator": ">=", "dep_type": "Requires"},
                            {"name": "urllib3", "version": None, "operator": None, "dep_type": "Requires"},
                        ]
                    }
                ),
                # A package deleted between the packages page and its dependencies fetch.
                ScriptedResponse(status=404, json={"detail": "Not found."}),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/v1/repos/acme/",
            "/v1/packages/acme/prod/",
            "/v1/packages/acme/prod/pkg1/dependencies/",
            "/v1/packages/acme/prod/gone/dependencies/",
        ]
        assert result.params("page_size") == ["100", "100", None, None]
        assert result.rows == [
            {
                "name": "requests",
                "version": "2.31",
                "operator": ">=",
                "dep_type": "Requires",
                "repository_slug": "prod",
                "package_slug_perm": "pkg1",
            },
            {
                "name": "urllib3",
                "version": None,
                "operator": None,
                "dep_type": "Requires",
                "repository_slug": "prod",
                "package_slug_perm": "pkg1",
            },
        ]
