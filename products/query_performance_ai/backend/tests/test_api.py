from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings as django_settings
from django.test import override_settings
from django.utils import timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from posthog.errors import InternalCHQueryError
from posthog.models.oauth import OAuthAccessToken, OAuthApplication

from products.query_performance_ai.backend import api as proxy_module
from products.query_performance_ai.backend.api import MAX_SQL_LENGTH, _reset_sync_client_cache

TEST_HOST = "clickhouse-test.internal"


def _generate_rsa_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


@override_settings(
    CLICKHOUSE_TEST_CLUSTER_HOST=TEST_HOST,
    DEBUG=True,
    OAUTH2_PROVIDER={**django_settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": _generate_rsa_key()},
)
class TestQueryPerformanceProxyViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        _reset_sync_client_cache()  # the proxy caches a SyncClient at module scope
        self.oauth_app = OAuthApplication.objects.create(
            name="Test query-perf App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )
        self.client.logout()

    def _make_token(self, scopes: list[str], *, scoped_teams: list[int] | None = None) -> str:
        # Unscoped by default; matches what production mints for this endpoint.
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_app,
            token=f"pha_test_{uuid4().hex}",
            expires=timezone.now() + timedelta(hours=1),
            scope=" ".join(scopes),
            scoped_teams=scoped_teams,
        )
        return token.token

    def _post(self, path: str, *, token: str, body: dict) -> Any:
        return self.client.post(
            path,
            body,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    # --- auth --------------------------------------------------------------

    def test_requires_token(self):
        resp = self.client.post(
            "/api/query_performance_proxy/execute-test/",
            {"sql": "SELECT 1"},
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_rejects_token_without_test_scope(self):
        token = self._make_token(["query:read"])
        resp = self._post(
            "/api/query_performance_proxy/execute-test/",
            token=token,
            body={"sql": "SELECT 1"},
        )
        assert resp.status_code == 403

    # --- config handling ---------------------------------------------------

    def test_returns_503_when_host_unset(self):
        token = self._make_token(["clickhouse_test_cluster_perf:read"])
        with (
            override_settings(CLICKHOUSE_TEST_CLUSTER_HOST=""),
            patch("products.query_performance_ai.backend.api.sync_execute") as mocked,
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )
        assert resp.status_code == 503
        assert mocked.call_count == 0

    def test_returns_503_when_debug_unset(self):
        # DEBUG is the hard gate; cluster host alone does not enable the proxy.
        token = self._make_token(["clickhouse_test_cluster_perf:read"])
        with (
            override_settings(DEBUG=False),
            patch("products.query_performance_ai.backend.api.sync_execute") as mocked,
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )
        assert resp.status_code == 503
        assert "DEBUG" in resp.json()["error"]
        assert mocked.call_count == 0

    def test_cloud_deployment_set_short_circuits_before_clickhouse(self):
        # Any non-empty CLOUD_DEPLOYMENT must refuse — DEBUG=True in cloud is
        # a misconfiguration that should never expose the test cluster. Direct
        # viewset unit test (avoids the full middleware stack which activates
        # cloud-only paths that hang the test runner).
        from rest_framework.test import APIRequestFactory

        from products.query_performance_ai.backend.api import QueryPerformanceProxyViewSet

        factory = APIRequestFactory()
        for cloud in ("US", "EU", "DEV", "anything-non-empty"):
            with (
                override_settings(CLOUD_DEPLOYMENT=cloud),
                patch("products.query_performance_ai.backend.api.sync_execute") as mocked,
            ):
                # Bypass auth/permission for unit-level gate testing.
                view_instance = QueryPerformanceProxyViewSet()
                view_instance.action = "execute_test"
                request = factory.post("/api/query_performance_proxy/execute-test/", {"sql": "SELECT 1"}, format="json")
                resp = view_instance.execute_test(request)
            assert resp.status_code == 503, f"CLOUD_DEPLOYMENT={cloud!r} should be refused"
            assert mocked.call_count == 0

    def test_server_mints_query_id_and_passes_to_sync_execute(self):
        # The caller must not control query_id — that would let a malicious
        # SQL request collide / overwrite a previous run's `system.query_log` row.
        token = self._make_token(["clickhouse_test_cluster_perf:read"])

        with patch("products.query_performance_ai.backend.api.sync_execute") as mocked:
            mocked.return_value = [(1,)]
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )

        assert resp.status_code == 200, resp.content
        passed_query_id = mocked.call_args.kwargs["query_id"]
        # UUIDv7: 36-char canonical form, version nibble = 7
        assert isinstance(passed_query_id, str) and len(passed_query_id) == 36
        assert passed_query_id[14] == "7"
        assert resp.json()["query_id"] == passed_query_id

    def test_passes_caps_and_readonly_on_every_request(self):
        token = self._make_token(["clickhouse_test_cluster_perf:read"])

        with patch("products.query_performance_ai.backend.api.sync_execute") as mocked:
            mocked.return_value = [(1,)]
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )

        assert resp.status_code == 200, resp.content
        passed_settings = mocked.call_args.kwargs["settings"]
        assert passed_settings["readonly"] == 2
        assert passed_settings["max_execution_time"] == 5 * 60
        assert passed_settings["max_result_rows"] == 10_000
        assert passed_settings["max_result_bytes"] == 10 * 1024 * 1024
        assert passed_settings["result_overflow_mode"] == "throw"
        client = mocked.call_args.kwargs["sync_client"]
        assert client.connection.hosts[0][0] == TEST_HOST

    def test_write_is_forwarded_and_clickhouse_rejection_becomes_502(self):
        # Writes are filtered by the CH user's `readonly = 2`, not Django.
        token = self._make_token(["clickhouse_test_cluster_perf:read"])

        for write_sql in ("INSERT INTO t VALUES (1)", "ALTER TABLE t DELETE WHERE 1 = 1", "DROP TABLE t"):
            with patch(
                "products.query_performance_ai.backend.api.sync_execute",
                side_effect=InternalCHQueryError("Cannot execute query in readonly mode", code=164),
            ) as mocked:
                resp = self._post(
                    "/api/query_performance_proxy/execute-test/",
                    token=token,
                    body={"sql": write_sql},
                )

            assert mocked.call_count == 1, f"{write_sql!r} was not forwarded"
            payload = resp.json()
            assert resp.status_code == 502, f"{write_sql!r} did not 502 ({resp.status_code})"
            assert payload["code"] == 164
            assert "detail" not in payload
            assert "readonly" not in str(payload)

    def test_clickhouse_query_error_does_not_leak_exception_text(self):
        token = self._make_token(["clickhouse_test_cluster_perf:read"])
        msg = (
            "Code: 62. DB::Exception: Syntax error near 'FROOM'.\n"
            "Stack trace (when copying this message, always include the lines below):\n"
            "0. DB::Exception::Exception() @ 0xdeadbeef in /usr/bin/clickhouse\n"
            "1. DB::parseQuery() @ 0xcafef00d in /usr/bin/clickhouse\n"
        )
        with patch(
            "products.query_performance_ai.backend.api.sync_execute",
            side_effect=InternalCHQueryError(msg, code=62),
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT * FROOM events"},
            )

        payload = resp.json()
        assert resp.status_code == 502
        assert payload == {"error": "clickhouse query failed", "code": 62}
        assert "FROOM" not in str(payload)
        assert "Stack trace" not in str(payload)
        assert "0xdeadbeef" not in str(payload)

    def test_clickhouse_connection_failure_does_not_leak_exception_detail(self):
        # Connection errors can embed host / port / cert internals.
        token = self._make_token(["clickhouse_test_cluster_perf:read"])
        with patch(
            "products.query_performance_ai.backend.api.sync_execute",
            side_effect=ConnectionRefusedError("refused: 10.0.0.42:9000 (internal-secret-host)"),
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )
        payload = resp.json()
        assert resp.status_code == 502
        assert payload == {"error": "clickhouse unreachable"}
        assert "10.0.0.42" not in str(payload)
        assert "internal-secret-host" not in str(payload)

    # --- happy path --------------------------------------------------------

    def test_test_endpoint_returns_rows_and_ch_reported_metrics(self):
        token = self._make_token(["clickhouse_test_cluster_perf:read"])

        # Plant metrics on a fake `last_query` so we can assert the proxy reads them.
        profile = MagicMock(rows=987654, bytes=12345678)
        fake_client = MagicMock()
        fake_client.last_query.profile_info = profile
        fake_client.last_query.elapsed = 0.1234  # seconds

        with (
            patch("products.query_performance_ai.backend.api._get_sync_client", return_value=fake_client),
            patch("products.query_performance_ai.backend.api.sync_execute", return_value=[(1, "a"), (2, None)]),
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT id, name FROM events"},
            )

        assert resp.status_code == 200, resp.content
        payload = resp.json()
        assert payload["result"] == [[1, "a"], [2, None]]
        assert payload["rows_read"] == 987654
        assert payload["bytes_read"] == 12345678
        assert payload["rows_returned"] == 2
        assert payload["elapsed_ms"] == 123.4  # CH's timer, not Python wall-clock
        assert isinstance(payload["query_id"], str) and len(payload["query_id"]) == 36

    # --- SQL validation ----------------------------------------------------

    def test_rejects_sql_over_length_cap(self):
        # Python-memory bound; over-cap rejected at the serializer.
        token = self._make_token(["clickhouse_test_cluster_perf:read"])
        with patch("products.query_performance_ai.backend.api.sync_execute") as mocked:
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1 -- " + ("x" * MAX_SQL_LENGTH)},
            )
        assert resp.status_code == 400
        assert mocked.call_count == 0

    def test_forwards_sql_verbatim_without_django_layer_validation(self):
        # CH grants are the SQL-safety enforcer; we forward verbatim.
        token = self._make_token(["clickhouse_test_cluster_perf:read"])
        sql = "SELECT * FROM url('http://attacker.example/', CSV, 'x String')"
        with patch("products.query_performance_ai.backend.api.sync_execute") as mocked:
            mocked.return_value = []
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": sql},
            )
        assert resp.status_code == 200, resp.content
        assert mocked.call_args.args[0] == sql

    # --- overflow behaviour ------------------------------------------------

    def test_result_overflow_throws_rather_than_truncates(self):
        # Truncation would let the compare oracle crown a wrong candidate.
        token = self._make_token(["clickhouse_test_cluster_perf:read"])
        # CH error 396: TOO_MANY_ROWS_OR_BYTES
        with patch(
            "products.query_performance_ai.backend.api.sync_execute",
            side_effect=InternalCHQueryError("result set is too large", code=396),
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT number FROM system.numbers LIMIT 1000000"},
            )
        assert resp.status_code == 502
        assert resp.json() == {"error": "clickhouse query failed", "code": 396}

    # --- client lifecycle --------------------------------------------------

    def test_connection_failure_invalidates_client_cache(self):
        # Without the reset, a zombie client would 502 every request to process restart.
        token = self._make_token(["clickhouse_test_cluster_perf:read"])
        fake_client = MagicMock()
        proxy_module._SYNC_CLIENT = fake_client
        proxy_module._SYNC_CLIENT_KEY = (TEST_HOST, "", "", "", False, None, True)

        with patch(
            "products.query_performance_ai.backend.api.sync_execute",
            side_effect=ConnectionError("broken pipe"),
        ):
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=token,
                body={"sql": "SELECT 1"},
            )
        assert resp.status_code == 502
        assert proxy_module._SYNC_CLIENT is None

    # --- token scoping -----------------------------------------------------

    def test_rejects_team_scoped_token(self):
        scoped_token = self._make_token(["clickhouse_test_cluster_perf:read"], scoped_teams=[self.team.id])

        with patch("products.query_performance_ai.backend.api.sync_execute") as mocked:
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=scoped_token,
                body={"sql": "SELECT 1"},
            )

        assert resp.status_code == 403, resp.content
        assert "team-scoped" in resp.json()["error"]
        assert mocked.call_count == 0

    def test_accepts_userless_internal_token(self):
        # `create_internal_oauth_access_token` mints with `user=None`; the auth
        # backend resolves it to a synthetic InternalAPIUser so DRF's
        # IsAuthenticated holds without pinning a real DB user.
        userless_token = OAuthAccessToken.objects.create(
            user=None,
            application=self.oauth_app,
            token=f"pha_test_{uuid4().hex}",
            expires=timezone.now() + timedelta(hours=1),
            scope="clickhouse_test_cluster_perf:read",
            scoped_teams=None,
        ).token

        with patch("products.query_performance_ai.backend.api.sync_execute") as mocked:
            mocked.return_value = [(1,)]
            resp = self._post(
                "/api/query_performance_proxy/execute-test/",
                token=userless_token,
                body={"sql": "SELECT 1"},
            )

        assert resp.status_code == 200, resp.content
        assert mocked.call_count == 1
