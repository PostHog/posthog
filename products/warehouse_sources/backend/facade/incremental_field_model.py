"""Decision-model incremental field recommendations for this product's presentation layer."""

from products.warehouse_sources.backend.logic.incremental_field_model import (
    recommend_for_candidates,
    recommend_incremental_fields,
)

__all__ = ["recommend_for_candidates", "recommend_incremental_fields"]
