import psycopg.errors
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import (
    MAX_FRIENDLY_MESSAGE_LENGTH,
    CDCErrorCategory,
    CDCErrorInfo,
    CDCSchemaMergeError,
    CDCTransactionTooLargeError,
    cdc_error_info,
    classify_cdc_error,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import PostgresCDCAdapter


class _StubAdapter:
    """Minimal adapter that classifies only exceptions whose message contains a marker."""

    def __init__(self, marker: str, category: CDCErrorCategory) -> None:
        self._marker = marker
        self._category = category
        self.seen: list[BaseException] = []

    def classify_error(self, exc: BaseException) -> CDCErrorInfo | None:
        self.seen.append(exc)
        return cdc_error_info(self._category) if self._marker in str(exc) else None


class TestCDCErrorInfo:
    @parameterized.expand(
        [
            (CDCErrorCategory.AUTH_FAILED, False),
            (CDCErrorCategory.SSL_REQUIRED, False),
            (CDCErrorCategory.CONNECTION_FAILED, True),
            (CDCErrorCategory.HOST_UNREACHABLE, False),
            (CDCErrorCategory.SLOT_MISSING, False),
            (CDCErrorCategory.PUBLICATION_MISSING, False),
            (CDCErrorCategory.SLOT_IN_USE, True),
            (CDCErrorCategory.WAL_DECODE_ERROR, False),
            (CDCErrorCategory.TRANSACTION_TOO_LARGE, False),
            (CDCErrorCategory.SCHEMA_MERGE_INCOMPATIBLE, False),
            (CDCErrorCategory.UNKNOWN, True),
        ]
    )
    def test_retryable_flag(self, category, expected_retryable):
        info = cdc_error_info(category)
        assert info.category is category
        assert info.retryable is expected_retryable

    def test_every_category_has_a_capped_non_empty_message(self):
        for category in CDCErrorCategory:
            info = cdc_error_info(category)
            assert info.friendly_message
            assert len(info.friendly_message) <= MAX_FRIENDLY_MESSAGE_LENGTH


class TestClassifyCDCError:
    def test_delegates_to_adapter(self):
        adapter = _StubAdapter("boom", CDCErrorCategory.AUTH_FAILED)
        info = classify_cdc_error(RuntimeError("boom"), adapter)  # type: ignore[arg-type]
        assert info.category is CDCErrorCategory.AUTH_FAILED
        assert info.retryable is False

    def test_unknown_when_adapter_returns_none(self):
        adapter = _StubAdapter("never", CDCErrorCategory.AUTH_FAILED)
        info = classify_cdc_error(RuntimeError("something else"), adapter)  # type: ignore[arg-type]
        assert info.category is CDCErrorCategory.UNKNOWN
        assert info.retryable is True

    def test_unknown_when_adapter_missing(self):
        info = classify_cdc_error(RuntimeError("anything"), None)
        assert info.category is CDCErrorCategory.UNKNOWN

    def test_walks_cause_chain(self):
        # The classifiable error is the cause; the outer wrapper is opaque.
        cause = psycopg.errors.InvalidPassword("password authentication failed")
        wrapper = RuntimeError("extraction failed")
        wrapper.__cause__ = cause
        info = classify_cdc_error(wrapper, PostgresCDCAdapter())
        assert info.category is CDCErrorCategory.AUTH_FAILED

    def test_transaction_too_large_is_classified_without_adapter(self):
        info = classify_cdc_error(CDCTransactionTooLargeError("500001 events"), None)
        assert info.category is CDCErrorCategory.TRANSACTION_TOO_LARGE
        assert info.retryable is False

    def test_schema_merge_error_is_non_retryable_via_cause_chain(self):
        # The activity wraps the Arrow type error as CDCSchemaMergeError; classification must
        # find it through the cause chain and mark the run non-retryable so it stops looping.
        cause = CDCSchemaMergeError("Incompatible column types across CDC batches for orders")
        wrapper = RuntimeError("flush failed")
        wrapper.__cause__ = cause
        info = classify_cdc_error(wrapper, None)
        assert info.category is CDCErrorCategory.SCHEMA_MERGE_INCOMPATIBLE
        assert info.retryable is False

    def test_non_psycopg_exception_with_slot_message_is_not_classified(self):
        # A non-psycopg exception whose message happens to contain slot/auth patterns must not be
        # misclassified as non-retryable — only psycopg exceptions carry these patterns meaningfully.
        exc = RuntimeError("replication slot my_slot does not exist")
        info = classify_cdc_error(exc, PostgresCDCAdapter())
        assert info.category is CDCErrorCategory.UNKNOWN
        assert info.retryable is True

    def test_friendly_message_never_echoes_raw_exception(self):
        # A connection error carrying secrets must classify to the static friendly copy,
        # never interpolate the raw message — no credential/host leakage into latest_error.
        exc = psycopg.OperationalError("connection failed: password=hunter2 host=secret.db.internal:5432")
        info = classify_cdc_error(exc, PostgresCDCAdapter())
        assert info.category is CDCErrorCategory.CONNECTION_FAILED
        assert "hunter2" not in info.friendly_message
        assert "secret.db.internal" not in info.friendly_message
