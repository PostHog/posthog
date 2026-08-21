from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException
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

    def test_cannot_parse_number_surfaces_the_useful_message(self):
        # A numeric operator against a null/non-numeric filter value fails the Float64 cast at
        # execution; CANNOT_PARSE_NUMBER (72) wraps to InternalCHQueryError (not Exposed), so it
        # used to 500. The 400 body must carry only the useful message: the DB::Exception framing
        # and any server stack trace tail are stripped, matching what ExposedCHQueryError exposes.
        raw = "DB::Exception: Cannot parse NaN: converting 'None' to Float64. Stack trace:\n0. DB::Exception::Exception"
        err = wrap_clickhouse_query_error(ServerException(raw, code=72))
        with self.assertRaises(ValidationError) as ctx, unevaluable_filters_as_validation_errors():
            raise err
        message = str(ctx.exception)
        self.assertIn("Cannot parse NaN", message)
        self.assertNotIn("Stack trace", message)
        self.assertNotIn("DB::Exception", message)

    def test_cannot_parse_text_surfaces_a_sanitized_message(self):
        # CANNOT_PARSE_TEXT (6) now wraps to ExposedCHQueryError with a fixed message, since the raw
        # CH text embeds the failing data value. It still surfaces as a 400, but the body carries the
        # generic message and never the source value or server framing.
        raw = "DB::Exception: Cannot parse string 'secret' as IPv4. Stack trace:\n0. DB::Exception::Exception"
        err = wrap_clickhouse_query_error(ServerException(raw, code=6))
        with self.assertRaises(ValidationError) as ctx, unevaluable_filters_as_validation_errors():
            raise err
        message = str(ctx.exception)
        self.assertIn("could not be parsed", message)
        self.assertNotIn("secret", message)
        self.assertNotIn("Stack trace", message)
        self.assertNotIn("DB::Exception", message)

    def test_other_internal_clickhouse_errors_stay_server_faults(self):
        # Only the deterministic cannot-parse-value codes are the caller's input; anything else
        # (here LOGICAL_ERROR) must keep surfacing as a 500 so real faults reach error tracking.
        err = wrap_clickhouse_query_error(ServerException("Logical error: invariant violated", code=49))
        with self.assertRaises(InternalCHQueryError), unevaluable_filters_as_validation_errors():
            raise err
