from django.test import TestCase

from hypothesis import (
    given,
    settings,
    strategies as st,
)

from posthog.schema import ProductItemCategory, ProductKey

from posthog.products import Products

from products.growth.backend.cross_sell_candidate_selector import (
    BASE_PREFERENCE_WEIGHTS,
    DEFAULT_IGNORED_CATEGORIES,
    LLM_ADJACENT_KEYS,
    LLM_ADJACENT_WEIGHT,
    SAME_CATEGORY_WEIGHT_BUMP,
    CrossSellCandidateSelector,
)

ALL_PRODUCT_PATHS = sorted(set(Products.get_product_paths()))
ALL_CATEGORIES = list(ProductItemCategory)
PRODUCTS_BY_CATEGORY = Products.get_products_by_category()

# Hypothesis strategies
product_paths_st = st.frozensets(st.sampled_from(ALL_PRODUCT_PATHS))
categories_st = st.frozensets(st.sampled_from(ALL_CATEGORIES))


def _make_selector(
    enabled: set[str] | None = None,
    ignored: set[ProductItemCategory] | None = None,
    excluded: set[str] | None = None,
) -> CrossSellCandidateSelector:
    return CrossSellCandidateSelector(
        user_enabled_products=enabled or set(),
        ignored_categories=ignored if ignored is not None else DEFAULT_IGNORED_CATEGORIES,
        user_excluded_products=excluded or set(),
    )


class TestCrossSellCandidateSelectorPreferenceWeights(TestCase):
    def test_base_weights_are_applied(self):
        selector = _make_selector()
        weights = selector._build_preference_weights()

        for key, expected_weight in BASE_PREFERENCE_WEIGHTS.items():
            paths = selector.intent_to_paths.get(key, [])
            assert len(paths) > 0, f"ProductKey {key} should resolve to at least one product path"
            for path in paths:
                assert weights[path] == expected_weight, (
                    f"Expected weight {expected_weight} for {path}, got {weights[path]}"
                )

    def test_non_favored_products_get_default_weight(self):
        selector = _make_selector()
        weights = selector._build_preference_weights()

        favored_paths = {p for k in BASE_PREFERENCE_WEIGHTS for p in selector.intent_to_paths.get(k, [])}
        for product in Products.products():
            if product.path not in favored_paths:
                assert weights[product.path] == 1, f"Non-favored product {product.path} should have weight 1"

    def test_llm_adjacent_boost_when_llm_analytics_enabled(self):
        selector_for_lookup = _make_selector()
        llm_paths = selector_for_lookup.intent_to_paths.get(ProductKey.LLM_ANALYTICS, [])
        assert len(llm_paths) > 0

        selector = _make_selector(enabled=set(llm_paths))
        weights = selector._build_preference_weights()

        for key in LLM_ADJACENT_KEYS:
            for path in selector.intent_to_paths.get(key, []):
                # Weight is at least LLM_ADJACENT_WEIGHT, possibly higher if same-category boost stacks
                assert weights[path] >= LLM_ADJACENT_WEIGHT, (
                    f"LLM adjacent product {path} should have weight >= {LLM_ADJACENT_WEIGHT}, got {weights[path]}"
                )

    def test_no_llm_boost_when_llm_analytics_not_enabled(self):
        selector = _make_selector()
        weights = selector._build_preference_weights()

        for key in LLM_ADJACENT_KEYS:
            for path in selector.intent_to_paths.get(key, []):
                if key not in BASE_PREFERENCE_WEIGHTS:
                    assert weights[path] != LLM_ADJACENT_WEIGHT, (
                        f"LLM adjacent product {path} should NOT have boosted weight when LLM Analytics is not enabled"
                    )

    def test_same_category_boost(self):
        selector_for_lookup = _make_selector()
        pa_paths = selector_for_lookup.intent_to_paths.get(ProductKey.PRODUCT_ANALYTICS, [])
        assert len(pa_paths) > 0
        pa_path = pa_paths[0]

        selector = _make_selector(enabled={pa_path})
        weights = selector._build_preference_weights()

        # Build a reverse map: path -> base weight (if it's a favored product)
        favored_path_to_weight: dict[str, int] = {}
        for key, w in BASE_PREFERENCE_WEIGHTS.items():
            for path in selector.intent_to_paths.get(key, []):
                favored_path_to_weight[path] = w

        analytics_products = set(selector.products_by_category.get(ProductItemCategory.ANALYTICS, []))
        for path in analytics_products - {pa_path}:
            base = favored_path_to_weight.get(path, 1)
            assert weights[path] == base + SAME_CATEGORY_WEIGHT_BUMP, (
                f"Same-category product {path} should have weight {base + SAME_CATEGORY_WEIGHT_BUMP}, got {weights[path]}"
            )


