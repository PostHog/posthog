"""Tests for experiment error handling decorator and error message mapping."""

from contextlib import contextmanager
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from clickhouse_driver.errors import ServerException
from parameterized import parameterized
from rest_framework.exceptions import ErrorDetail, ValidationError

from posthog.hogql.errors import ExposedHogQLError

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut

from products.experiments.backend.hogql_queries.error_handling import (
    ERROR_TYPE_TO_CODE,
    classify_experiment_query_error,
    experiment_error_handler,
    get_user_friendly_message,
)
from products.experiments.stats.shared.statistics import StatisticError


@contextmanager
def _record_captures():
    captured: list[dict] = []

    def _fake_capture(*args, **kwargs) -> None:
        captured.append(kwargs)

    @contextmanager
    def _fake_scoped_capture():
        yield _fake_capture

    with patch(
        "products.experiments.backend.hogql_queries.error_handling.ph_scoped_capture",
        _fake_scoped_capture,
    ):
        yield captured


class TestExperimentErrorHandling(BaseTest):
    def test_get_user_friendly_message_for_memory_limit_exceeded(self):
        """Test that ClickHouseQueryMemoryLimitExceeded gets a user-friendly message."""
        error = ClickHouseQueryMemoryLimitExceeded()
        message = get_user_friendly_message(error)

        self.assertIsNotNone(message)
        self.assertEqual(
            message,
            "This experiment query is using too much memory. Try viewing a shorter time period or contact support for help.",
        )

    def test_get_user_friendly_message_for_unmapped_error(self):
        """Test that unmapped errors return None."""
        error = RuntimeError("Some unexpected error")
        message = get_user_friendly_message(error)

        self.assertIsNone(message)

    @patch("products.experiments.backend.hogql_queries.error_handling.capture_exception")
    def test_decorator_converts_memory_limit_exception(self, mock_capture):
        """Test that the decorator converts ClickHouseQueryMemoryLimitExceeded to ValidationError."""

        @experiment_error_handler
        def failing_method(self):
            raise ClickHouseQueryMemoryLimitExceeded()

        mock_self = Mock()
        mock_self.experiment_id = None  # Ensure this is None so the fallback to experiment.id is used
        mock_experiment = Mock()
        mock_experiment.id = 123
        mock_self.experiment = mock_experiment
        mock_self.metric = None
        mock_self.user_facing = True

        with self.assertRaises(ValidationError) as context:
            failing_method(mock_self)

        # ValidationError.detail can be a list or dict, check it's a list first
        self.assertIsInstance(context.exception.detail, list)

        # Cast to list for type checker
        detail_list = cast(list[ErrorDetail], context.exception.detail)

        self.assertEqual(
            str(detail_list[0]),
            "This experiment query is using too much memory. Try viewing a shorter time period or contact support for help.",
        )
        # Verify error code is set correctly
        # In DRF, the code is stored in the ErrorDetail object, not directly on the exception
        self.assertIsInstance(detail_list[0], ErrorDetail)
        self.assertEqual(detail_list[0].code, "memory_limit_exceeded")

        # Verify exception was captured with correct properties
        mock_capture.assert_called_once()
        call_args = mock_capture.call_args
        self.assertIsInstance(call_args[0][0], ClickHouseQueryMemoryLimitExceeded)
        self.assertEqual(call_args[1]["additional_properties"]["experiment_id"], 123)
        self.assertEqual(call_args[1]["additional_properties"]["query_runner"], "Mock")

    @patch("products.experiments.backend.hogql_queries.error_handling.capture_exception")
    def test_decorator_captures_query_runner_name(self, mock_capture):
        """Test that the decorator captures the query runner class name."""

        @experiment_error_handler
        def failing_method(self):
            raise ClickHouseQueryMemoryLimitExceeded()

        class ExperimentExposuresQueryRunner:
            def __init__(self):
                self.experiment = Mock(id=456)
                self.metric = None
                self.user_facing = True

        runner = ExperimentExposuresQueryRunner()

        with self.assertRaises(ValidationError):
            failing_method(runner)

        mock_capture.assert_called_once()
        additional_props = mock_capture.call_args[1]["additional_properties"]
        self.assertEqual(additional_props["query_runner"], "ExperimentExposuresQueryRunner")
        self.assertEqual(additional_props["experiment_id"], 456)

    @patch("products.experiments.backend.hogql_queries.error_handling.capture_exception")
    def test_decorator_does_not_convert_for_non_user_facing(self, mock_capture):
        """Test that the decorator doesn't convert exceptions when user_facing=False."""

        @experiment_error_handler
        def failing_method(self):
            raise ClickHouseQueryMemoryLimitExceeded()

        mock_self = Mock()
        mock_self.experiment = Mock(id=123)
        mock_self.metric = None
        mock_self.user_facing = False

        # Should re-raise the original exception
        with self.assertRaises(ClickHouseQueryMemoryLimitExceeded):
            failing_method(mock_self)

        # Should still capture for internal tracking
        mock_capture.assert_called_once()

    def test_error_type_to_code_mapping(self):
        """Test that ClickHouseQueryMemoryLimitExceeded has a code mapping."""
        self.assertIn(ClickHouseQueryMemoryLimitExceeded, ERROR_TYPE_TO_CODE)
        self.assertEqual(ERROR_TYPE_TO_CODE[ClickHouseQueryMemoryLimitExceeded], "memory_limit_exceeded")

    @parameterized.expand(
        [
            ("wrapped_timeout", ClickHouseQueryTimeOut(), "timeout"),
            ("ch_timeout_code", ServerException("timed out", code=159), "timeout"),
            ("wrapped_oom", ClickHouseQueryMemoryLimitExceeded(), "out_of_memory"),
            ("ch_memory_limit_code", ServerException("memory limit", code=241), "out_of_memory"),
            ("ch_too_many_bytes_code", ServerException("too many bytes", code=307), "byte_limit"),
            ("wrapped_at_capacity", ClickHouseAtCapacity(), "rate_limited"),
            ("app_concurrency_limit", ConcurrencyLimitExceeded("app:query:per-org"), "rate_limited"),
            ("ch_too_many_queries_code", ServerException("too many queries", code=202), "rate_limited"),
            ("statistic_error", StatisticError("not enough data"), "insufficient_data"),
            ("zero_division", ZeroDivisionError(), "insufficient_data"),
            ("validation_error", ValidationError("bad metric config"), "validation_error"),
            ("exposed_hogql_error", ExposedHogQLError("unknown property"), "validation_error"),
            ("anything_else", RuntimeError("kaboom"), "server_error"),
        ]
    )
    def test_classify_experiment_query_error(self, _name, error, expected):
        # The taxonomy contract behind every 'experiment metric error' emitter. byte_limit (307) and
        # rate_limited (202) are the buckets that historically collapsed into server_error, hiding the
        # two biggest real failure modes — a regression here makes them invisible again.
        self.assertEqual(classify_experiment_query_error(error), expected)


