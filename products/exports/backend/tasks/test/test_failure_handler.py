from unittest import TestCase

from django.core.exceptions import ValidationError as DjangoValidationError

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.exceptions import ClickHouseAtCapacity, ClickHouseClusterMemoryLimitExceeded

from products.exports.backend.tasks.failure_handler import (
    FAILURE_TYPE_SYSTEM,
    FAILURE_TYPE_TIMEOUT_GENERATION,
    FAILURE_TYPE_UNKNOWN,
    FAILURE_TYPE_USER,
    SLO_FAILURE_CATEGORY_APPLICATION,
    SLO_FAILURE_CATEGORY_QUERY_CAPACITY,
    SLO_FAILURE_CATEGORY_RENDERER_RATE_LIMITED,
    SLO_FAILURE_CATEGORY_RENDERER_TIMEOUT,
    SLO_FAILURE_CATEGORY_RENDERER_UNAVAILABLE,
    SLO_FAILURE_CATEGORY_STORAGE,
    BrowserlessUnavailable,
    ExportCancelled,
    classify_failure_type,
    export_slo_failure_details,
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
            ("OperationalError", FAILURE_TYPE_SYSTEM),
            ("ClickHouseAtCapacity", FAILURE_TYPE_SYSTEM),
            ("ReadTimeoutError", FAILURE_TYPE_SYSTEM),
            ("ObjectStorageError", FAILURE_TYPE_SYSTEM),
            ("RetryableExportError", FAILURE_TYPE_SYSTEM),
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


class TestExportSloFailureDetails(TestCase):
    @parameterized.expand(
        [
            (
                "browserless_rate_limit",
                BrowserlessUnavailable("Browserless returned 429 Too Many Requests"),
                SLO_FAILURE_CATEGORY_RENDERER_RATE_LIMITED,
                "browserless",
                True,
            ),
            ("render_timeout", "TimeoutError", SLO_FAILURE_CATEGORY_RENDERER_TIMEOUT, "browserless", True),
            (
                "export_cancelled",
                ExportCancelled("cancelled"),
                SLO_FAILURE_CATEGORY_RENDERER_TIMEOUT,
                "browserless",
                False,
            ),
            ("query_capacity", "ConcurrencyLimitExceeded", SLO_FAILURE_CATEGORY_QUERY_CAPACITY, "query", True),
            # ClickHouse capacity errors share the query_capacity category — classify_query_error groups
            # the same three as RATE_LIMITED. The instance path is what the export activity feeds in, and
            # ClickHouseClusterMemoryLimitExceeded subclasses a user-query error, so without an explicit
            # capacity check it would fall through to the query (user) or transient_dependency buckets.
            (
                "query_capacity_at_capacity_instance",
                ClickHouseAtCapacity(),
                SLO_FAILURE_CATEGORY_QUERY_CAPACITY,
                "query",
                True,
            ),
            (
                "query_capacity_cluster_memory_instance",
                ClickHouseClusterMemoryLimitExceeded(),
                SLO_FAILURE_CATEGORY_QUERY_CAPACITY,
                "query",
                True,
            ),
            ("storage", "CHQueryErrorS3Error", SLO_FAILURE_CATEGORY_STORAGE, "object_storage", True),
            ("unknown", "RuntimeError", SLO_FAILURE_CATEGORY_APPLICATION, "exporter", False),
        ]
    )
    def test_returns_safe_breakdown_dimensions(
        self,
        _name: str,
        exception: Exception | str,
        category: str,
        component: str,
        retryable: bool,
    ) -> None:
        assert export_slo_failure_details(exception) == {
            "failure_category": category,
            "failure_component": component,
            "failure_retryable": retryable,
        }

    def test_bounds_browserless_rate_limit_message_inspection(self) -> None:
        exception = BrowserlessUnavailable(f"{'x' * 8_000} 429 Too Many Requests")

        assert export_slo_failure_details(exception) == {
            "failure_category": SLO_FAILURE_CATEGORY_RENDERER_UNAVAILABLE,
            "failure_component": "browserless",
            "failure_retryable": True,
        }
