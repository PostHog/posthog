"""Quick local validation for the MCP sessions backfill activity.

Runs the same code path the Temporal activity uses, end-to-end:
  ClickHouse aggregate -> Postgres upsert.

Usage:
  flox activate -- python scripts/validate_mcp_backfill.py
"""

import os
import sys
import asyncio

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()


async def main() -> None:
    from asgiref.sync import sync_to_async

    from posthog.temporal.mcp_analytics.backfill_sessions.activities import aggregate_and_upsert_mcp_sessions
    from posthog.temporal.mcp_analytics.backfill_sessions.types import BackfillMCPSessionsInput

    from products.mcp_analytics.backend.models import MCPSession

    before = await sync_to_async(MCPSession.objects.unscoped().count)()
    sys.stdout.write(f"MCPSession rows BEFORE: {before}\n")

    await aggregate_and_upsert_mcp_sessions(BackfillMCPSessionsInput(lookback_hours=72))

    after = await sync_to_async(MCPSession.objects.unscoped().count)()
    sys.stdout.write(f"MCPSession rows AFTER:  {after}\n")
    sys.stdout.write(f"Delta: {after - before}\n")

    sys.stdout.write("\nFirst 5 rows:\n")
    rows = await sync_to_async(lambda: list(MCPSession.objects.unscoped().order_by("-session_end")[:5]))()
    for row in rows:
        sys.stdout.write(
            f"  team={row.team_id} session_id={row.session_id} "
            f"duration={row.duration_seconds}s tools={row.tools_used} "
            f"distinct_id={row.distinct_id!r} client={row.mcp_client_name!r}\n"
        )


if __name__ == "__main__":
    asyncio.run(main())
