from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.windmill import (
    WindmillSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.settings import WINDMILL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.source import WindmillSource
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill import (
    PER_PAGE,
    WindmillHostNotAllowedError,
    WindmillResumeConfig,
    _format_after,
    normalize_base_url,
    validate_credentials,
)

BASE_URL = "https://app.windmill.dev"
WORKSPACE = "my-workspace"

HOST_SAFE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill._is_host_safe"


def _json_response(body: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


def _page(n: int) -> list[dict[str, Any]]:
    return [{"id": str(i)} for i in range(n)]


def _driver() -> SourceDriver:
    return SourceDriver(WindmillSource(), WindmillSourceConfig(host=BASE_URL, workspace=WORKSPACE, api_token="token"))


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://app.windmill.dev", "https://app.windmill.dev/api"),
            ("https://app.windmill.dev/", "https://app.windmill.dev/api"),
            # A user pasting the full API root must not produce /api/api.
            ("https://app.windmill.dev/api", "https://app.windmill.dev/api"),
            ("https://app.windmill.dev/api/", "https://app.windmill.dev/api"),
            # Plaintext is upgraded to https; a scheme-less host gets one.
            ("http://windmill.internal.example.com", "https://windmill.internal.example.com/api"),
            ("windmill.example.com", "https://windmill.example.com/api"),
            ("  https://app.windmill.dev  ", "https://app.windmill.dev/api"),
            # Embedded userinfo / query / fragment must not change the authority we connect to,
            # so the SSRF host check can't diverge from the effective request host.
            ("https://user:pw@app.windmill.dev", "https://app.windmill.dev/api"),
            ("https://app.windmill.dev?x=1", "https://app.windmill.dev/api"),
            ("https://app.windmill.dev#frag", "https://app.windmill.dev/api"),
            # A custom port is preserved for self-hosted instances.
            ("https://windmill.internal:8080", "https://windmill.internal:8080/api"),
        ],
    )
    def test_normalizes(self, value, expected):
        assert normalize_base_url(value) == expected