class _FakeRunner:
    """Minimal stand-in exposing the attributes the error boundary reads off a query runner."""

    def __init__(self, team, *, error, error_event_context="ui", user_facing=True):
        self.team = team
        self.error_event_context = error_event_context
        self.user_facing = user_facing
        self.experiment_id = 42
        self.metric = None
        self.query = None
        self.user = None
        self._error = error

    @experiment_error_handler
    def _calculate(self):
        raise self._error


class TestTerminalErrorEventEmission(BaseTest):
    """The error boundary is the single terminal emitter for direct (in-request) paths. Over-emission
    double-counts retried orchestrated attempts; under-emission makes UI/agent failures invisible."""

    def test_emits_terminal_event_with_context_and_mechanism(self):
        runner = _FakeRunner(self.team, error=ServerException("too many bytes", code=307))

        with _record_captures() as captured, self.assertRaises(ServerException):
            runner._calculate()

        assert len(captured) == 1
        assert captured[0]["event"] == "experiment metric error"
        props = captured[0]["properties"]
        assert props["error_type"] == "byte_limit"
        assert props["context"] == "ui"
        assert props["mechanism"] == "direct"
        assert props["experiment_id"] == 42
        assert props["team_id"] == self.team.id
        assert captured[0]["distinct_id"] == f"team_{self.team.id}"

    def test_user_facing_validation_errors_still_emit(self):
        # ValidationError/ExposedHogQLError pass through the boundary unconverted, but a misconfigured
        # metric fails every load — terminal user pain that must be counted, tagged validation_error.
        runner = _FakeRunner(self.team, error=ValidationError("bad metric"))

        with _record_captures() as captured, self.assertRaises(ValidationError):
            runner._calculate()

        assert len(captured) == 1
        assert captured[0]["properties"]["error_type"] == "validation_error"

    @parameterized.expand(
        [
            ("no_context", {"error_event_context": None, "user_facing": True}),
            ("internal_caller", {"error_event_context": "ui", "user_facing": False}),
        ]
    )
    def test_internal_callers_stay_silent(self, _name, runner_kwargs):
        # Recalc, canary, warming, and backfills own their retries and telemetry; a runner-level emit
        # there would count non-terminal attempts (or double-count next to the orchestrator's emit).
        runner = _FakeRunner(self.team, error=RuntimeError("kaboom"), **runner_kwargs)

        with _record_captures() as captured, self.assertRaises(RuntimeError):
            runner._calculate()

        assert captured == []
