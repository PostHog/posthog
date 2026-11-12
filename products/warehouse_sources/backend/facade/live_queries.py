"""Live-query eligibility and access references for dual-mode schema rows."""

from products.warehouse_sources.backend.logic.live_queries import is_live_query_eligible, live_only_access_ref

__all__ = ["is_live_query_eligible", "live_only_access_ref"]
