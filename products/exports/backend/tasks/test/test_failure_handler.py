from unittest import TestCase

from django.core.exceptions import ValidationError as DjangoValidationError

from parameterized import parameterized
from playwright.sync_api import Error as PlaywrightError
from rest_framework.exceptions import ValidationError

from products.exports.backend.tasks.failure_handler import (
    FAILURE_TYPE_BENIGN,
    FAILURE_TYPE_SYSTEM,
    FAILURE_TYPE_TIMEOUT_GENERATION,
    FAILURE_TYPE_UNKNOWN,
    FAILURE_TYPE_USER,
    classify_failure_type,
    is_benign_playwright_binding_race,
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
            ("InvalidExportContext", True),
            ("ValidationError", True),  # DRF validation of the user's query (e.g. one-step funnel export)
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
            ("InvalidExportContext", FAILURE_TYPE_USER),
            ("ValidationError", FAILURE_TYPE_USER),
            # System errors (from EXCEPTIONS_TO_RETRY)
            ("CHQueryErrorS3Error", FAILURE_TYPE_SYSTEM),
            ("CHQueryErrorTooManySimultaneousQueries", FAILURE_TYPE_SYSTEM),
            ("OperationalError", FAILURE_TYPE_SYSTEM),
            ("ClickHouseAtCapacity", FAILURE_TYPE_SYSTEM),
            ("ReadTimeoutError", FAILURE_TYPE_SYSTEM),
            # Unknown errors
            ("ValueError", FAILURE_TYPE_UNKNOWN),
            ("RuntimeError", FAILURE_TYPE_UNKNOWN),
            ("", FAILURE_TYPE_UNKNOWN),
        ]
    )
    def test_classify_failure_type(self, exception_type: str, expected: str) -> None:
        assert classify_failure_type(exception_type) == expected

    def test_drf_validation_error_instance_classifies_as_user(self) -> None:
        # The funnel validation rules raise rest_framework.exceptions.ValidationError
        # (e.g. a funnel with fewer than two steps); it must classify as a user error.
        exception = ValidationError("Funnels require at least two steps.", code="funnels_require_at_least_two_steps")
        assert classify_failure_type(exception) == FAILURE_TYPE_USER

    @parameterized.expand(
        [
            # Unrelated classes that merely share a name with a user-query error must not be
            # mislabelled when passed as a live instance — only the in-scope DRF/HogQL types count.
            (DjangoValidationError("not a query error"),),
            (SyntaxError("a Python syntax error, not HogQL's"),),
        ]
    )
    def test_same_named_foreign_exception_instances_are_not_user_errors(self, exception: Exception) -> None:
        assert classify_failure_type(exception) == FAILURE_TYPE_UNKNOWN

    def test_name_string_classification_is_unchanged_for_backfill(self) -> None:
        # Stored rows only carry the class name, so the string path stays purely name-based.
        assert classify_failure_type("ValidationError") == FAILURE_TYPE_USER


class TestBenignPlaywrightBindingRace(TestCase):
    @parameterized.expand(
        [
            ('Function "__pw_storage_change2" is not exposed', True),
            ('Function "__pw_storage_change" is not exposed', True),
            ('Function "__pw_storage_change17" is not exposed', True),
            # Needs both markers, so an unrelated "is not exposed" must not be swallowed.
            ('Function "someOtherBinding" is not exposed', False),
            ("__pw_storage_change2 emitted but page crashed", False),
            ("Timeout while waiting for the page to load", False),
            ("", False),
        ]
    )
    def test_is_benign_playwright_binding_race(self, message: str, expected: bool) -> None:
        assert is_benign_playwright_binding_race(message) is expected
        assert is_benign_playwright_binding_race(PlaywrightError(message)) is expected

    def test_binding_race_instance_classifies_as_benign(self) -> None:
        exception = PlaywrightError('Function "__pw_storage_change2" is not exposed')
        assert classify_failure_type(exception) == FAILURE_TYPE_BENIGN

    def test_binding_race_message_string_classifies_as_benign(self) -> None:
        assert classify_failure_type('Function "__pw_storage_change2" is not exposed') == FAILURE_TYPE_BENIGN