class TestCrossSellCandidateSelectorCandidates(TestCase):
    def test_same_category_products_are_candidates(self):
        selector_for_lookup = _make_selector()
        pa_paths = selector_for_lookup.intent_to_paths.get(ProductKey.PRODUCT_ANALYTICS, [])
        assert len(pa_paths) > 0
        pa_path = pa_paths[0]

        selector = _make_selector(enabled={pa_path})
        weights = selector._build_preference_weights()
        candidates = selector._build_candidates(weights)

        analytics_products = set(selector.products_by_category.get(ProductItemCategory.ANALYTICS, []))
        same_category_not_enabled = analytics_products - {pa_path}

        assert same_category_not_enabled <= candidates, (
            f"Same-category products should be candidates: missing {same_category_not_enabled - candidates}"
        )

    def test_favored_products_are_candidates(self):
        selector = _make_selector()
        weights = selector._build_preference_weights()
        candidates = selector._build_candidates(weights)

        for key in BASE_PREFERENCE_WEIGHTS:
            for path in selector.intent_to_paths.get(key, []):
                if selector.product_to_category.get(path) not in DEFAULT_IGNORED_CATEGORIES:
                    assert path in candidates, f"Favored product {path} should be a candidate"

    def test_enabled_products_excluded_from_candidates(self):
        selector_for_lookup = _make_selector()
        pa_path = selector_for_lookup.intent_to_paths.get(ProductKey.PRODUCT_ANALYTICS, [])[0]
        sr_path = selector_for_lookup.intent_to_paths.get(ProductKey.SESSION_REPLAY, [])[0]
        assert pa_path and sr_path

        selector = _make_selector(enabled={pa_path, sr_path})
        weights = selector._build_preference_weights()
        candidates = selector._build_candidates(weights)

        assert pa_path not in candidates
        assert sr_path not in candidates

    def test_dismissed_products_excluded_from_candidates(self):
        selector_for_lookup = _make_selector()
        pa_path = selector_for_lookup.intent_to_paths.get(ProductKey.PRODUCT_ANALYTICS, [])[0]
        sr_path = selector_for_lookup.intent_to_paths.get(ProductKey.SESSION_REPLAY, [])[0]
        ff_path = selector_for_lookup.intent_to_paths.get(ProductKey.FEATURE_FLAGS, [])[0]
        assert pa_path and sr_path and ff_path

        # pa is enabled, sr is dismissed (excluded but not enabled), ff is not in the system
        selector = _make_selector(enabled={pa_path}, excluded={pa_path, sr_path})
        weights = selector._build_preference_weights()
        candidates = selector._build_candidates(weights)

        assert pa_path not in candidates, "Enabled product should not be a candidate"
        assert sr_path not in candidates, "Dismissed product should not be a candidate"
        assert ff_path in candidates, "Product not in system should be a candidate"

    def test_dismissed_products_do_not_influence_category_weights(self):
        selector_for_lookup = _make_selector()
        sr_path = selector_for_lookup.intent_to_paths.get(ProductKey.SESSION_REPLAY, [])[0]
        assert sr_path is not None

        # sr is dismissed — its category (Behavior) should NOT get the same-category boost
        selector_with_dismissed = _make_selector(enabled=set(), excluded={sr_path})
        weights_dismissed = selector_with_dismissed._build_preference_weights()

        selector_with_enabled = _make_selector(enabled={sr_path})
        weights_enabled = selector_with_enabled._build_preference_weights()

        sr_category = selector_for_lookup.product_to_category.get(sr_path)
        assert sr_category is not None
        sibling_paths = set(selector_for_lookup.products_by_category.get(sr_category, [])) - {sr_path}

        for path in sibling_paths:
            assert weights_dismissed[path] < weights_enabled[path], (
                f"Dismissed product's category should not boost {path}"
            )

    def test_ignored_categories_excluded_from_candidates(self):
        selector_for_lookup = _make_selector()
        pa_path = selector_for_lookup.intent_to_paths.get(ProductKey.PRODUCT_ANALYTICS, [])[0]
        assert pa_path is not None

        selector = _make_selector(enabled={pa_path}, ignored={ProductItemCategory.ANALYTICS})
        weights = selector._build_preference_weights()
        candidates = selector._build_candidates(weights)

        analytics_products = set(selector.products_by_category.get(ProductItemCategory.ANALYTICS, []))
        assert not candidates & analytics_products, (
            "Analytics products should not be candidates when Analytics is ignored"
        )

    def test_fallback_when_no_primary_candidates(self):
        products_by_category = Products.get_products_by_category()
        analytics_products = set(products_by_category.get(ProductItemCategory.ANALYTICS, []))

        lookup_selector = _make_selector()
        favored_paths = {p for k in BASE_PREFERENCE_WEIGHTS for p in lookup_selector.intent_to_paths.get(k, [])}

        enabled = analytics_products | favored_paths
        selector = _make_selector(enabled=enabled)
        weights = selector._build_preference_weights()
        candidates = selector._build_candidates(weights)

        tools_products = set(products_by_category.get(ProductItemCategory.TOOLS, []))
        unreleased_products = set(products_by_category.get(ProductItemCategory.UNRELEASED, []))

        assert len(candidates) > 0, "Fallback should produce candidates"
        assert not candidates & enabled, "Enabled products should not be in fallback candidates"
        assert not candidates & tools_products, "Tools should not be in fallback candidates"
        assert not candidates & unreleased_products, "Unreleased should not be in fallback candidates"

    def test_empty_candidates_when_all_products_enabled(self):
        selector = _make_selector(enabled=set(Products.get_product_paths()))
        assert selector._get_weighted_candidates() == []


