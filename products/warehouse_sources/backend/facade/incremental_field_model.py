"""Decision-model incremental field recommendations for this product's presentation layer."""

from products.warehouse_sources.backend.logic.incremental_field_model import (
    apply_stored_suggestion,
    recommend_for_candidates,
)

__all__ = ["apply_stored_suggestion", "recommend_for_candidates"]
