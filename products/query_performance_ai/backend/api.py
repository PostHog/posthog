"""OAuth-gated ClickHouse passthrough for the query-performance autoresearch sandbox.

SQL safety comes entirely from the CH user routed through
``CLICKHOUSE_TEST_CLUSTER_*`` (``autoresearch`` in dev, see
``docker/clickhouse/users-dev.xml``): ``readonly=2`` pinned in the profile,
no grants on ``url``/``s3``/``file``/``executable``/etc., SELECT grants
limited to a small whitelist. We don't parse or filter SQL here.
"""

from __future__ import annotations

import logging
import threading

from django.conf import settings

from clickhouse_driver import (
    Client as SyncClient,
    errors as clickhouse_driver_errors,
)
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.errors import InternalCHQueryError
from posthog.models.utils import uuid7
from posthog.permissions import APIScopePermission

logger = logging.getLogger(__name__)


# Caps are defense-in-depth around the CH user's profile constraints. The
# row/byte caps + result_overflow_mode=throw make a runaway `SELECT *` fail
# loud instead of silently truncating and poisoning the compare oracle.
MAX_SQL_LENGTH = 64 * 1024
MAX_EXECUTION_TIME_SECONDS = 5 * 60
MAX_RESULT_ROWS = 10_000
MAX_RESULT_BYTES = 10 * 1024 * 1024


class ExecuteTestClusterRequestSerializer(serializers.Serializer):
    sql = serializers.CharField(max_length=MAX_SQL_LENGTH, help_text="ClickHouse SQL to run against the test cluster.")


class ExecuteTestClusterResponseSerializer(serializers.Serializer):
    result = serializers.ListField(
        child=serializers.ListField(),
        help_text="Rows returned, each as a positional list of values from the ClickHouse driver.",
    )
    elapsed_ms = serializers.FloatField(allow_null=True, help_text="Server-side elapsed time in milliseconds.")
    rows_read = serializers.IntegerField(allow_null=True, help_text="Rows read from storage (scan-side).")
    bytes_read = serializers.IntegerField(allow_null=True, help_text="Bytes read from storage (scan-side).")
    rows_returned = serializers.IntegerField(help_text="Rows in the `result` payload.")
    query_id = serializers.CharField(
        help_text="Server-minted query id; the caller can look this up in `system.query_log`.",
    )


_QUERY_SETTINGS: dict[str, object] = {
    "max_execution_time": MAX_EXECUTION_TIME_SECONDS,
    "max_result_rows": MAX_RESULT_ROWS,
    "max_result_bytes": MAX_RESULT_BYTES,
    "result_overflow_mode": "throw",
    "readonly": 2,
}


# `clickhouse-driver.Client` owns mutable per-connection state (`last_query`);
# `_QUERY_LOCK` serializes calls so concurrent reads can't corrupt it. One
# query at a time is what the single-tenant test cluster wants anyway.
_LOCK_WAIT_TIMEOUT_SECONDS = MAX_EXECUTION_TIME_SECONDS + 10
_SYNC_CLIENT: SyncClient | None = None
_SYNC_CLIENT_KEY: tuple | None = None
_QUERY_LOCK = threading.Lock()


class _CachedSyncClient(SyncClient):
    """`Client.__exit__` calls ``disconnect()`` → ``reset_last_query()``,
    wiping the metrics we want to return. ``sync_execute`` always wraps its
    argument in ``with``, so override ``__exit__`` to a no-op; the cache's
    lifecycle is managed by ``_reset_sync_client_cache``."""

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None


def _get_sync_client() -> SyncClient:
    global _SYNC_CLIENT, _SYNC_CLIENT_KEY
    key = (
        settings.CLICKHOUSE_TEST_CLUSTER_HOST,
        settings.CLICKHOUSE_TEST_CLUSTER_DATABASE,
        settings.CLICKHOUSE_TEST_CLUSTER_USER,
        settings.CLICKHOUSE_TEST_CLUSTER_PASSWORD,
        settings.CLICKHOUSE_TEST_CLUSTER_SECURE,
        settings.CLICKHOUSE_TEST_CLUSTER_CA,
        settings.CLICKHOUSE_TEST_CLUSTER_VERIFY,
    )
    if _SYNC_CLIENT is None or _SYNC_CLIENT_KEY != key:
        _SYNC_CLIENT = _CachedSyncClient(
            host=key[0],
            database=key[1],
            user=key[2],
            password=key[3],
            secure=key[4],
            ca_certs=key[5],
            verify=key[6],
        )
        _SYNC_CLIENT_KEY = key
    return _SYNC_CLIENT


