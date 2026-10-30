from datetime import UTC, datetime
from typing import Any

from unittest.mock import patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.unstructured import (
    UnstructuredSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.source import UnstructuredSource
from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.unstructured import (
    DEFAULT_BASE_URL,
    FAILED_FILES_PAGE_SIZE,
    NOTIFICATIONS_PAGE_SIZE,
    WORKFLOWS_PAGE_SIZE,
    UnstructuredResumeConfig,
    UnstructuredRetryableError,
    normalize_base_url,
    validate_credentials,
)

MIXINS_IS_CLOUD = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.is_cloud"


def _driver(base_url: str | None = None, api_key: str = "key") -> SourceDriver:
    return SourceDriver(UnstructuredSource(), UnstructuredSourceConfig(api_key=api_key, base_url=base_url))


class TestNormalizeBaseUrl:
    @parameterized.expand(
        [
            ("none_falls_back", None, DEFAULT_BASE_URL),
            ("empty_falls_back", "", DEFAULT_BASE_URL),
            ("whitespace_falls_back", "   ", DEFAULT_BASE_URL),
            ("strips_trailing_slash", "https://custom.example.com/", "https://custom.example.com"),
            ("custom_host_kept", "https://eu.platform.example.com", "https://eu.platform.example.com"),
        ]
    )
    def test_normalize_base_url(self, _name: str, value: str | None, expected: str) -> None:
        assert normalize_base_url(value) == expected


class TestFetch:
    @parameterized.expand([("rate_limited", 429), ("bad_gateway", 502), ("server_error", 500)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        result = _driver().run("jobs", always(ScriptedResponse(status=status, json={"detail": "later"})))

        assert isinstance(result.raised, UnstructuredRetryableError)

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        result = _driver().run("jobs", [ScriptedResponse(status=status, json={"detail": "nope"})])

        assert isinstance(result.raised, requests.HTTPError)

    @parameterized.expand([("moved_permanently", 301), ("found", 302), ("temporary_redirect", 307)])
    def test_redirect_response_raises(self, _name: str, status: int) -> None:
        # The session never follows redirects (SSRF hardening); a 30x must surface as an error so a
        # customer-controlled host can't quietly point a credentialed request at another origin.
        result = _driver().run(
            "jobs", [ScriptedResponse(status=status, headers={"Location": "https://evil.example.com"})]
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert result.urls == [f"{DEFAULT_BASE_URL}/api/v1/jobs/"]

    def test_non_list_body_returns_empty(self) -> None:
        # A shape change (envelope instead of bare array) must degrade to an empty sync, not crash.
        result = _driver().run("jobs", [ScriptedResponse(json={"data": []})])

        assert result.raised is None
        assert result.rows == []


class TestGetRows:
    def test_paginated_walks_pages_until_short_page(self) -> None:
        full_page = [{"id": str(i)} for i in range(WORKFLOWS_PAGE_SIZE)]
        last_page = [{"id": "last"}]
        result = _driver().run("workflows", [ScriptedResponse(json=full_page), ScriptedResponse(json=last_page)])

        assert result.items == [full_page, last_page]
        assert len(result.requests) == 2
        # First request starts at page 1.
        assert result.params("page") == ["1", "2"]
        # State is saved after the full page (more to come); the short page ends the walk.
        assert result.saved_states == [UnstructuredResumeConfig(next_page=2)]

    def test_paginated_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "workflows",
            [ScriptedResponse(json=[{"id": "x"}])],
            resume_state=UnstructuredResumeConfig(next_page=3),
        )

        assert result.items == [[{"id": "x"}]]
        # Resumed straight into the saved page rather than restarting at page 1.
        assert result.params("page") == ["3"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("workflows", [ScriptedResponse(json=[{"id": "x"}])])

        assert result.params("page") == ["1"]

    @parameterized.expand(["sources", "destinations"])
    def test_connector_config_is_stripped(self, endpoint: str) -> None:
        # The connector `config` object holds raw secrets (DB passwords, OAuth tokens, cloud keys); it
        # must never be persisted. Non-secret inventory fields are kept.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(
                    json=[{"id": "c1", "name": "prod", "type": "s3", "config": {"key": "AKIA...", "secret": "shh"}}]
                )
            ],
        )

        assert result.items == [[{"id": "c1", "name": "prod", "type": "s3"}]]

    def test_session_pins_redirects_off_and_redacts_key(self) -> None:
        # Locks in the SSRF hardening: the credentialed session must never follow redirects and must
        # register the key for value-based redaction so it can't leak off-origin or into a sample.
        result = _driver(api_key="secret-key").run("jobs", [ScriptedResponse(json=[])])

        assert result.session_options[0]["allow_redirects"] is False
        assert result.session_options[0]["redact_values"] == ("secret-key",)

    @parameterized.expand([("secret_endpoint", "sources", False), ("plain_endpoint", "jobs", True)])
    def test_capture_disabled_for_secret_bearing_endpoints(self, _name: str, endpoint: str, capture: bool) -> None:
        # The adapter captures the raw body before `_drop_sensitive_fields` runs, so capture must be
        # off for endpoints whose responses carry the connector `config` secrets.
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.session_options[0]["capture"] is capture

    def test_unsafe_host_blocks_fetch(self) -> None:
        # A host resolving to an internal address must be rejected before the key is ever sent.
        with patch(MIXINS_IS_CLOUD, return_value=True):
            result = _driver("https://169.254.169.254").run("jobs", [])

        assert isinstance(result.raised, ValueError)
        assert result.requests == []

    @parameterized.expand(
        [
            ("raw_backslash_userinfo", "https://169.254.169.254\\@example.com"),
            ("userinfo", "https://user@169.254.169.254"),
            ("encoded_backslash", "https://169.254.169.254%5c@example.com"),
            ("encoded_at", "https://169.254.169.254%40example.com"),
        ]
    )
    def test_parser_differential_host_is_rejected(self, _name: str, base_url: str) -> None:
        # urlparse and the HTTP client disagree on the host for these URLs, so `169.254.169.254\@x`
        # validates as `x` yet the client may connect to the IP. Reject on the character screen before
        # any request, with no host-safety override, so the rejection can only come from the screen itself.
        result = _driver(base_url).run("jobs", [])

        assert isinstance(result.raised, ValueError)
        assert result.requests == []


JOB_A = "11111111-1111-4111-8111-111111111111"
JOB_B = "22222222-2222-4222-8222-222222222222"
JOB_C = "33333333-3333-4333-8333-333333333333"


def _job(job_id: str, failed_file_count: int | None = None) -> dict[str, Any]:
    return {
        "id": job_id,
        "workflow_id": "wf-1",
        "created_at": "2026-01-02T03:04:05Z",
        "status": "COMPLETED",
        "failed_file_count": failed_file_count,
    }


def _failed_file(document: str, node_id: str = "node-partition") -> dict[str, Any]:
    return {"document": document, "error": "could not parse", "node": {"id": node_id, "type": "partition"}}


class TestJobFanOut:
    def test_failed_files_skips_clean_jobs_and_walks_offset_pages(self) -> None:
        result = _driver().run(
            "job_failed_files",
            route(
                {
                    "/api/v1/jobs/": [ScriptedResponse(json=[_job(JOB_A, 0), _job(JOB_B, 3), _job(JOB_C)])],
                    f"/api/v1/jobs/{JOB_B}/failed-files": [
                        ScriptedResponse(
                            json={"failed_files": [_failed_file("a.pdf"), _failed_file("b.pdf")], "next_offset": 2}
                        ),
                        ScriptedResponse(json={"failed_files": [_failed_file("c.pdf")], "next_offset": None}),
                    ],
                    f"/api/v1/jobs/{JOB_C}/failed-files": [ScriptedResponse(status=404, json={"detail": "gone"})],
                }
            ),
        )

        assert result.raised is None
        assert f"/api/v1/jobs/{JOB_A}/failed-files" not in result.paths
        assert result.params("offset") == [None, "0", "2", "0"]
        assert result.params("limit")[1:] == [str(FAILED_FILES_PAGE_SIZE)] * 3
        assert [row["document"] for row in result.rows] == ["a.pdf", "b.pdf", "c.pdf"]
        assert result.rows[0] == {
            **_failed_file("a.pdf"),
            "job_id": JOB_B,
            "workflow_id": "wf-1",
            "job_created_at": "2026-01-02T03:04:05Z",
            "node_id": "node-partition",
        }

    @parameterized.expand(
        [
            ("no_next_offset", {"failed_files": [{"document": "a.pdf", "error": "x", "node": {"id": "n"}}]}),
            ("next_offset_not_ahead", {"failed_files": [], "next_offset": 0}),
        ]
    )
    def test_failed_files_stops_without_a_forward_offset(self, _name: str, body: dict[str, Any]) -> None:
        result = _driver().run(
            "job_failed_files",
            route(
                {
                    "/api/v1/jobs/": [ScriptedResponse(json=[_job(JOB_A, 1)])],
                    f"/api/v1/jobs/{JOB_A}/failed-files": [ScriptedResponse(json=body)],
                }
            ),
        )

        assert result.raised is None
        assert len(result.requests) == 2

    def test_job_details_adds_job_fields_and_skips_deleted_jobs(self) -> None:
        details = {"id": JOB_A, "processing_status": "SUCCESS", "node_stats": [{"node_id": "n", "success": 4}]}
        result = _driver().run(
            "job_details",
            route(
                {
                    "/api/v1/jobs/": [ScriptedResponse(json=[_job(JOB_A), _job(JOB_B)])],
                    f"/api/v1/jobs/{JOB_A}/details": [ScriptedResponse(json=details)],
                    f"/api/v1/jobs/{JOB_B}/details": [ScriptedResponse(status=404, json={"detail": "gone"})],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{**details, "workflow_id": "wf-1", "job_created_at": "2026-01-02T03:04:05Z"}]

    def test_per_job_server_error_still_fails_the_sync(self) -> None:
        # Only a 404 means the job is gone; any other error must not silently drop the job's rows.
        result = _driver().run(
            "job_details",
            route(
                {
                    "/api/v1/jobs/": [ScriptedResponse(json=[_job(JOB_A)])],
                    f"/api/v1/jobs/{JOB_A}/details": [ScriptedResponse(status=403, json={"detail": "no"})],
                }
            ),
        )

        assert isinstance(result.raised, requests.HTTPError)


def _event(event_id: str, created_at: str = "2026-03-01T00:00:00Z") -> dict[str, Any]:
    return {"id": event_id, "event_type": "job.completed", "payload": {}, "created_at": created_at}


class TestNotifications:
    def test_walks_cursor_pages_and_stages_each_cursor_before_its_page(self) -> None:
        result = _driver().run(
            "notifications",
            [
                ScriptedResponse(json={"events": [_event("e1"), _event("e2")], "next_cursor": "c1"}),
                ScriptedResponse(json={"events": [], "next_cursor": "c2"}),
                ScriptedResponse(json={"events": [_event("e3")], "next_cursor": None}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["e1", "e2", "e3"]
        assert result.params("cursor") == [None, "c1", "c2"]
        assert result.params("limit") == [str(NOTIFICATIONS_PAGE_SIZE)] * 3
        assert result.saved_states == [
            UnstructuredResumeConfig(next_cursor="c1"),
            UnstructuredResumeConfig(next_cursor="c2"),
        ]
        assert result.committed_states == result.saved_states
        assert result.response is not None and result.response.sort_mode == "desc"

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "notifications",
            [ScriptedResponse(json={"events": [_event("e9")], "next_cursor": None})],
            resume_state=UnstructuredResumeConfig(next_cursor="c7"),
        )

        assert result.params("cursor") == ["c7"]
        assert [row["id"] for row in result.rows] == ["e9"]

    def test_repeated_cursor_ends_the_walk(self) -> None:
        result = _driver().run(
            "notifications",
            [
                ScriptedResponse(json={"events": [_event("e1")], "next_cursor": "c1"}),
                ScriptedResponse(json={"events": [_event("e1")], "next_cursor": "c1"}),
            ],
        )

        assert result.raised is None
        assert len(result.requests) == 2

    @parameterized.expand(
        [
            ("incremental_datetime", True, datetime(2026, 2, 1, 12, 0), "2026-02-01T12:00:00+00:00"),
            ("incremental_string", True, "2026-02-01T12:00:00Z", "2026-02-01T12:00:00Z"),
            ("incremental_first_sync", True, None, None),
            ("full_refresh_ignores_watermark", False, datetime(2026, 2, 1, tzinfo=UTC), None),
        ]
    )
    def test_since_follows_the_incremental_watermark(
        self, _name: str, incremental: bool, last_value: Any, expected_since: str | None
    ) -> None:
        result = _driver().run(
            "notifications",
            [ScriptedResponse(json={"events": [], "next_cursor": None})],
            incremental_field="created_at",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.params("since") == [expected_since]

    def test_non_object_body_returns_empty(self) -> None:
        result = _driver().run("notifications", [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.rows == []


class TestUnstructuredSource:
    @parameterized.expand(["workflows", "jobs", "sources", "destinations"])
    def test_source_response_contract(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # created_at is stable (set once at creation) so partitions never churn.
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"


class TestValidateCredentials:
    def test_session_pins_redirects_off_and_redacts_key(self) -> None:
        # Validation carries the key to a user-configurable host; pin redirects off and redact the key.
        with scripted_network([ScriptedResponse(json=[])]) as network:
            validate_credentials(DEFAULT_BASE_URL, "secret-key", team_id=1)

        assert network.session_options[0]["allow_redirects"] is False
        assert network.session_options[0]["redact_values"] == ("secret-key",)

    def test_unsafe_host_rejected_before_request(self) -> None:
        with patch(MIXINS_IS_CLOUD, return_value=True), scripted_network([]) as network:
            ok, msg = validate_credentials("https://169.254.169.254", "key", team_id=1)
        assert ok is False
        assert msg is not None and "internal or private IP" in msg
        assert network.requests_log == []

    @parameterized.expand(
        [
            ("raw_backslash_userinfo", "https://169.254.169.254\\@example.com"),
            ("userinfo", "https://user@169.254.169.254"),
            ("encoded_backslash", "https://169.254.169.254%5c@example.com"),
        ]
    )
    def test_parser_differential_host_is_rejected(self, _name: str, base_url: str) -> None:
        # Validation carries the key to the host, so the same parser-differential bypass must be
        # rejected here before any request, with no host-safety override.
        with scripted_network([]) as network:
            ok, _msg = validate_credentials(base_url, "key", team_id=1)
        assert ok is False
        assert network.requests_log == []