class TestCrossSellCandidateSelectorGetWeightedCandidates(TestCase):
    def test_returns_tuples_of_path_and_weight(self):
        selector = _make_selector()
        weighted = selector._get_weighted_candidates()

        assert len(weighted) > 0
        for path, weight in weighted:
            assert isinstance(path, str)
            assert isinstance(weight, int)
            assert weight >= 1

    def test_all_paths_are_valid_products(self):
        all_paths = set(Products.get_product_paths())
        selector = _make_selector()
        weighted = selector._get_weighted_candidates()

        for path, _ in weighted:
            assert path in all_paths, f"{path} is not a valid product path"

    def test_weights_reflect_preference_weights(self):
        selector = _make_selector()
        weighted = selector._get_weighted_candidates()
        weight_map = dict(weighted)

        for key, expected_weight in BASE_PREFERENCE_WEIGHTS.items():
            for path in selector.intent_to_paths.get(key, []):
                if path in weight_map:
                    assert weight_map[path] == expected_weight, (
                        f"Expected {path} to have weight {expected_weight}, got {weight_map[path]}"
                    )


def _assert_selector_invariants(selector: CrossSellCandidateSelector) -> None:
    weighted = selector._get_weighted_candidates()
    candidate_paths = {path for path, _ in weighted}
    all_paths = set(ALL_PRODUCT_PATHS)

    assert not candidate_paths & selector.user_excluded_products, (
        f"Candidates include excluded products: {candidate_paths & selector.user_excluded_products}"
    )
    assert candidate_paths <= all_paths, f"Candidates include invalid paths: {candidate_paths - all_paths}"

    for cat in selector.ignored_categories:
        ignored_paths = set(PRODUCTS_BY_CATEGORY.get(cat, []))
        assert not candidate_paths & ignored_paths, (
            f"Candidates from ignored category {cat}: {candidate_paths & ignored_paths}"
        )

    for _, weight in weighted:
        assert weight >= 1


class TestCrossSellCandidateSelectorPropertyTests:
    @given(enabled=product_paths_st)
    @settings(max_examples=200, deadline=None)
    def test_invariants_across_random_states(self, enabled: frozenset[str]):
        selector = CrossSellCandidateSelector(
            user_enabled_products=set(enabled),
            ignored_categories=DEFAULT_IGNORED_CATEGORIES,
        )
        _assert_selector_invariants(selector)

    @given(enabled=product_paths_st, ignored=categories_st)
    @settings(max_examples=200, deadline=None)
    def test_invariants_with_random_ignored_categories(
        self, enabled: frozenset[str], ignored: frozenset[ProductItemCategory]
    ):
        selector = CrossSellCandidateSelector(
            user_enabled_products=set(enabled),
            ignored_categories=set(ignored),
        )
        _assert_selector_invariants(selector)

    @given(
        enabled=product_paths_st,
        dismissed=product_paths_st,
    )
    @settings(max_examples=200, deadline=None)
    def test_invariants_with_dismissed_products(self, enabled: frozenset[str], dismissed: frozenset[str]):
        selector = CrossSellCandidateSelector(
            user_enabled_products=set(enabled),
            ignored_categories=DEFAULT_IGNORED_CATEGORIES,
            user_excluded_products=set(enabled | dismissed),
        )
        _assert_selector_invariants(selector)

    @given(
        enabled=product_paths_st,
        dismissed=product_paths_st,
        ignored=categories_st,
    )
    @settings(max_examples=200, deadline=None)
    def test_invariants_all_dimensions(
        self,
        enabled: frozenset[str],
        dismissed: frozenset[str],
        ignored: frozenset[ProductItemCategory],
    ):
        selector = CrossSellCandidateSelector(
            user_enabled_products=set(enabled),
            ignored_categories=set(ignored),
            user_excluded_products=set(enabled | dismissed),
        )
        _assert_selector_invariants(selector)