class TestFormatAfter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_after(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (404, False, "Could not access Windmill workspace 'my-workspace' with this token"),
        ],
    )
    def test_status_mapping(self, status_code, expected_valid, expected_message):
        with scripted_network(always(_json_response({"message": "x"}, status_code))) as network:
            valid, message = validate_credentials("token", BASE_URL, WORKSPACE)

        assert valid is expected_valid
        assert message == expected_message
        assert network.requests_log[0].url == f"{BASE_URL}/api/w/{WORKSPACE}/users/whoami"

    def test_uses_no_redirect_session(self):
        redirect = ScriptedResponse(status=302, headers={"Location": "https://evil.example/whoami"}, body=b"moved")

        with scripted_network([redirect]) as network:
            validate_credentials("token", BASE_URL, WORKSPACE)

        assert [request.url for request in network.requests_log] == [f"{BASE_URL}/api/w/{WORKSPACE}/users/whoami"]

    def test_redacts_api_token_in_tracked_session(self):
        # The bearer token rides in a header the name-based scrubbers can't see, so it must be
        # value-redacted or it leaks into captured request samples.
        with scripted_network([_json_response({})]) as network:
            validate_credentials("token", BASE_URL, WORKSPACE)

        assert network.session_options[0]["redact_values"] == ("token",)

    @mock.patch(HOST_SAFE_PATCH)
    def test_blocks_internal_host_when_team_id_given(self, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        with scripted_network([]) as network:
            valid, message = validate_credentials("token", "https://10.0.0.1", WORKSPACE, team_id=42)

        assert valid is False
        assert message == "host not allowed"
        assert network.requests_log == []


class TestSync:
    def test_saves_next_page_after_each_committed_page(self):
        # The resume hook fires after a page is yielded and persists the NEXT page to fetch, so a
        # crash re-scans from a page whose predecessors are all committed (merge dedupes overlap).
        result = _driver().run(
            "completed_jobs",
            [_json_response(_page(PER_PAGE)), _json_response(_page(PER_PAGE)), _json_response(_page(1))],
        )

        # Full pages 1 and 2 each checkpoint the following page; the short final page 3 checkpoints
        # nothing (no next page remains).
        assert [state.page for state in result.saved_states] == [2, 3]

    def test_resumes_from_saved_page(self):
        result = _driver().run("completed_jobs", [_json_response(_page(2))], resume_state=WindmillResumeConfig(page=7))

        assert result.params("page")[0] == "7"

    def test_incremental_applies_after_filter(self):
        result = _driver().run(
            "completed_jobs",
            [_json_response(_page(1))],
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="started_at",
        )

        started_after = result.requests[0].param("started_after")
        assert started_after is not None and started_after.startswith("2026-01-01")

    def test_full_refresh_endpoint_never_sends_after_filter(self):
        # scripts has no server-side timestamp filter, so a cutoff must never leak into params.
        result = _driver().run(
            "scripts",
            [_json_response(_page(1))],
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="created_at",
        )

        assert "created_after" not in result.requests[0].query
        assert "started_after" not in result.requests[0].query

    def test_bearer_token_redacted_via_client_session(self):
        # The bearer token is supplied through framework auth, whose secret values feed the tracked
        # session's value redaction so the token can't leak into captured samples or error text.
        result = _driver().run("completed_jobs", [_json_response(_page(1))])

        assert result.session_options[0]["redact_values"] == ("token",)

    def test_does_not_follow_redirects(self):
        redirect = ScriptedResponse(status=302, headers={"Location": "https://evil.example/jobs"}, body=b"moved")

        result = _driver().run("completed_jobs", [redirect])

        assert len(result.requests) == 1
        assert result.requests[0].url.startswith(BASE_URL)

    @pytest.mark.parametrize(
        "endpoint, page_sizes, expected_pages",
        [
            # A short page ends the walk for endpoints whose pages are filled by LIMIT/OFFSET.
            ("completed_jobs", [PER_PAGE, 1], ["1", "2"]),
            # listFolders drops out-of-scope folders after LIMIT, so a short page can precede more
            # rows and only an empty page ends the walk.
            ("folders", [PER_PAGE, 1, 3, 0], ["1", "2", "3", "4"]),
        ],
    )
    def test_page_walk_terminates(self, endpoint, page_sizes, expected_pages):
        result = _driver().run(endpoint, [_json_response(_page(n)) for n in page_sizes])

        assert result.raised is None
        assert result.params("page") == expected_pages
        assert len(result.rows) == sum(page_sizes)

    @pytest.mark.parametrize(
        "endpoint, expected_url",
        [
            ("workspaces", f"{BASE_URL}/api/workspaces/list"),
            ("user_usage", f"{BASE_URL}/api/w/{WORKSPACE}/users/list_usage"),
        ],
    )
    def test_unpaginated_endpoint_makes_one_request(self, endpoint, expected_url):
        rows = [{"id": "ws-1", "email": "a@example.com", "executions": 12}]

        result = _driver().run(endpoint, [_json_response(rows)])

        assert result.raised is None
        assert result.urls == [expected_url]
        assert result.rows == rows

    def test_groups_fetch_each_detail_for_members(self):
        detail_alpha = {"name": "alpha", "summary": "A", "members": ["ann", "bob"], "extra_perms": {}}
        result = _driver().run(
            "groups",
            route(
                {
                    "/groups/list": [
                        _json_response([{"name": "alpha", "extra_perms": {}}, {"name": "gone", "extra_perms": {}}]),
                    ],
                    "/groups/get/alpha": [_json_response(detail_alpha)],
                    # Deleted between the list call and its detail call.
                    "/groups/get/gone": [_json_response({"error": "not found"}, status_code=404)],
                }
            ),
        )

        assert result.raised is None
        assert result.paths == [
            f"/api/w/{WORKSPACE}/groups/list",
            f"/api/w/{WORKSPACE}/groups/get/alpha",
            f"/api/w/{WORKSPACE}/groups/get/gone",
        ]
        assert [{k: row[k] for k in detail_alpha} for row in result.rows] == [detail_alpha]

    def test_groups_percent_encode_names_in_detail_path(self):
        result = _driver().run(
            "groups",
            route(
                {
                    "/groups/list": [_json_response([{"name": "team#ops/eu", "extra_perms": {}}])],
                    "/groups/get/team%23ops%2Feu": [_json_response({"name": "team#ops/eu", "members": ["ann"]})],
                }
            ),
        )

        assert result.raised is None
        assert result.paths[-1] == f"/api/w/{WORKSPACE}/groups/get/team%23ops%2Feu"
        assert [row["members"] for row in result.rows] == [["ann"]]

    @mock.patch(HOST_SAFE_PATCH)
    def test_raises_when_host_not_allowed(self, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        result = _driver().run("completed_jobs", [_json_response(_page(1))])

        assert isinstance(result.raised, WindmillHostNotAllowedError)
        assert result.requests == []


class TestWindmillSourceResponse:
    @pytest.mark.parametrize("config", list(WINDMILL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_fields(self, config):
        # Partition keys must be immutable creation timestamps, never edited/last-* fields.
        if config.partition_key:
            assert config.partition_key in {"created_at", "timestamp"}
