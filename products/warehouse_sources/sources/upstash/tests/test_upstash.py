import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.upstash import (
    UpstashSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.settings import (
    UPSTASH_API_BASE_URL,
    UPSTASH_ROOT_BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.source import UpstashSource
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.upstash import validate_credentials


def _driver() -> SourceDriver:
    return SourceDriver(UpstashSource(), UpstashSourceConfig(email="e", api_key="k"))


class TestListEndpoints:
    @parameterized.expand(
        [
            ("redis_databases", f"{UPSTASH_API_BASE_URL}/redis/databases", "database_id"),
            ("teams", f"{UPSTASH_API_BASE_URL}/teams", "team_id"),
            ("vector_indexes", f"{UPSTASH_API_BASE_URL}/vector/index", "id"),
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


class TestStatsFanOut:
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
    @parameterized.expand([("vector_indexes", False), ("teams", True)])
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
