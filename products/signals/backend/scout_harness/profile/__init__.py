"""Project profile aggregator — reads authoritative sources to build the inventory layer.

The package is intentionally separate from `scout_harness/tools/` because the aggregator
grows over time (Phase 7 layers deltas, activity_notes, and an LLM narrative on top of
inventory). Keeping it module-scoped lets the source-readers stay small and testable.
"""

from products.signals.backend.scout_harness.profile.builders import INVENTORY_SOURCE_VERSION, build_inventory
from products.signals.backend.scout_harness.profile.schema import Inventory

__all__ = ["INVENTORY_SOURCE_VERSION", "Inventory", "build_inventory"]
