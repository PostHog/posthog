from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches


@parameterized.expand(
    [
        (
            "exact_case_match",
            "401 Client Error: Unauthorized for url: https://www.eventbriteapi.com/v3/users/me/organizations/",
            ["401 Client Error: Unauthorized for url: https://www.eventbriteapi.com"],
            True,
        ),
        (
            "vendor_returns_non_standard_reason_phrase_casing",
            "401 Client Error: UNAUTHORIZED for url: https://www.eventbriteapi.com/v3/users/me/organizations/",
            ["401 Client Error: Unauthorized for url: https://www.eventbriteapi.com"],
            True,
        ),
        (
            "no_pattern_matches",
            "500 Server Error: Internal Server Error for url: https://example.com",
            ["401 Client Error: Unauthorized for url: https://example.com"],
            False,
        ),
        (
            "empty_patterns",
            "any error message",
            [],
            False,
        ),
    ]
)
def test_error_message_matches(_name, error_msg, patterns, expected):
    assert error_message_matches(error_msg, patterns) is expected
