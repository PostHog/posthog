from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.errors import CLICKHOUSE_ERROR_CODE_LOOKUP, InternalCHQueryError, wrap_clickhouse_query_error
from posthog.models.property import PropertyValidationError

from products.feature_flags.backend.user_blast_radius import (
    UNEVALUABLE_FILTERS_MESSAGE,
    unevaluable_filters_as_validation_errors,
)

PARSE_NAN_TO_FLOAT = "Cannot parse NaN: converting 'None' to Float64"


class TestUnevaluableFiltersAsValidationErrors(SimpleTestCase):
    def test_property_validation_error_surfaces_as_a_caller_error(self):
        # Raised by Property.__init__ during query build (e.g. a referenced cohort stored with a
        # value-less property); a plain ValueError subclass, so it used to escape as a 500.
        with self.assertRaises(ValidationError) as ctx, unevaluable_filters_as_validation_errors():
            raise PropertyValidationError("Value must be set for property type person & operator gt")
        self.assertIn("Value must be set", str(ctx.exception))

    @parameterized.expand(
        [
            ("cannot_parse_text", 6, PARSE_NAN_TO_FLOAT, CLICKHOUSE_ERROR_CODE_LOOKUP[6].user_safe),
            ("cannot_parse_number", 72, PARSE_NAN_TO_FLOAT, CLICKHOUSE_ERROR_CODE_LOOKUP[72].user_safe),
            (
                "no_supertype",
                386,
                "There is no supertype for types String, UInt8 because some of them are String",
                UNEVALUABLE_FILTERS_MESSAGE,
            ),
            (
                "illegal_type_of_argument",
                43,
                "Illegal type String of argument of function equals",
                UNEVALUABLE_FILTERS_MESSAGE,
            ),
            ("curated_copy", 70, "CANNOT_CONVERT_TYPE", CLICKHOUSE_ERROR_CODE_LOOKUP[70].user_safe),
        ]
    )
    def test_clickhouse_failure_surfaces_as_a_caller_error(self, _name, code, raw, expected):
        # The 400 carries only copy that PostHog wrote, because the ClickHouse message names
        # engine types and generated SQL instead of the filter to correct. A code whose
        # ErrorCodeMeta names a user-facing string keeps that string; the rest fall back to the
        # generic line.
        err = wrap_clickhouse_query_error(ServerException(f"DB::Exception: {raw}", code=code))
        with self.assertRaises(ValidationError) as ctx, unevaluable_filters_as_validation_errors():
            raise err
        self.assertEqual(ctx.exception.detail["filters"], expected)

    def test_other_internal_clickhouse_errors_stay_server_faults(self):
        # Only the deterministic cannot-parse-value codes are the caller's input; anything else
        # (here LOGICAL_ERROR) must keep surfacing as a 500 so real faults reach error tracking.
        err = wrap_clickhouse_query_error(ServerException("Logical error: invariant violated", code=49))
        with self.assertRaises(InternalCHQueryError), unevaluable_filters_as_validation_errors():
            raise err
