"""CDC error taxonomy.

Classifies an extraction failure into a user-facing category with a friendly,
credential-safe message and a retryable flag. Engine-agnostic: the engine-specific
interpretation (which psycopg exception means "authentication failed", etc.) lives
behind ``CDCSourceAdapter.classify_error`` in each source's adapter, mirroring the
``is_slot_invalidation_error`` seam. This module owns the shared vocabulary, the
user-facing copy, and the orchestration-level fallbacks.
"""

from __future__ import annotations

import enum
import dataclasses
from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import CDCSourceAdapter

# Friendly messages land in the user-visible `latest_error`; cap them so the column stays tidy.
MAX_FRIENDLY_MESSAGE_LENGTH = 500


class CDCErrorCategory(enum.StrEnum):
    AUTH_FAILED = "auth_failed"
    SSL_REQUIRED = "ssl_required"
    CONNECTION_FAILED = "connection_failed"
    HOST_UNREACHABLE = "host_unreachable"
    SLOT_MISSING = "slot_missing"
    PUBLICATION_MISSING = "publication_missing"
    SLOT_IN_USE = "slot_in_use"
    WAL_DECODE_ERROR = "wal_decode_error"
    TRANSACTION_TOO_LARGE = "transaction_too_large"
    SCHEMA_MERGE_INCOMPATIBLE = "schema_merge_incompatible"
    UNKNOWN = "unknown"


@dataclasses.dataclass(frozen=True)
class CDCErrorInfo:
    category: CDCErrorCategory
    friendly_message: str
    retryable: bool


class CDCTransactionTooLargeError(Exception):
    """A single source transaction exceeded the in-memory decode budget.

    Non-retryable: re-decoding replays the same oversized transaction. The decoder guard
    that raises this lives in the source-specific decoder; the type is defined here so the
    shared classifier owns the mapping to ``TRANSACTION_TOO_LARGE``.
    """


class CDCSchemaMergeError(Exception):
    """A column's values can't be reconciled into one Parquet type across micro-batches.

    Non-retryable: the conflicting batches replay identically, so re-running re-fails. The
    activity raises this when an Arrow schema merge rejects the data (e.g. a source column
    that genuinely changed type mid-stream — int in one batch, text in another). Defined
    here so the shared classifier owns the mapping to ``SCHEMA_MERGE_INCOMPATIBLE``.
    """


# (friendly_message, retryable) per category. Messages are STATIC templates — they never
# interpolate host/user/password or raw exception text, so stored copy can't leak credentials.
_CATEGORY_DEFAULTS: dict[CDCErrorCategory, tuple[str, bool]] = {
    CDCErrorCategory.AUTH_FAILED: (
        "Could not authenticate with the source database. Check the configured username and "
        "password, then re-enable change data capture.",
        False,
    ),
    CDCErrorCategory.SSL_REQUIRED: (
        "Could not establish a required encrypted (SSL) connection to the source database. Check "
        "that the database accepts SSL connections, then re-enable change data capture.",
        False,
    ),
    CDCErrorCategory.CONNECTION_FAILED: (
        "Could not connect to the source database. PostHog will keep retrying — if this persists, "
        "check that the database is reachable and accepting connections.",
        True,
    ),
    CDCErrorCategory.HOST_UNREACHABLE: (
        "PostHog has no network route to the source database host, so it can't be reached. Check "
        "that the host and port are correct and reachable from the public internet (PostHog's IP "
        "addresses allowed through, and the host not resolving to a private or unreachable "
        "address), then re-enable change data capture.",
        False,
    ),
    CDCErrorCategory.SLOT_MISSING: (
        "The replication slot no longer exists on the source database, so changes can no longer be "
        "read. Disable and re-enable change data capture to recreate it and re-sync.",
        False,
    ),
    CDCErrorCategory.PUBLICATION_MISSING: (
        "The publication used for change data capture no longer exists on the source database. "
        "Recreate it, or disable and re-enable change data capture, then re-sync.",
        False,
    ),
    CDCErrorCategory.SLOT_IN_USE: (
        "The replication slot is currently in use by another connection. PostHog will retry shortly.",
        True,
    ),
    CDCErrorCategory.WAL_DECODE_ERROR: (
        "PostHog could not decode the change stream from the source database. This usually points to "
        "an unsupported column type or replication setting. Contact support if it persists.",
        False,
    ),
    CDCErrorCategory.TRANSACTION_TOO_LARGE: (
        "A single database transaction contained more changes than change data capture can process at "
        "once. Reduce the size of bulk operations on the source, then re-sync.",
        False,
    ),
    CDCErrorCategory.SCHEMA_MERGE_INCOMPATIBLE: (
        "A source column changed type partway through the change stream (for example, numbers and text "
        "in the same column), so the changes can no longer be combined into one table. Disable and "
        "re-enable change data capture to re-sync from a fresh snapshot.",
        False,
    ),
    CDCErrorCategory.UNKNOWN: (
        "Change data capture hit an unexpected error. PostHog will retry automatically — if it "
        "persists, check the source's sync logs or contact support.",
        True,
    ),
}


def cdc_error_info(category: CDCErrorCategory) -> CDCErrorInfo:
    """Build the canonical ``CDCErrorInfo`` for a category from the shared copy table."""
    message, retryable = _CATEGORY_DEFAULTS[category]
    return CDCErrorInfo(category=category, friendly_message=message, retryable=retryable)


def _iter_cause_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield ``exc`` and every exception in its ``__cause__``/``__context__`` chain once."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def classify_cdc_error(exc: BaseException, adapter: CDCSourceAdapter | None) -> CDCErrorInfo:
    """Classify a CDC extraction failure into a user-facing ``CDCErrorInfo``.

    Walks the exception's cause chain. Orchestration-level errors that any engine can hit are
    matched here; engine-specific interpretation is delegated to ``adapter.classify_error``.
    Falls back to a retryable ``unknown`` so a misclassification never strands a recoverable run.
    """
    for err in _iter_cause_chain(exc):
        if isinstance(err, CDCTransactionTooLargeError):
            return cdc_error_info(CDCErrorCategory.TRANSACTION_TOO_LARGE)
        if isinstance(err, CDCSchemaMergeError):
            return cdc_error_info(CDCErrorCategory.SCHEMA_MERGE_INCOMPATIBLE)
        if adapter is not None:
            info = adapter.classify_error(err)
            if info is not None:
                return info
    return cdc_error_info(CDCErrorCategory.UNKNOWN)
