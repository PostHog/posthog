"""
Control-plane team-listing wiring for managed_warehouse.

Re-exports the ``cp_teams`` **module object** for the same reason as
``facade.team_state``: callers (the duckling backfill sensor and its tests) reset its
cache and patch its fetch helper, both of which need live attribute lookup on the
source module.
"""

from products.managed_warehouse.backend import cp_teams
from products.managed_warehouse.backend.cp_teams import CPTeam

__all__ = ["CPTeam", "cp_teams"]
