from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.errors import ExposedHogQLError

from posthog.errors import ExposedCHQueryError, InternalCHQueryError, QueryErrorCategory

from products.logs.backend.alert_error_classifier import TRANSIENT_ERROR_CODES, classify


def _with_category(category: QueryErrorCategory):
    return patch("products.logs.backend.alert_error_classifier.classify_query_error", return_value=category)


class TestClassifyAlertError(TestCase):
    @parameterized.expand(
        [
            (QueryErrorCategory.RATE_LIMITED, "server_busy"),
            (QueryErrorCategory.QUERY_PERFORMANCE_ERROR, "query_performance"),
            (QueryErrorCategory.CANCELLED, "cancelled"),
            (QueryErrorCategory.ERROR, "unknown"),
        ]
    )
    def test_category_maps_to_expected_code(self, category: QueryErrorCategory, expected_code: str) -> None:
        with _with_category(category):
            result = classify(Exception("whatever"))

        assert result.code == expected_code
        assert result.user_message, "user_message must never be empty"

    def test_user_error_from_exposed_ch_error_surfaces_sanitized_text(self) -> None:
        # ExposedCHQueryError.__str__ strips the DB::Exception / Stack trace framing,
        # so the remaining text is safe to surface verbatim.
        exc = ExposedCHQueryError("DB::Exception: Unknown identifier 'foo'\nStack trace: internal", code=47)
        with _with_category(QueryErrorCategory.USER_ERROR):
            result = classify(exc)

        assert result.code == "invalid_query"
        assert "DB::Exception" not in result.user_message
        assert "Stack trace" not in result.user_message
        assert "Unknown identifier 'foo'" in result.user_message

    def test_user_error_from_exposed_hogql_error_surfaces_its_message(self) -> None:
        exc = ExposedHogQLError("Alert filter has an invalid property")
        with _with_category(QueryErrorCategory.USER_ERROR):
            result = classify(exc)

        assert result.code == "invalid_query"
        assert result.user_message == "Alert filter has an invalid property"

    def test_user_error_from_internal_ch_error_falls_back_to_unknown(self) -> None:
        # USER_ERROR-category codes that aren't marked user_safe get wrapped as raw
        # InternalCHQueryError — the message still contains DB::Exception framing,
        # so we must not surface it.
        exc = InternalCHQueryError(
            "Code: 62. DB::Exception: Syntax error near token 'from' at position 412 (Stack trace: ...)",
            code=62,
        )
        with _with_category(QueryErrorCategory.USER_ERROR):
            result = classify(exc)

        assert result.code == "unknown"
        assert "DB::Exception" not in result.user_message
        assert "Syntax error" not in result.user_message
        assert "PostHog" in result.user_message

    def test_user_error_message_is_truncated(self) -> None:
        exc = ExposedCHQueryError("x" * 5000, code=47)
        with _with_category(QueryErrorCategory.USER_ERROR):
            result = classify(exc)

        assert len(result.user_message) == 500

    def test_unknown_message_mentions_posthog(self) -> None:
        with _with_category(QueryErrorCategory.ERROR):
            result = classify(RuntimeError("something unexpected"))

        assert "PostHog" in result.user_message


class TestIsTransient(TestCase):
    @parameterized.expand(
        [
            (QueryErrorCategory.RATE_LIMITED, True),
            (QueryErrorCategory.CANCELLED, True),
            (QueryErrorCategory.ERROR, True),
            (QueryErrorCategory.QUERY_PERFORMANCE_ERROR, False),
        ]
    )
    def test_is_transient_matches_transient_error_codes(self, category: QueryErrorCategory, expected: bool) -> None:
        with _with_category(category):
            result = classify(Exception("whatever"))
        assert result.is_transient is expected

    def test_is_transient_false_for_invalid_query(self) -> None:
        exc = ExposedCHQueryError("Unknown identifier", code=47)
        with _with_category(QueryErrorCategory.USER_ERROR):
            result = classify(exc)
        assert result.code == "invalid_query"
        assert result.is_transient is False

    def test_transient_error_codes_covers_all_transient_categories(self) -> None:
        transient_categories = {QueryErrorCategory.RATE_LIMITED, QueryErrorCategory.CANCELLED, QueryErrorCategory.ERROR}
        for category in transient_categories:
            with _with_category(category):
                result = classify(Exception("x"))
            assert result.code in TRANSIENT_ERROR_CODES, f"{category} should map to a transient code"
