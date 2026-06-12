from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import PropertyOperator, SpanPropertyFilter, SpanPropertyFilterType

from products.tracing.backend.logic import translate_span_filter


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
            ("status_code", "status_code", 2, ["2"]),
            ("kind", "kind", "3", ["3"]),
        ]
    )
    def test_translation_is_idempotent(self, _name, key, value, expected):
        span_filter = _span_filter(key, value)
        translate_span_filter(span_filter)
        translate_span_filter(span_filter)
        self.assertEqual(span_filter.value, expected)
