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
            ("cannot_parse_text", 6),
            ("cannot_parse_number", 72),
        ]
    )
    def test_clickhouse_value_parse_failure_surfaces_as_a_caller_error(self, _name, code):
        # A numeric operator against a null/non-numeric filter value fails the Float64 cast at
        # execution; these codes wrap to InternalCHQueryError (not Exposed), so they used to 500.
        # The 400 is what the caller needs, but the ClickHouse message is not: it names a column
        # type and a Python repr, so the body must carry the actionable line instead.
        raw = "DB::Exception: Cannot parse NaN: converting 'None' to Float64. Stack trace:\n0. DB::Exception::Exception"
        err = wrap_clickhouse_query_error(ServerException(raw, code=code))
        with self.assertRaises(ValidationError) as ctx, unevaluable_filters_as_validation_errors():
            raise err
        message = str(ctx.exception)
        self.assertNotIn("Cannot parse NaN", message)
        self.assertNotIn("Float64", message)
        self.assertIn("Check the property values", message)

    def test_other_internal_clickhouse_errors_stay_server_faults(self):
        # Only the deterministic cannot-parse-value codes are the caller's input; anything else
        # (here LOGICAL_ERROR) must keep surfacing as a 500 so real faults reach error tracking.
        err = wrap_clickhouse_query_error(ServerException("Logical error: invariant violated", code=49))
        with self.assertRaises(InternalCHQueryError), unevaluable_filters_as_validation_errors():
            raise err

    @parameterized.expand(
        [
            ("no_supertype", 386, "There is no supertype for types String, UInt8 because some of them are String"),
            ("illegal_type_of_argument", 43, "Illegal type String of argument of function equals"),
        ]
    )
    def test_clickhouse_engine_text_never_reaches_the_caller(self, _name, code, raw):
        # These codes are user_safe, so they wrap to ExposedCHQueryError and used to put the
        # ClickHouse message straight into the 400 body, which the release condition editor
        # prints. Engine text names ClickHouse types and generated SQL, so it must be replaced.
        err = wrap_clickhouse_query_error(ServerException(f"DB::Exception: {raw}", code=code))
        with self.assertRaises(ValidationError) as ctx, unevaluable_filters_as_validation_errors():
            raise err
        message = str(ctx.exception)
        self.assertNotIn("String, UInt8", message)
        self.assertNotIn("Illegal type", message)
        self.assertIn("Check the property values", message)

    def test_curated_clickhouse_message_is_kept(self):
        # Code 70 carries PostHog-written copy in its ErrorCodeMeta, which replaces the engine
        # message during wrapping. That copy is worth showing, so it must survive.
        err = wrap_clickhouse_query_error(ServerException("DB::Exception: CANNOT_CONVERT_TYPE", code=70))
        with self.assertRaises(ValidationError) as ctx, unevaluable_filters_as_validation_errors():
            raise err
        self.assertIn("Cannot convert one type to another", str(ctx.exception))
