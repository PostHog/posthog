"""
Team-state wiring for managed_warehouse.

Re-exports the ``team_state`` **module object** rather than its functions: callers
resolve ``team_state.<fn>`` at call time, and tests patch those attributes on the
source module. Binding the functions here instead would freeze a copy that patches
never reach.
"""

from products.managed_warehouse.backend import team_state

__all__ = ["team_state"]
