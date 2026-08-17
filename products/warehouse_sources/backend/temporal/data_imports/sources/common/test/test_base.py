from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    _BaseSource,
    error_message_matches,
)


class _DescriptionsOnlySource:
    def get_canonical_descriptions(self):
        return {"widgets": {"description": "A widget."}}


def test_table_prefix_hook_defaults_to_the_plain_descriptions() -> None:
    # Almost no source overrides this, so a default that dropped or emptied the descriptions
    # would silently strip curated docs from every one of them on the enrichment path.
    source = _DescriptionsOnlySource()

    result = _BaseSource.get_canonical_descriptions_for_table_prefix(source, "acme_")

    assert result == {"widgets": {"description": "A widget."}}


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
