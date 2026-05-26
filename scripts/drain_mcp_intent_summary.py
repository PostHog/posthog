"""Drain all NULL-intent MCPSession rows by repeatedly invoking the summary activity.

Loops the activity until no rows are pending, capped at MAX_ITERATIONS for safety.

Usage:
  flox activate -- python scripts/drain_mcp_intent_summary.py
"""

import os
import sys
import asyncio

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

MAX_ITERATIONS = 10
BATCH_SIZE = 25


async def main() -> None:
    from asgiref.sync import sync_to_async

    from posthog.temporal.mcp_analytics.summarize_session_intents.activities import summarize_mcp_session_intents
    from posthog.temporal.mcp_analytics.summarize_session_intents.types import SummarizeMCPSessionIntentsInput

    from products.mcp_analytics.backend.models import MCPSession

    pending_count = await sync_to_async(MCPSession.objects.unscoped().filter(intent__isnull=True).count)()
    sys.stdout.write(f"Sessions pending intent: {pending_count}\n")

    for iteration in range(MAX_ITERATIONS):
        if pending_count == 0:
            break
        sys.stdout.write(f"\nIteration {iteration + 1}: summarising up to {BATCH_SIZE} sessions...\n")
        await summarize_mcp_session_intents(SummarizeMCPSessionIntentsInput(batch_size=BATCH_SIZE))
        new_pending = await sync_to_async(MCPSession.objects.unscoped().filter(intent__isnull=True).count)()
        sys.stdout.write(f"  pending after: {new_pending}\n")
        if new_pending >= pending_count:
            sys.stdout.write("  No progress made; stopping to avoid infinite loop.\n")
            break
        pending_count = new_pending

    final_pending = await sync_to_async(MCPSession.objects.unscoped().filter(intent__isnull=True).count)()
    total = await sync_to_async(MCPSession.objects.unscoped().count)()
    sys.stdout.write(f"\nDone. pending={final_pending} total={total}\n")


if __name__ == "__main__":
    asyncio.run(main())
