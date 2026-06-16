"""Tests for experiment error handling decorator and error message mapping."""

from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from clickhouse_driver.errors import ServerException
from rest_framework.exceptions import ErrorDetail, ValidationError

from posthog.errors import wrap_clickhouse_query_error
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded

from products.experiments.backend.hogql_queries.error_handling import (
    ERROR_TYPE_TO_CODE,
    experiment_error_handler,
    get_user_friendly_message,
)
from products.experiments.backend.hogql_queries.utils import ExperimentDataError

# ClickHouse error code for "Limit for rows or bytes to read exceeded" (TOO_MANY_ROWS_OR_BYTES).
# This is the error that blocked experiment loads in the originating incident.
TOO_MANY_ROWS_OR_BYTES_CODE = 396


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

    def test_get_user_friendly_message_for_clickhouse_read_limit_exceeded(self):
        """The 'rows or bytes to read exceeded' error (the incident trigger) should degrade to a
        friendly resource-limit message instead of surfacing as a raw 500."""
        raw_error = ServerException(
            "Limit for rows or bytes to read exceeded, max bytes 5.00 TiB",
            code=TOO_MANY_ROWS_OR_BYTES_CODE,
        )
        wrapped_error = wrap_clickhouse_query_error(raw_error)

        # The wrapped error is a dynamically-built CHQueryError subclass, not a type we map
        # explicitly — classification is what catches it.
        self.assertNotIsInstance(wrapped_error, ClickHouseQueryMemoryLimitExceeded)

        expected = (
            "This experiment query exceeded resource limits. Try viewing a shorter time period, "
            "or contact support if the problem persists."
        )
        self.assertEqual(get_user_friendly_message(raw_error), expected)
        self.assertEqual(get_user_friendly_message(wrapped_error), expected)

    def test_get_user_friendly_message_for_clickhouse_at_capacity(self):
        """Capacity / rate-limit errors should degrade to a friendly retry message."""
        message = get_user_friendly_message(ClickHouseAtCapacity())

        self.assertEqual(message, "Experiment analytics are temporarily at capacity. Please refresh in a moment.")

    def test_get_user_friendly_message_for_experiment_data_error(self):
        """Data-shape errors (e.g. no control variant) should degrade to a friendly message."""
        message = get_user_friendly_message(ExperimentDataError("No control variant found"))

        self.assertEqual(
            message,
            "Unable to calculate experiment results from the collected data. This usually resolves once more exposures are recorded.",
        )

    def test_get_user_friendly_message_for_generic_value_error_passes_through(self):
        """Generic ValueErrors are intentionally not mapped so the original message stays visible."""
        self.assertIsNone(get_user_friendly_message(ValueError("some generic value error")))

    @patch("products.experiments.backend.hogql_queries.error_handling.capture_exception")
    def test_decorator_converts_read_limit_exceeded_to_validation_error(self, mock_capture):
        """The decorator should convert the read-limit ClickHouse error into a 400-style
        ValidationError with a stable code rather than re-raising a 500."""

        @experiment_error_handler
        def failing_method(self):
            raise wrap_clickhouse_query_error(
                ServerException(
                    "Limit for rows or bytes to read exceeded, max bytes 5.00 TiB",
                    code=TOO_MANY_ROWS_OR_BYTES_CODE,
                )
            )

        mock_self = Mock()
        mock_self.experiment_id = 123
        mock_self.metric = None
        mock_self.user_facing = True

        with self.assertRaises(ValidationError) as context:
            failing_method(mock_self)

        detail_list = cast(list[ErrorDetail], context.exception.detail)
        self.assertEqual(
            str(detail_list[0]),
            "This experiment query exceeded resource limits. Try viewing a shorter time period, "
            "or contact support if the problem persists.",
        )
        self.assertEqual(detail_list[0].code, "query_resource_limit_exceeded")
        mock_capture.assert_called_once()

    @patch("products.experiments.backend.hogql_queries.error_handling.capture_exception")
    def test_decorator_converts_experiment_data_error(self, mock_capture):
        """The decorator should convert ExperimentDataError into a user-facing ValidationError."""

        @experiment_error_handler
        def failing_method(self):
            raise ExperimentDataError("No control variant found")

        mock_self = Mock()
        mock_self.experiment_id = 123
        mock_self.metric = None
        mock_self.user_facing = True

        with self.assertRaises(ValidationError) as context:
            failing_method(mock_self)

        detail_list = cast(list[ErrorDetail], context.exception.detail)
        self.assertEqual(
            str(detail_list[0]),
            "Unable to calculate experiment results from the collected data. This usually resolves once more exposures are recorded.",
        )
        mock_capture.assert_called_once()

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
