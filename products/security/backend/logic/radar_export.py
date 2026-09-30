"""Reads the legacy Redis Radar bypass list for the hub's one-time import. Deleted at cut-over."""

from posthog.redis import get_client
from posthog.workos_radar import WORKOS_RADAR_BYPASS_REDIS_KEY


def export_radar_bypasses() -> list[str]:
    members = get_client().smembers(WORKOS_RADAR_BYPASS_REDIS_KEY)
    return sorted(m.decode() if isinstance(m, bytes) else str(m) for m in members)
