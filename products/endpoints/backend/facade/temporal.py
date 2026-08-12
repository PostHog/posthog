"""
Temporal wiring for endpoints.

Re-exports the hooks the data-modeling Temporal workflow calls around
endpoint-backed saved queries: rebuilding the executable HogQL before each
materialization run, and updating the materialization-readiness cache on
completion/failure. Heavy imports (HogQL) ride along, same as the direct
imports they replace — keep this module off config-only import paths.
"""

from products.endpoints.backend.logic.materialization import prepare_executable_query
from products.endpoints.backend.rate_limit import update_materialization_ready_for_saved_query

__all__ = ["prepare_executable_query", "update_materialization_ready_for_saved_query"]