def _reset_sync_client_cache() -> None:
    """Drop the cached SyncClient. Callers must hold `_QUERY_LOCK` unless
    they're single-threaded (test setUp)."""
    global _SYNC_CLIENT, _SYNC_CLIENT_KEY
    if _SYNC_CLIENT is not None:
        try:
            _SYNC_CLIENT.disconnect()
        except Exception:
            logger.debug("sync client disconnect raised during reset", exc_info=True)
    _SYNC_CLIENT = None
    _SYNC_CLIENT_KEY = None


class QueryPerformanceProxyViewSet(viewsets.ViewSet):
    authentication_classes = [OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "INTERNAL"
    # `as_view()` rejects unknown initkwargs, and DRF's `@action(required_scopes=...)`
    # is plumbed through as one — so any class using the kwarg must declare it.
    # Other PostHog viewsets get this from `TeamAndOrgViewSetMixin`; this one doesn't.
    required_scopes: list[str] | None = None

    # No project / org URL nesting. See `APIScopePermission.check_team_and_org_permissions`.
    dangerously_skip_scoped_team_enforcement = True

    @extend_schema(
        request=ExecuteTestClusterRequestSerializer,
        responses={200: ExecuteTestClusterResponseSerializer},
        summary="Run a read-only query against the autoresearch test cluster",
        description=(
            "DEBUG-only proxy that forwards SQL to the ClickHouse `autoresearch` user. "
            "SQL safety comes entirely from the CH user's grants + readonly=2 profile; "
            "the endpoint does not parse or filter SQL."
        ),
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="execute-test",
        required_scopes=["clickhouse_test_cluster_perf:read"],
    )
    def execute_test(self, request: Request) -> Response:
        if not settings.DEBUG or settings.CLOUD_DEPLOYMENT:
            return Response(
                {"error": "query_performance_proxy is only available in DEBUG mode outside cloud deployments"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not settings.CLICKHOUSE_TEST_CLUSTER_HOST:
            return Response(
                {"error": "CLICKHOUSE_TEST_CLUSTER_HOST is not configured; test endpoint disabled"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        access_token = getattr(request.successful_authenticator, "access_token", None)
        if access_token is not None and access_token.scoped_teams:
            return Response(
                {"error": "team-scoped OAuth tokens are not allowed on this endpoint"},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = ExecuteTestClusterRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _run_autoresearch_query(serializer.validated_data["sql"])


def _run_autoresearch_query(sql: str) -> Response:
    acquired = _QUERY_LOCK.acquire(timeout=_LOCK_WAIT_TIMEOUT_SECONDS)
    if not acquired:
        return Response(
            {"error": "query_performance_proxy is busy; retry shortly"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    # Server-minted so the caller can't poison `system.query_log` lookups by
    # supplying a colliding id; returned in the response so the agent can use it.
    query_id = str(uuid7())
    try:
        client = _get_sync_client()
        try:
            with tags_context(
                product=Product.INTERNAL,
                feature=Feature.AUTORESEARCH,
                kind="request",
                query_type="autoresearch_proxy",
            ):
                rows = sync_execute(
                    sql,
                    settings=_QUERY_SETTINGS,
                    sync_client=client,
                    flush=False,
                    query_id=query_id,
                )
        except InternalCHQueryError as e:
            # Echoing exception text trips CodeQL information-exposure.
            logger.exception("query_performance_proxy: clickhouse query failed")
            return Response(
                {
                    "error": "clickhouse query failed",
                    "code": getattr(e, "code", None),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except (
            ConnectionError,
            OSError,
            EOFError,
            clickhouse_driver_errors.NetworkError,
            clickhouse_driver_errors.SocketTimeoutError,
            clickhouse_driver_errors.UnexpectedPacketFromServerError,
            clickhouse_driver_errors.UnknownPacketFromServerError,
            clickhouse_driver_errors.PartiallyConsumedQueryError,
        ):
            # Network-level failure leaves the cached client unusable. Other
            # exceptions propagate as 500 — we don't drop a healthy socket on
            # a code bug.
            logger.exception("query_performance_proxy: failed to reach ClickHouse")
            _reset_sync_client_cache()
            return Response(
                {"error": "clickhouse unreachable"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Read inside the lock so a concurrent reset can't null the client.
        last_query = getattr(client, "last_query", None)
        profile_info = getattr(last_query, "profile_info", None)
        elapsed_seconds = getattr(last_query, "elapsed", None)
    finally:
        _QUERY_LOCK.release()

    return Response(
        {
            "result": rows,
            "elapsed_ms": round(elapsed_seconds * 1000.0, 3) if isinstance(elapsed_seconds, int | float) else None,
            "rows_read": getattr(profile_info, "rows", None),
            "bytes_read": getattr(profile_info, "bytes", None),
            "rows_returned": len(rows),
            "query_id": query_id,
        },
        status=status.HTTP_200_OK,
    )
