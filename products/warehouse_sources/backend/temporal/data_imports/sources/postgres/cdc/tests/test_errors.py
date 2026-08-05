import struct

import psycopg.errors
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCErrorCategory
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.errors import (
    classify_postgres_cdc_error,
)


class TestClassifyPostgresCDCError:
    @parameterized.expand(
        [
            (
                "invalid_password_class",
                psycopg.errors.InvalidPassword('password authentication failed for user "posthog"'),
                CDCErrorCategory.AUTH_FAILED,
            ),
            (
                "invalid_authorization_class",
                psycopg.errors.InvalidAuthorizationSpecification("no pg_hba.conf entry for host"),
                CDCErrorCategory.AUTH_FAILED,
            ),
            (
                "auth_message_on_operational_error",
                psycopg.OperationalError('connection failed: password authentication failed for user "x"'),
                CDCErrorCategory.AUTH_FAILED,
            ),
            (
                "ssl_required",
                psycopg.OperationalError("server does not support SSL, but SSL was required"),
                CDCErrorCategory.SSL_REQUIRED,
            ),
            (
                "ssl_close_is_connection_not_ssl_required",
                psycopg.OperationalError("SSL connection has been closed unexpectedly"),
                CDCErrorCategory.CONNECTION_FAILED,
            ),
            (
                "connection_refused",
                psycopg.OperationalError("connection to server at localhost, port 5432 failed: Connection refused"),
                CDCErrorCategory.CONNECTION_FAILED,
            ),
            (
                "network_unreachable_is_non_retryable_host",
                psycopg.OperationalError(
                    'connection to server at "2001:db8::1", port 5432 failed: Network is unreachable'
                ),
                CDCErrorCategory.HOST_UNREACHABLE,
            ),
            (
                "no_route_to_host_is_non_retryable_host",
                psycopg.OperationalError("connection to server at example.invalid, port 5432 failed: No route to host"),
                CDCErrorCategory.HOST_UNREACHABLE,
            ),
            (
                "slot_missing",
                psycopg.errors.UndefinedObject('replication slot "posthog_slot" does not exist'),
                CDCErrorCategory.SLOT_MISSING,
            ),
            (
                "publication_missing",
                psycopg.errors.UndefinedObject('publication "posthog_pub" does not exist'),
                CDCErrorCategory.PUBLICATION_MISSING,
            ),
            (
                "slot_in_use",
                psycopg.errors.ObjectInUse('replication slot "posthog_slot" is active for PID 123'),
                CDCErrorCategory.SLOT_IN_USE,
            ),
            (
                "wal_decode_struct_error",
                struct.error("unpack requires a buffer of 4 bytes"),
                CDCErrorCategory.WAL_DECODE_ERROR,
            ),
            (
                "unrelated_runtime_error",
                RuntimeError("S3 write failed"),
                None,
            ),
            (
                "undefined_table_is_not_slot_or_publication",
                psycopg.errors.UndefinedTable('relation "public.orders" does not exist'),
                None,
            ),
        ]
    )
    def test_classification(self, _name, exc, expected):
        assert classify_postgres_cdc_error(exc) is expected

    def test_slot_in_use_takes_precedence_over_does_not_exist_wording(self):
        # An "is active for PID" message must classify as retryable slot_in_use even if it
        # mentions the slot — never as the non-retryable slot_missing.
        exc = psycopg.errors.ObjectInUse('replication slot "posthog_slot" is active for PID 99')
        assert classify_postgres_cdc_error(exc) is CDCErrorCategory.SLOT_IN_USE
