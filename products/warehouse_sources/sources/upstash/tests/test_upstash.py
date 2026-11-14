from collections.abc import Callable

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.upstash._config import UpstashSourceConfig
from products.warehouse_sources.sources.upstash.settings import UPSTASH_API_BASE_URL, UPSTASH_ROOT_BASE_URL
from products.warehouse_sources.sources.upstash.source import UpstashSource
from products.warehouse_sources.sources.upstash.upstash import validate_credentials


def _driver() -> SourceDriver:
    return SourceDriver(UpstashSource(), UpstashSourceConfig(email="e", api_key="k"))


class TestListEndpoints:
    @parameterized.expand(
        [
            ("redis_databases", f"{UPSTASH_API_BASE_URL}/redis/databases", "database_id"),
            ("teams", f"{UPSTASH_API_BASE_URL}/teams", "team_id"),
            ("vector_indexes", f"{UPSTASH_API_BASE_URL}/vector/index", "id"),
            ("search_indexes", f"{UPSTASH_API_BASE_URL}/search", "id"),
            # Audit logs are served from the unversioned host, not api.upstash.com/v2.
            ("audit_logs", f"{UPSTASH_ROOT_BASE_URL}/auditlogs", "log_id"),
        ]
    )
    def test_yields_dicts_from_raw_array_at_expected_url(self, endpoint: str, expected_url: str, pk: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[{pk: "a"}, {pk: "b"}])])

        assert [r[pk] for r in result.rows] == ["a", "b"]
        assert result.urls == [expected_url]

    def test_non_list_response_raises(self) -> None:
        # A malformed body (object instead of array) must fail the sync loudly rather than silently
        # replace the warehouse table with zero rows.
        result = _driver().run("teams", [ScriptedResponse(json={"unexpected": "shape"})])

        assert isinstance(result.raised, ValueError)

    @parameterized.expand([("vector_indexes",), ("search_indexes",)])
    def test_index_tokens_are_stripped_from_rows(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=[{"id": "i1", "name": "idx", "token": "secret", "read_only_token": "ro"}])],
        )

        assert result.rows == [{"id": "i1", "name": "idx"}]


def _fan_out_responder(
    parent_path: str, parent_rows: list[dict], child_body_by_path: dict[str, object]
) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == f"/v2{parent_path}":
            return ScriptedResponse(json=parent_rows)
        if request.path in child_body_by_path:
            return ScriptedResponse(json=child_body_by_path[request.path])
        return ScriptedResponse(status=404, json={"error": "not found"})

    return respond


class TestStatsFanOut:
    @parameterized.expand(
        [
            (
                "redis_stats",
                "/redis/databases",
                [{"database_id": "db1"}, {"database_id": "db2"}],
                {"/v2/redis/stats/db1": {"daily_net_commands": 1}, "/v2/redis/stats/db2": {"daily_net_commands": 2}},
                [{"daily_net_commands": 1, "database_id": "db1"}, {"daily_net_commands": 2, "database_id": "db2"}],
            ),
            (
                # Member lists are arrays: every member of every team becomes its own row.
                "team_members",
                "/teams",
                [{"team_id": "t1"}, {"team_id": "t2"}],
                {
                    "/v2/teams/t1": [
                        {"team_id": "t1", "member_email": "a@example.com"},
                        {"team_id": "t1", "member_email": "b@example.com"},
                    ],
                    "/v2/teams/t2": [{"team_id": "t2", "member_email": "a@example.com"}],
                },
                [
                    {"team_id": "t1", "member_email": "a@example.com"},
                    {"team_id": "t1", "member_email": "b@example.com"},
                    {"team_id": "t2", "member_email": "a@example.com"},
                ],
            ),
            (
                "vector_index_stats",
                "/vector/index",
                [{"id": "v1", "token": "secret"}, {"id": "v2", "token": "secret"}],
                {
                    "/v2/vector/index/v1/stats": {"monthly_cost": 0.5},
                    "/v2/vector/index/v2/stats": {"monthly_cost": 1.5},
                },
                [{"monthly_cost": 0.5, "index_id": "v1"}, {"monthly_cost": 1.5, "index_id": "v2"}],
            ),
            (
                "qstash_stats",
                "/qstash/users",
                [{"id": "q1", "token": "secret"}, {"id": "q2", "token": "secret"}],
                {"/v2/qstash/stats/q1": {"dlq_message_count": 3}, "/v2/qstash/stats/q2": {"dlq_message_count": 0}},
                [{"dlq_message_count": 3, "qstash_user_id": "q1"}, {"dlq_message_count": 0, "qstash_user_id": "q2"}],
            ),
        ]
    )
    def test_fans_out_over_every_parent_and_stamps_its_id(
        self,
        endpoint: str,
        parent_path: str,
        parent_rows: list[dict],
        child_body_by_path: dict[str, object],
        expected_rows: list[dict],
    ) -> None:
        result = _driver().run(endpoint, _fan_out_responder(parent_path, parent_rows, child_body_by_path))

        assert result.raised is None
        assert result.rows == expected_rows
        assert [request.path for request in result.requests] == [f"/v2{parent_path}", *child_body_by_path]

    def test_parent_deleted_before_its_stats_fetch_is_skipped(self) -> None:
        result = _driver().run(
            "qstash_stats",
            _fan_out_responder(
                "/qstash/users",
                [{"id": "gone"}, {"id": "q2"}],
                {"/v2/qstash/stats/q2": {"dlq_message_count": 0}},
            ),
        )

        assert result.raised is None
        assert result.rows == [{"dlq_message_count": 0, "qstash_user_id": "q2"}]

    def test_non_404_error_during_fan_out_propagates(self) -> None:
        # A persistent 5xx while fetching stats fails the sync (after the client's retries) rather
        # than being swallowed like a 404.
        def respond(request: RecordedRequest) -> ScriptedResponse:
            # The parent databases list succeeds; every stats fetch after it 500s.
            if request.path.endswith("/redis/databases"):
                return ScriptedResponse(json=[{"database_id": "db1"}])
            return ScriptedResponse(status=500, json={"error": "boom"})

        result = _driver().run("redis_stats", respond)

        assert result.raised is not None
        # The parent succeeded once; the child 500 was retried several times before failing.
        assert len(result.requests) > 2

    def test_database_row_missing_id_raises(self) -> None:
        # The stats sync fans out over every database id; a row missing its id must fail the sync
        # rather than be silently dropped, which would yield partial usage/billing data.
        result = _driver().run(
            "redis_stats",
            [
                ScriptedResponse(json=[{"database_id": "db1"}, {"not_the_id": "x"}]),
                ScriptedResponse(json={"total_monthly_billing": 1.5}),
            ],
        )

        assert isinstance(result.raised, ValueError)


