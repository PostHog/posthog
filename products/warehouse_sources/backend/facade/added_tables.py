"""
Access checks for a table added to an object storage source by its path.

A table added by path has no access rules of its own, so access to it falls back to its source. The API
refuses to add one when it could show a member files that the rules of another table hide from them.
"""

from products.warehouse_sources.backend.self_managed_access import added_table_access_refusal

__all__ = ["added_table_access_refusal"]
