"""Postgres-specific CDC error classification.

Maps psycopg exceptions (and their message markers) raised on the WAL data path or the
management connection to the engine-agnostic ``CDCErrorCategory`` taxonomy. Mirrors the
``is_slot_invalidation_error`` seam: the shared layer owns the taxonomy and user-facing copy,
this module owns the Postgres interpretation.
"""

from __future__ import annotations

import struct

import psycopg
import psycopg.errors

from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCErrorCategory

# Server requires (or rejects) an encrypted connection. Kept specific so a transient
# "SSL connection has been closed unexpectedly" stays a retryable connection failure.
_SSL_REQUIRED_MARKERS = (
    "server does not support ssl",
    "ssl connection is required",
    "ssl was required",
)

_AUTH_MARKERS = (
    "authentication failed",
    "no password supplied",
)

# Routing failures (ENETUNREACH / EHOSTUNREACH): there is no route to the host's network at all,
# so the connection never leaves PostHog. Unlike a refused or reset connection — where the host is
# reachable and the failure is plausibly transient — these are deterministic for the configured
# host (e.g. it resolves to a private or otherwise non-routable address, such as an IPv6 address
# PostHog can't route to), so retrying re-hits the same wall. Mirrors the non-retryable treatment
# on the batch path (PostgresSource.get_non_retryable_errors).
_HOST_UNREACHABLE_MARKERS = (
    "network is unreachable",
    "no route to host",
)


def classify_postgres_cdc_error(exc: BaseException) -> CDCErrorCategory | None:
    """Classify a single Postgres exception into a ``CDCErrorCategory``.

    Returns None when the exception isn't a recognizable Postgres CDC failure, so the
    shared classifier can keep walking the cause chain and fall back to ``unknown``.
    """
    # struct.error => the pgoutput binary stream couldn't be unpacked.
    if isinstance(exc, struct.error):
        return CDCErrorCategory.WAL_DECODE_ERROR

    # Guard all string-based checks: only psycopg exceptions carry these message patterns.
    # A non-psycopg exception whose message happens to contain e.g. "does not exist" would
    # otherwise be misclassified as non-retryable SLOT_MISSING, permanently stopping retries.
    if not isinstance(exc, psycopg.Error):
        return None

    message = str(exc).lower()

    # Slot held by another connection (e.g. a previous run still draining): "replication
    # slot ... is active for PID ...". Retryable — it frees up on its own.
    if "is active for pid" in message:
        return CDCErrorCategory.SLOT_IN_USE

    if "does not exist" in message:
        if "replication slot" in message:
            return CDCErrorCategory.SLOT_MISSING
        if "publication" in message:
            return CDCErrorCategory.PUBLICATION_MISSING

    # Authentication (SQLSTATE class 28) surfaces either as a mapped subclass (server-side)
    # or a bare OperationalError with a libpq message (connection-time). Check before the
    # generic OperationalError fallback, which these subclass.
    if isinstance(exc, psycopg.errors.InvalidPassword | psycopg.errors.InvalidAuthorizationSpecification):
        return CDCErrorCategory.AUTH_FAILED
    if any(marker in message for marker in _AUTH_MARKERS):
        return CDCErrorCategory.AUTH_FAILED

    if isinstance(exc, psycopg.OperationalError):
        if any(marker in message for marker in _SSL_REQUIRED_MARKERS):
            return CDCErrorCategory.SSL_REQUIRED
        if any(marker in message for marker in _HOST_UNREACHABLE_MARKERS):
            return CDCErrorCategory.HOST_UNREACHABLE
        return CDCErrorCategory.CONNECTION_FAILED

    return None
