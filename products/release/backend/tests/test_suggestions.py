from parameterized import parameterized

from products.release.backend.logic.suggestions import MAX_SEARCH_TERMS, rank, search_terms, terms
from products.release.backend.models import Release


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


def test_rank_weighs_a_release_s_own_words_above_its_linked_flags() -> None:
    newer_via_flag = Release(name="Payments", description="", feature_flag_ids=[7])
    older_by_name = Release(name="Checkout", description="", feature_flag_ids=[])
    unrelated = Release(name="Pricing", description="", feature_flag_ids=[8])

    ranked = rank(
        [newer_via_flag, older_by_name, unrelated],
        {"checkout", "redesign"},
        {7: {"checkout", "copy"}, 8: {"pricing"}},
    )

    assert [(release.name, matched) for release, matched in ranked] == [
        ("Checkout", ["checkout"]),
        ("Payments", ["checkout"]),
    ]