class TestHttpSampleCapture:
    # Responses that carry secrets (vector index tokens) must be excluded from HTTP sample capture,
    # since the generic scrubber does not redact fields named `token`. Other endpoints keep capture on.
    # Fan-out children whose parent listing carries tokens are excluded too, even though the child rows
    # themselves hold no secret.
    @parameterized.expand(
        [
            ("vector_indexes", False),
            ("search_indexes", False),
            ("vector_index_stats", False),
            ("qstash_stats", False),
            ("teams", True),
            ("team_members", True),
            ("redis_stats", True),
        ]
    )
    def test_capture_flag_tracks_sensitive_endpoints(self, endpoint: str, expected_capture: bool) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.session_options[0]["capture"] is expected_capture


class TestRetryClassification:
    def test_persistent_5xx_raises_after_retries(self) -> None:
        result = _driver().run("teams", always(ScriptedResponse(status=500, json={"error": "boom"})))

        assert result.raised is not None
        # The client retries a 5xx several times before giving up (default 5 attempts).
        assert len(result.requests) > 1

    @parameterized.expand([(401,), (403,)])
    def test_auth_errors_raise_immediately(self, status: int) -> None:
        result = _driver().run("teams", always(ScriptedResponse(status=status, json={"error": "denied"})))

        assert isinstance(result.raised, requests.HTTPError)
        # A credential error is not retried.
        assert len(result.requests) == 1


class TestValidateCredentials:
    # Only a definitive 401/403 rejects the credentials. 429/5xx are transient (retried during sync)
    # and must not block source creation during an Upstash outage or rate-limit window.
    @parameterized.expand([(429, True), (500, True)])
    def test_status_mapping(self, status: int, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            ok, error = validate_credentials("e", "k")

        assert ok is expected_ok
        assert (error is None) is expected_ok
        assert network.requests_log[0].url == f"{UPSTASH_API_BASE_URL}/teams"
        assert network.requests_log[0].headers["authorization"].startswith("Basic ")

    # A 403 means the whole account can't use the management API, so it must not read as a bad key
    # and send the customer off to generate another one that fails the same way.
    @parameterized.expand(
        [
            (401, "invalid or has been revoked"),
            (403, "isn't authorized to use the management API"),
        ]
    )
    def test_a_bad_key_and_an_unauthorized_account_read_differently(self, status: int, expected: str) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            ok, error = validate_credentials("e", "k")

        assert ok is False
        assert expected in (error or "")

    def test_request_exception_does_not_block_creation(self) -> None:
        # An unreachable API is transient, not a credential rejection; a genuine auth failure still
        # surfaces at sync time.
        with scripted_network(always(requests.ConnectionError("boom"))):
            ok, error = validate_credentials("e", "k")

        assert ok is True
        assert error is None


class TestUpstashSource:
    @parameterized.expand(
        [
            ("redis_databases", ["database_id"]),
            ("redis_stats", ["database_id"]),
            ("teams", ["team_id"]),
            ("vector_indexes", ["id"]),
            ("audit_logs", ["log_id"]),
        ]
    )
    def test_source_response_primary_keys_and_sort(self, endpoint: str, expected_pk: list[str]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_pk
        # Full refresh, replaced wholesale each sync; asc is the pipeline default.
        assert result.response.sort_mode == "asc"
