from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import PropertyOperator, SpanPropertyFilter, SpanPropertyFilterType

from products.tracing.backend.logic import UnknownSpanFilterKeyError, translate_span_filter, validate_span_filter_key


def _span_filter(key: str, value: object) -> SpanPropertyFilter:
    return SpanPropertyFilter(
        key=key,
        operator=PropertyOperator.EXACT,
        type=SpanPropertyFilterType.SPAN,
        value=value,
    )


class TestTranslateSpanFilter(SimpleTestCase):
    @parameterized.expand(
        [
            # status_code normalises to string-digit codes. Integers and digit strings
            # must survive — an integer must NOT collapse to [] (which filters nothing).
            ("status_code_int", "status_code", 2, ["2"]),
            ("status_code_int_zero", "status_code", 0, ["0"]),
            ("status_code_digit_string", "status_code", "2", ["2"]),
            ("status_code_error_label", "status_code", "Error", ["2"]),
            ("status_code_ok_label", "status_code", "OK", ["0", "1"]),
            ("status_code_list_ints", "status_code", [0, 2], ["0", "2"]),
            # kind normalises to string-digit codes (same form as status_code). Digit strings
            # and ints must survive — they must NOT collapse to [].
            ("kind_int", "kind", 2, ["2"]),
            ("kind_digit_string", "kind", "3", ["3"]),
            ("kind_server_label", "kind", "Server", ["2"]),
            ("kind_list_digit_strings", "kind", ["2", "3"], ["2", "3"]),
        ]
    )
    def test_normalises_status_code_and_kind_values(self, _name, key, value, expected):
        span_filter = _span_filter(key, value)
        translate_span_filter(span_filter)
        self.assertEqual(span_filter.value, expected)

    @parameterized.expand(
        [
            # Duration is given in seconds and converted to nanoseconds. The result must be an
            # integer string — a `.0`-suffixed value can't be cast to the UInt64 `duration_nano`
            # column and makes ClickHouse throw. Floats (e.g. the slider max) are the regression.
            ("duration_int", 2, "2000000"),
            ("duration_float", 2000000000.0, "2000000000000000"),
            ("duration_float_string", "2000000000.0", "2000000000000000"),
            ("duration_int_string", "2", "2000000"),
        ]
    )
    def test_duration_converts_to_integer_nanoseconds(self, _name, value, expected):
        span_filter = _span_filter("duration", value)
        translate_span_filter(span_filter)
        self.assertEqual(span_filter.key, "duration_nano")
        self.assertEqual(span_filter.value, expected)

    def test_duration_list_converts_to_integer_nanoseconds(self):
        span_filter = _span_filter("duration", [1.0, 2000000000.0])
        translate_span_filter(span_filter)
        self.assertEqual(span_filter.key, "duration_nano")
        self.assertEqual(span_filter.value, ["1000000", "2000000000000000"])

    @parameterized.expand(
        [
            # The API returns all three ids as hex, while the columns store base64, so each one
            # needs converting or a filter on a value the API just handed out matches zero rows.
            ("trace_id", "trace_id", "00000000000000000000000000000001", "AAAAAAAAAAAAAAAAAAAAAQ=="),
            ("span_id", "span_id", "0000000000000001", "AAAAAAAAAAE="),
            ("parent_span_id", "parent_span_id", "0000000000000001", "AAAAAAAAAAE="),
        ]
    )
    def test_hex_ids_convert_to_base64(self, _name, key, value, expected):
        span_filter = _span_filter(key, value)
        translate_span_filter(span_filter)
        self.assertEqual(span_filter.value, expected)

    def test_hex_id_list_converts_to_base64(self):
        span_filter = _span_filter("parent_span_id", ["0000000000000001", "0000000000000002"])
        translate_span_filter(span_filter)
        self.assertEqual(span_filter.value, ["AAAAAAAAAAE=", "AAAAAAAAAAI="])

    @parameterized.expand(
        [
            ("status_code", "status_code", 2, ["2"]),
            ("kind", "kind", "3", ["3"]),
            ("parent_span_id", "parent_span_id", "0000000000000001", "AAAAAAAAAAE="),
        ]
    )
    def test_translation_is_idempotent(self, _name, key, value, expected):
        span_filter = _span_filter(key, value)
        translate_span_filter(span_filter)
        translate_span_filter(span_filter)
        self.assertEqual(span_filter.value, expected)


class TestValidateSpanFilterKey(SimpleTestCase):
    @parameterized.expand(
        [
            ("column", "service_name"),
            ("duration_alias", "duration"),
            ("translated_duration", "duration_nano"),
        ]
    )
    def test_accepts_span_columns(self, _name, key):
        validate_span_filter_key(_span_filter(key, "x"))

    @parameterized.expand(
        [
            # OTel attribute keys sent with the wrong filter type. Before the check they reached the
            # HogQL resolver as unknown fields and failed the whole query with a 500.
            ("camel_case_attribute", "sessionId"),
            ("dotted_attribute", "http.method"),
            ("attribute_map", "attributes"),
        ]
    )
    def test_rejects_keys_that_are_not_span_columns(self, _name, key):
        with self.assertRaises(UnknownSpanFilterKeyError) as caught:
            validate_span_filter_key(_span_filter(key, "x"))
        message = str(caught.exception)
        self.assertIn(key, message)
        self.assertIn("span_attribute", message)
        self.assertIn("service_name", message)
