"""Decision-model incremental field recommendations for this product's presentation layer."""

from products.warehouse_sources.backend.logic.incremental_field_model import (
    MAX_COLUMNS_PER_CALL,
    MAX_TABLES_PER_CALL,
    WIZARD_PATH,
    apply_stored_suggestion,
    fits_one_call,
    recommend_for_candidates,
)

__all__ = [
    "MAX_COLUMNS_PER_CALL",
    "MAX_TABLES_PER_CALL",
    "WIZARD_PATH",
    "apply_stored_suggestion",
    "fits_one_call",
    "recommend_for_candidates",
]
