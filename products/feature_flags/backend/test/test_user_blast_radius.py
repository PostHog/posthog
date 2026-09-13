from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.errors import InternalCHQueryError, wrap_clickhouse_query_error
from posthog.models.property import PropertyValidationError

from products.feature_flags.backend.user_blast_radius import unevaluable_filters_as_validation_errors


class TestUnevaluableFiltersAsValidationErrors(SimpleTestCase):
    def test_property_validation_error_surfaces_as_a_caller_error(self):
        # Raised by Property.__init__ during query build (e.g. a referenced cohort stored with a
        # value-less property); a plain ValueError subclass, so it used to escape as a 500.
        with self.assertRaises(ValidationError) as ctx, unevaluable_filters_as_validation_errors():
            raise PropertyValidationError("Value must be set for property type person & operator gt")
        self.assertIn("Value must be set", str(ctx.exception))

    @parameterized.expand(
        [
            (
                "cannot_parse_text",
                6,
                "Cannot parse a text value as the required type. Check the types in your comparisons and IN clauses.",
            ),
            (
                "cannot_parse_number",
                72,
                "Cannot parse a value in the query as a number. Check the types in your comparisons and IN clauses.",
            ),
        ]
    )
    def test_clickhouse_value_parse_failure_surfaces_as_a_caller_error(self, _name, code, expected_message):
        # A numeric operator against a null/non-numeric filter value fails the Float64 cast at
        # execution. These codes are user_safe with a fixed message (posthog/errors.py), so they
        # surface as a 400 whose body hides the failing data value the raw ClickHouse text embeds.
        raw = "DB::Exception: Cannot parse NaN: converting 'None' to Float64. Stack trace:\n0. DB::Exception::Exception"
        err = wrap_clickhouse_query_error(ServerException(raw, code=code))
        with self.assertRaises(ValidationError) as ctx, unevaluable_filters_as_validation_errors():
            raise err
        message = str(ctx.exception)
        self.assertIn(expected_message, message)
        # The raw ClickHouse text and the embedded value must not reach the caller.
        self.assertNotIn("Cannot parse NaN", message)
        self.assertNotIn("None", message)
        self.assertNotIn("Stack trace", message)
        self.assertNotIn("DB::Exception", message)

    def test_other_internal_clickhouse_errors_stay_server_faults(self):
        # Only the deterministic cannot-parse-value codes are the caller's input; anything else
        # (here LOGICAL_ERROR) must keep surfacing as a 500 so real faults reach error tracking.
        err = wrap_clickhouse_query_error(ServerException("Logical error: invariant violated", code=49))
        with self.assertRaises(InternalCHQueryError), unevaluable_filters_as_validation_errors():
            raise err
