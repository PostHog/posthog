from parameterized import parameterized

from products.release.backend.logic.suggestions import MAX_SEARCH_TERMS, search_terms, terms


@parameterized.expand(
    [
        ("kebab_key", ("checkout-redesign-button",), {"checkout", "redesign", "button"}),
        ("camel_case", ("newCheckoutFlow",), {"checkout", "flow"}),
        ("generic_and_short_words", ("enable the beta flag for v2 pay",), {"pay"}),
        ("digits", ("checkout 2026",), {"checkout"}),
    ]
)
def test_terms(_name: str, texts: tuple[str, ...], expected: set[str]) -> None:
    assert terms(*texts) == expected


def test_search_terms_keep_the_key_first_and_stop_at_the_cap() -> None:
    description = " ".join(f"word{index:05d}x" for index in range(20_000))

    found = search_terms("checkout-redesign", description)

    assert len(found) == MAX_SEARCH_TERMS
    assert {"checkout", "redesign"} <= found
