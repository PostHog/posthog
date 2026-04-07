import random as random_module

from django.test import TestCase

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


def _make_selector(
    enabled: set[str] | None = None,
    ignored: set[ProductItemCategory] | None = None,
) -> CrossSellCandidateSelector:
    return CrossSellCandidateSelector(
        user_enabled_products=enabled or set(),
        ignored_categories=ignored if ignored is not None else DEFAULT_IGNORED_CATEGORIES,
    )


class TestCrossSellCandidateSelectorPreferenceWeights(TestCase):
    def test_base_weights_are_applied(self):
        selector = _make_selector()
        weights = selector._build_preference_weights()

        for key, expected_weight in BASE_PREFERENCE_WEIGHTS.items():
            path = selector.intent_to_path.get(key)
            assert path is not None, f"ProductKey {key} should resolve to a product path"
            assert weights[path] == expected_weight, (
                f"Expected weight {expected_weight} for {path}, got {weights[path]}"
            )

    def test_non_favored_products_get_default_weight(self):
        selector = _make_selector()
        weights = selector._build_preference_weights()

        favored_paths = {selector.intent_to_path[k] for k in BASE_PREFERENCE_WEIGHTS if k in selector.intent_to_path}
        for product in Products.products():
            if product.path not in favored_paths:
                assert weights[product.path] == 1, f"Non-favored product {product.path} should have weight 1"

    def test_llm_adjacent_boost_when_llm_analytics_enabled(self):
        selector_for_lookup = _make_selector()
        llm_path = selector_for_lookup.intent_to_path.get(ProductKey.LLM_ANALYTICS)
        assert llm_path is not None

        selector = _make_selector(enabled={llm_path})
        weights = selector._build_preference_weights()

        for key in LLM_ADJACENT_KEYS:
            path = selector.intent_to_path.get(key)
            if path:
                # Weight is at least LLM_ADJACENT_WEIGHT, possibly higher if same-category boost stacks
                assert weights[path] >= LLM_ADJACENT_WEIGHT, (
                    f"LLM adjacent product {path} should have weight >= {LLM_ADJACENT_WEIGHT}, got {weights[path]}"
                )

    def test_no_llm_boost_when_llm_analytics_not_enabled(self):
        selector = _make_selector()
        weights = selector._build_preference_weights()

        for key in LLM_ADJACENT_KEYS:
            path = selector.intent_to_path.get(key)
            if path and key not in BASE_PREFERENCE_WEIGHTS:
                assert weights[path] != LLM_ADJACENT_WEIGHT, (
                    f"LLM adjacent product {path} should NOT have boosted weight when LLM Analytics is not enabled"
                )

    def test_same_category_boost(self):
        selector_for_lookup = _make_selector()
        pa_path = selector_for_lookup.intent_to_path.get(ProductKey.PRODUCT_ANALYTICS)
        assert pa_path is not None

        selector = _make_selector(enabled={pa_path})
        weights = selector._build_preference_weights()

        # Build a reverse map: path -> base weight (if it's a favored product)
        favored_path_to_weight: dict[str, int] = {}
        for key, w in BASE_PREFERENCE_WEIGHTS.items():
            if path := selector.intent_to_path.get(key):
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
        pa_path = selector_for_lookup.intent_to_path.get(ProductKey.PRODUCT_ANALYTICS)
        assert pa_path is not None

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
            path = selector.intent_to_path.get(key)
            if path and selector.product_to_category.get(path) not in DEFAULT_IGNORED_CATEGORIES:
                assert path in candidates, f"Favored product {path} should be a candidate"

    def test_enabled_products_excluded_from_candidates(self):
        selector_for_lookup = _make_selector()
        pa_path = selector_for_lookup.intent_to_path.get(ProductKey.PRODUCT_ANALYTICS)
        sr_path = selector_for_lookup.intent_to_path.get(ProductKey.SESSION_REPLAY)
        assert pa_path and sr_path

        selector = _make_selector(enabled={pa_path, sr_path})
        weights = selector._build_preference_weights()
        candidates = selector._build_candidates(weights)

        assert pa_path not in candidates
        assert sr_path not in candidates

    def test_ignored_categories_excluded_from_candidates(self):
        selector_for_lookup = _make_selector()
        pa_path = selector_for_lookup.intent_to_path.get(ProductKey.PRODUCT_ANALYTICS)
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
        favored_paths = {
            lookup_selector.intent_to_path[k] for k in BASE_PREFERENCE_WEIGHTS if k in lookup_selector.intent_to_path
        }

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
            path = selector.intent_to_path.get(key)
            if path and path in weight_map:
                assert weight_map[path] == expected_weight, (
                    f"Expected {path} to have weight {expected_weight}, got {weight_map[path]}"
                )


class TestCrossSellCandidateSelectorPropertyTests(TestCase):
    """Property tests that exercise the selector with many random inputs."""

    def setUp(self):
        super().setUp()
        self.all_product_paths = sorted(set(Products.get_product_paths()))
        self.products_by_category = Products.get_products_by_category()

    def _assert_selector_invariants(
        self,
        selector: CrossSellCandidateSelector,
        trial_label: str,
    ) -> None:
        weighted = selector._get_weighted_candidates()
        candidate_paths = {path for path, _ in weighted}
        all_paths = set(self.all_product_paths)

        overlap = candidate_paths & selector.user_enabled_products
        assert not overlap, f"[{trial_label}] candidates include enabled products: {overlap}"

        invalid = candidate_paths - all_paths
        assert not invalid, f"[{trial_label}] candidates include invalid paths: {invalid}"

        for cat in selector.ignored_categories:
            ignored_paths = set(self.products_by_category.get(cat, []))
            leaked = candidate_paths & ignored_paths
            assert not leaked, f"[{trial_label}] candidates from ignored category {cat}: {leaked}"

        for _, weight in weighted:
            assert weight >= 1, f"[{trial_label}] weight must be >= 1"

    def test_invariants_across_random_states(self):
        rng = random_module.Random(42)

        for trial in range(200):
            num_enabled = rng.randint(0, min(10, len(self.all_product_paths)))
            enabled = set(rng.sample(self.all_product_paths, num_enabled))

            selector = CrossSellCandidateSelector(
                user_enabled_products=enabled,
                ignored_categories=DEFAULT_IGNORED_CATEGORIES,
            )
            self._assert_selector_invariants(selector, f"trial={trial}, enabled={num_enabled}")

    def test_invariants_with_random_ignored_categories(self):
        rng = random_module.Random(456)
        all_categories = list(ProductItemCategory)

        for trial in range(100):
            num_ignored = rng.randint(0, len(all_categories) - 1)
            ignored = set(rng.sample(all_categories, num_ignored))
            num_enabled = rng.randint(0, 5)
            enabled = set(rng.sample(self.all_product_paths, num_enabled))

            selector = CrossSellCandidateSelector(
                user_enabled_products=enabled,
                ignored_categories=ignored,
            )
            self._assert_selector_invariants(selector, f"trial={trial}, ignored={len(ignored)}, enabled={num_enabled}")

    def test_invariants_at_saturation(self):
        rng = random_module.Random(789)

        for trial in range(50):
            num_enabled = rng.randint(len(self.all_product_paths) - 5, len(self.all_product_paths))
            enabled = set(rng.sample(self.all_product_paths, num_enabled))

            selector = CrossSellCandidateSelector(
                user_enabled_products=enabled,
                ignored_categories=DEFAULT_IGNORED_CATEGORIES,
            )
            self._assert_selector_invariants(selector, f"trial={trial}, enabled={num_enabled}")
