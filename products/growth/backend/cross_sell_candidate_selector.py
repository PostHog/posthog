from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from posthog.schema import ProductItemCategory, ProductKey

from posthog.products import Products

# Base weights for high-value products.
# Analysis: https://us.posthog.com/project/2/notebooks/x3AWOfsm
BASE_PREFERENCE_WEIGHTS: dict[ProductKey, int] = {
    ProductKey.PRODUCT_ANALYTICS: 10,
    ProductKey.WEB_ANALYTICS: 6,
    ProductKey.SESSION_REPLAY: 6,
    ProductKey.FEATURE_FLAGS: 6,
    ProductKey.ERROR_TRACKING: 4,
}

LLM_ADJACENT_KEYS: list[ProductKey] = [
    ProductKey.LLM_ANALYTICS,
    ProductKey.LLM_EVALUATIONS,
    ProductKey.LLM_DATASETS,
    ProductKey.LLM_PROMPTS,
    ProductKey.LLM_CLUSTERS,
]

DEFAULT_IGNORED_CATEGORIES: set[ProductItemCategory] = {
    ProductItemCategory.TOOLS,
    ProductItemCategory.UNRELEASED,
}

SAME_CATEGORY_WEIGHT_BUMP = 2
LLM_ADJACENT_WEIGHT = 10


