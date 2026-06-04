from unittest import TestCase

from parameterized import parameterized

from products.exports.backend.tasks.failure_handler import (
    FAILURE_TYPE_SYSTEM,
    FAILURE_TYPE_TIMEOUT_GENERATION,
    FAILURE_TYPE_UNKNOWN,
    FAILURE_TYPE_USER,
    NON_RETRYABLE_SYSTEM_ERROR_NAMES,
    RETRYABLE_ERROR_NAMES,
    SYSTEM_ERROR_NAMES,
    classify_failure_type,
    is_user_query_error_type,
)


class TestIsUserQueryErrorType(TestCase):
    @parameterized.expand(
        [
            # User query errors - should return True
            ("QueryError", True),
            ("SyntaxError", True),
            ("CHQueryErrorIllegalAggregation", True),
            ("CHQueryErrorIllegalTypeOfArgument", True),
            ("CHQueryErrorNoCommonType", True),
            ("CHQueryErrorNotAnAggregate", True),
            ("CHQueryErrorTypeMismatch", True),
            ("CHQueryErrorUnknownFunction", True),
            ("ClickHouseQueryTimeOut", True),
            ("ClickHouseQueryMemoryLimitExceeded", True),
            ("CHQueryErrorInvalidJoinOnExpression", True),
            ("CHQueryErrorUnknownTable", True),
            ("ExcelColumnLimitExceeded", True),
            # Non-user errors - should return False
            ("TimeoutError", False),
            ("ValueError", False),
            ("CHQueryErrorS3Error", False),
            ("CHQueryErrorTooManySimultaneousQueries", False),
            ("ClickHouseAtCapacity", False),
            ("ConcurrencyLimitExceeded", False),
            ("ReadTimeoutError", False),
            (None, False),
            ("", False),
        ]
    )
    def test_is_user_query_error_type(self, exception_type: str | None, expected: bool) -> None:
        assert is_user_query_error_type(exception_type) == expected


class TestClassifyFailureType(TestCase):
    @parameterized.expand(
        [
            # Timeout errors
            ("SoftTimeLimitExceeded", FAILURE_TYPE_TIMEOUT_GENERATION),
            ("TimeoutError", FAILURE_TYPE_TIMEOUT_GENERATION),
            # User errors (from USER_QUERY_ERRORS)
            ("QueryError", FAILURE_TYPE_USER),
            ("SyntaxError", FAILURE_TYPE_USER),
            ("CHQueryErrorIllegalAggregation", FAILURE_TYPE_USER),
            ("ClickHouseQueryTimeOut", FAILURE_TYPE_USER),
            ("ClickHouseQueryMemoryLimitExceeded", FAILURE_TYPE_USER),
            ("CHQueryErrorInvalidJoinOnExpression", FAILURE_TYPE_USER),
            ("CHQueryErrorUnknownTable", FAILURE_TYPE_USER),
            ("ExcelColumnLimitExceeded", FAILURE_TYPE_USER),
            # System errors (from EXCEPTIONS_TO_RETRY)
            ("CHQueryErrorS3Error", FAILURE_TYPE_SYSTEM),
            ("CHQueryErrorTooManySimultaneousQueries", FAILURE_TYPE_SYSTEM),
            ("OperationalError", FAILURE_TYPE_SYSTEM),
            ("ClickHouseAtCapacity", FAILURE_TYPE_SYSTEM),
            ("ReadTimeoutError", FAILURE_TYPE_SYSTEM),
            ("BrowserlessUnavailable", FAILURE_TYPE_SYSTEM),
            # Non-retryable system errors still classify as SYSTEM (infra, not user's fault)
            ("BrowserlessRateLimited", FAILURE_TYPE_SYSTEM),
            # Unknown errors
            ("ValueError", FAILURE_TYPE_UNKNOWN),
            ("RuntimeError", FAILURE_TYPE_UNKNOWN),
            ("", FAILURE_TYPE_UNKNOWN),
        ]
    )
    def test_classify_failure_type(self, exception_type: str, expected: str) -> None:
        assert classify_failure_type(exception_type) == expected


class TestRetryableErrorNames(TestCase):
    def test_browserless_unavailable_is_retryable(self) -> None:
        # Genuine connection drops / unreachable backend are worth retrying.
        assert "BrowserlessUnavailable" in RETRYABLE_ERROR_NAMES

    def test_browserless_rate_limited_is_not_retryable(self) -> None:
        # Retrying a 429 back into an overloaded endpoint compounds the rate-limiting.
        assert "BrowserlessRateLimited" not in RETRYABLE_ERROR_NAMES
        assert "BrowserlessRateLimited" in NON_RETRYABLE_SYSTEM_ERROR_NAMES

    def test_non_retryable_system_errors_are_classified_as_system(self) -> None:
        # SYSTEM_ERROR_NAMES (classification) is the union of retryable and non-retryable.
        assert NON_RETRYABLE_SYSTEM_ERROR_NAMES <= SYSTEM_ERROR_NAMES
        assert RETRYABLE_ERROR_NAMES <= SYSTEM_ERROR_NAMES
        # Non-retryable names are deliberately absent from the retryable set.
        assert RETRYABLE_ERROR_NAMES.isdisjoint(NON_RETRYABLE_SYSTEM_ERROR_NAMES)
