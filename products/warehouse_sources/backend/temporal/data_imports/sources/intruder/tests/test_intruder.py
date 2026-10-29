from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.intruder import (
    IntruderSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.intruder import (
    PAGE_SIZE,
    IntruderResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.settings import (
    INCREMENTAL_FIELDS,
    INTRUDER_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.source import IntruderSource

BASE = "https://api.intruder.io/v1"


def _driver() -> SourceDriver:
    return SourceDriver(IntruderSource(), IntruderSourceConfig(access_token="tok"))


def _page(rows: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"results": rows, "next": next_url})


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("targets", ["id"], None, None),
            ("scans", ["id"], "datetime", "created_at"),
            ("scan_schedules", ["id"], None, None),
            ("issues", ["id"], None, None),
            ("occurrences", ["issue_id", "id"], "datetime", "first_seen_at"),
            ("issue_targets", ["issue_id", "id"], None, None),
            ("fixed_occurrences", ["id"], "datetime", "first_seen_at"),
            ("tags", ["name"], None, None),
        ]
    )
    def test_primary_keys_and_partitioning(
        self,
        endpoint: str,
        expected_pks: list[str],
        expected_partition_mode: str | None,
        expected_partition_key: str | None,
    ) -> None:
        result = _driver().run(endpoint, [_page([])])
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_pks
        assert result.response.partition_mode == expected_partition_mode
        assert result.response.partition_keys == ([expected_partition_key] if expected_partition_key else None)


class TestEndpointConfig:
    def test_occurrences_is_fan_out_with_composite_key(self) -> None:
        config = INTRUDER_ENDPOINTS["occurrences"]
        assert config.fan_out_over_issues is True
        # An occurrence id is only unique within its issue, so the key must include the parent issue.
        assert config.primary_keys == ["issue_id", "id"]

    def test_tags_keyed_by_name(self) -> None:
        # Tags are bare {name} objects with no numeric id, so name is the primary key.
        assert INTRUDER_ENDPOINTS["tags"].primary_keys == ["name"]

    def test_no_endpoint_advertises_incremental_fields(self) -> None:
        # Intruder exposes no server-side timestamp filter, so nothing advertises incremental fields.
        assert all(fields == [] for fields in INCREMENTAL_FIELDS.values())


class TestStandardPagination:
    def test_resumes_from_saved_next_url(self) -> None:
        # With saved state the first request must be the saved cursor, not the initial page.
        state = IntruderResumeConfig(next_url=f"{BASE}/targets/?limit={PAGE_SIZE}&offset=100")
        result = _driver().run("targets", [_page([{"id": 2}])], resume_state=state)
        assert result.raised is None
        assert result.paths == ["/v1/targets/"]
        assert result.params("limit") == [str(PAGE_SIZE)]
        assert result.params("offset") == ["100"]
        assert result.rows == [{"id": 2}]


class TestOccurrencesFanOut:
    @parameterized.expand([("occurrences", "occurrences"), ("issue_targets", "targets")])
    def test_injects_parent_issue_id_into_every_row(self, endpoint: str, child_path: str) -> None:
        # The child response has no issue reference; without the injected issue_id the composite
        # primary key [issue_id, id] collapses to id and duplicate rows accumulate across issues.
        result = _driver().run(
            endpoint,
            route(
                {
                    "/v1/issues/": [_page([{"id": 10}, {"id": 20}])],
                    f"/v1/issues/10/{child_path}/": [_page([{"id": 1}, {"id": 2}])],
                    f"/v1/issues/20/{child_path}/": [_page([{"id": 3}])],
                }
            ),
        )
        assert result.raised is None
        assert result.paths == [
            "/v1/issues/",
            f"/v1/issues/10/{child_path}/",
            f"/v1/issues/20/{child_path}/",
        ]
        assert result.params("limit") == [str(PAGE_SIZE)] * 3
        assert result.rows == [
            {"id": 1, "issue_id": 10},
            {"id": 2, "issue_id": 10},
            {"id": 3, "issue_id": 20},
        ]

    def test_resume_from_deleted_issue_restarts_from_first(self) -> None:
        # The in-progress issue from the saved state no longer exists — its checkpoint is ignored and
        # the surviving issues sync fresh (merge dedupes any re-pulled rows).
        state = IntruderResumeConfig(
            fanout_state={
                "completed": [],
                "current": "/issues/999/occurrences/",
                "child_state": {"next_url": f"{BASE}/issues/999/occurrences/?limit={PAGE_SIZE}&offset=100"},
            }
        )
        result = _driver().run(
            "occurrences",
            route(
                {
                    "/v1/issues/": [_page([{"id": 10}])],
                    "/v1/issues/10/occurrences/": [_page([{"id": 1}])],
                }
            ),
            resume_state=state,
        )
        assert result.raised is None
        assert result.paths == ["/v1/issues/", "/v1/issues/10/occurrences/"]
        assert result.params("limit") == [str(PAGE_SIZE)] * 2
        assert result.rows == [{"id": 1, "issue_id": 10}]


class TestRetryClassification:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_transient_status_is_retried_then_succeeds(self, status: int) -> None:
        # 429/5xx are transient — the client backs off and reissues the same request rather than
        # failing the whole sync.
        result = _driver().run(
            "targets",
            [ScriptedResponse(status=status, json={"error": "transient"}), _page([{"id": 1}])],
        )
        assert result.raised is None
        assert result.paths == ["/v1/targets/", "/v1/targets/"]
        assert result.params("limit") == [str(PAGE_SIZE)] * 2
        assert result.rows == [{"id": 1}]

    @parameterized.expand([(401,), (403,), (404,)])
    def test_client_error_fails_loud(self, status: int) -> None:
        # 4xx (other than 429) are permanent — raise rather than retry or silently sync 0 rows. A 401/
        # 403 is surfaced as a non-retryable credential error upstream via get_non_retryable_errors.
        result = _driver().run("targets", [ScriptedResponse(status=status, json={"error": "nope"})])
        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/v1/targets/"]
        assert result.params("limit") == [str(PAGE_SIZE)]


class TestUrlSafety:
    @parameterized.expand(
        [
            ("attacker_host", "https://evil.com/v1/targets/"),
            ("attacker_subdomain", "https://api.intruder.io.evil.com/v1/targets/"),
            ("userinfo_trick", "https://api.intruder.io@evil.com/v1/targets/"),
        ]
    )
    def test_off_host_next_url_is_refused(self, _name: str, evil_next: str) -> None:
        # A poisoned resume cursor or a malicious API-returned `next` pointing off the Intruder host
        # must never be followed with the bearer token — allowed_hosts=[] is the SSRF guard. The
        # first page is yielded, then following the off-host `next` raises before the request leaves
        # the process.
        result = _driver().run("targets", [_page([{"id": 1}], next_url=evil_next)])
        assert isinstance(result.raised, ValueError)
        assert result.rows == [{"id": 1}]
        assert result.paths == ["/v1/targets/"]
        assert result.params("limit") == [str(PAGE_SIZE)]

    def test_redirect_is_refused(self) -> None:
        # A 3xx could retarget the authenticated request off-origin; allow_redirects=False refuses it
        # rather than following it with the token attached.
        result = _driver().run("targets", [ScriptedResponse(status=302, headers={"Location": "https://evil.com"})])
        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/v1/targets/"]
        assert result.params("limit") == [str(PAGE_SIZE)]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("tok") is expected
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/v1/targets/"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"

    def test_redacts_token(self) -> None:
        # Dropping redact_values would leak the bearer token into logged URLs / captured samples.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("secret-token") is True
        assert network.session_options[0].get("redact_values") == ("secret-token",)