@dataclass
class CrossSellCandidateSelector:
    """
    Given product catalog metadata and user state, produces a weighted list
    of candidate product paths for cross-sell suggestions.

    Pure computation — no DB access. The caller
    (UserProductList.sync_cross_sell_products) handles querying enabled
    products and persisting results. Randomness is isolated to `pick`,
    which uses `np.random.choice` for weighted sampling without replacement.

    Algorithm overview
    ------------------
    The goal is to suggest products the user doesn't have yet, biased toward
    products that are likely to be useful given what they already use.

    **Step 1 — Build preference weights** (build_preference_weights)

    Every product starts with a default weight of 1. Three layers of boosts
    are applied on top, in order:

      a) Base preference weights: a handful of universally high-value products
         get static weights (e.g. Product analytics=10, Session replay=6).
         See BASE_PREFERENCE_WEIGHTS for the full list and the linked notebook
         for the analysis behind these numbers.

      b) LLM adjacent boost: if the user already has LLM Analytics enabled,
         all LLM-adjacent products (Evaluations, Datasets, Prompts, Clusters)
         are set to weight 10, because they're most useful together.

      c) Same-category bump: for every category the user already has a product
         in, all *other* products in that category get +2. This makes the
         selection favor expanding within a familiar area.

    **Step 2 — Build the candidate set** (build_candidates)

    Candidates are chosen in two tiers:

      Tier 1 (narrow): products from the same categories the user already
      uses, plus all "favored" products (those that received a base preference
      weight in step 1a). Both are filtered to exclude user_excluded_products
      (which includes dismissed/disabled products, not just enabled ones) and
      any ignored categories (Tools, Unreleased by default).

      Tier 2 (fallback): if tier 1 is empty — e.g. the user already has
      every favored and same-category product — we expand to all products
      outside ignored categories that the user doesn't have yet.

    **Step 3 — Combine** (_get_weighted_candidates)

    Returns the candidate set paired with their weights as
    list[tuple[str, int]], ready to be passed to random.choices by the caller.
    """

    # Products the user actively has enabled — drives category weighting and LLM boost.
    user_enabled_products: set[str]
    ignored_categories: set[ProductItemCategory]
    # Products to exclude from the candidate pool. Superset of user_enabled_products:
    # includes dismissed (enabled=False) rows so we don't re-suggest them.
    # Defaults to user_enabled_products when not provided.
    user_excluded_products: set[str] = field(default_factory=set)

    # Derived lookups, built from Products singleton in __post_init__
    products_by_category: dict[ProductItemCategory, list[str]] = field(init=False, repr=False)
    product_to_category: dict[str, ProductItemCategory] = field(init=False, repr=False)
    intent_to_paths: dict[ProductKey, list[str]] = field(init=False, repr=False)
    user_enabled_categories: set[ProductItemCategory] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.user_excluded_products:
            self.user_excluded_products = self.user_enabled_products

        self.products_by_category = Products.get_products_by_category()

        self.product_to_category = {}
        self.intent_to_paths = defaultdict(list)
        for product in Products.products():
            if product.category:
                self.product_to_category[product.path] = product.category
            for intent in product.intents:
                self.intent_to_paths[intent].append(product.path)

        self.user_enabled_categories = {
            category
            for path in self.user_enabled_products
            if (category := self.product_to_category.get(path)) is not None
        } - self.ignored_categories

    def _resolve_paths(self, key: ProductKey) -> list[str]:
        return self.intent_to_paths.get(key, [])

    def _build_preference_weights(self) -> defaultdict[str, int]:
        """
        Build a weight map (product_path → int) that controls how likely
        each product is to be selected.

        Three layers, applied in order:
        1. Base weights for universally high-value products
        2. Contextual boost when the user already uses LLM Analytics
        3. +2 bump for products in the same category as the user's enabled products
        """
        weights: defaultdict[str, int] = defaultdict(lambda: 1)

        for key, weight in BASE_PREFERENCE_WEIGHTS.items():
            for path in self._resolve_paths(key):
                weights[path] = weight

        self._apply_llm_adjacent_boost(weights)
        self._apply_same_category_boost(weights)
        return weights

    def _apply_llm_adjacent_boost(self, weights: defaultdict[str, int]) -> None:
        llm_analytics_paths = self._resolve_paths(ProductKey.LLM_ANALYTICS)
        if not any(p in self.user_enabled_products for p in llm_analytics_paths):
            return

        for key in LLM_ADJACENT_KEYS:
            for path in self._resolve_paths(key):
                weights[path] = LLM_ADJACENT_WEIGHT

    def _apply_same_category_boost(self, weights: defaultdict[str, int]) -> None:
        for category in self.user_enabled_categories:
            for path in self.products_by_category.get(category, []):
                if path not in self.user_enabled_products:
                    weights[path] += SAME_CATEGORY_WEIGHT_BUMP

    def _build_candidates(self, preference_weights: defaultdict[str, int]) -> set[str]:
        """
        Build the candidate set in two tiers:

        1. Same-category products (where user already has something) + favored products
           (those with explicit preference weights), both filtered by ignored categories.
        2. Fallback: all products outside ignored categories, if tier 1 is empty.
        """
        same_category = {
            product.path
            for product in Products.products()
            if product.path not in self.user_excluded_products
            and (category := self.product_to_category.get(product.path)) is not None
            and category in self.user_enabled_categories
            and category not in self.ignored_categories
        }

        favored = {
            path
            for path in set(preference_weights.keys()) - self.user_excluded_products
            if self.product_to_category.get(path) not in self.ignored_categories
        }

        candidates = same_category | favored
        if candidates:
            return candidates

        return {
            product.path
            for product in Products.products()
            if product.path not in self.user_excluded_products
            and self.product_to_category.get(product.path) not in self.ignored_categories
        }

    def _get_weighted_candidates(self) -> list[tuple[str, int]]:
        """
        Returns a list of (product_path, weight) pairs for all eligible candidates.
        Useful for inspection/testing without introducing randomness.
        """
        weights = self._build_preference_weights()
        candidates = self._build_candidates(weights)
        return [(path, weights[path]) for path in candidates]

    def pick(self, k: int = 1) -> list[str]:
        """
        Main entry point. Selects up to k product paths via weighted random
        sampling from the candidate set. Returns an empty list when there
        are no eligible candidates.
        """
        weighted = self._get_weighted_candidates()
        if not weighted:
            return []

        paths, weights = zip(*weighted)

        # From a list of weights to a normalized [0, 1] probability distribution
        prob_distribution = np.array(weights) / sum(weights)
        return list(np.random.choice(list(paths), min(k, len(paths)), replace=False, p=prob_distribution))
