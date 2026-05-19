"""End-to-end smoke test for the MCP session intent summary activity.

Runs the same code path the Temporal activity uses:
  Postgres pick -> ClickHouse fetch -> OpenAI -> Postgres update.

Requires OPENAI_API_KEY to be set in the environment.

Usage:
  flox activate -- python scripts/validate_mcp_intent_summary.py
"""

import os
import sys
import asyncio

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()


async def main() -> None:
    from asgiref.sync import sync_to_async

    from posthog.temporal.mcp_analytics.summarize_session_intents.activities import summarize_mcp_session_intents
    from posthog.temporal.mcp_analytics.summarize_session_intents.types import SummarizeMCPSessionIntentsInput

    from products.mcp_analytics.backend.models import MCPSession

    pending_before = await sync_to_async(MCPSession.objects.unscoped().filter(intent__isnull=True).count)()
    sys.stdout.write(f"Sessions awaiting intent BEFORE: {pending_before}\n")

    if not os.environ.get("OPENAI_API_KEY"):
        sys.stdout.write("OPENAI_API_KEY is not set; activity will mark sessions without intents only.\n")

    await summarize_mcp_session_intents(SummarizeMCPSessionIntentsInput(batch_size=5))

    pending_after = await sync_to_async(MCPSession.objects.unscoped().filter(intent__isnull=True).count)()
    sys.stdout.write(f"Sessions awaiting intent AFTER:  {pending_after}\n")

    sys.stdout.write("\nMost recent summaries:\n")
    rows = await sync_to_async(
        lambda: list(MCPSession.objects.unscoped().filter(intent__isnull=False).order_by("-updated_at")[:5])
    )()
    for row in rows:
        sys.stdout.write(f"  {row.session_id[:24]}\n    {row.intent}\n")


if __name__ == "__main__":
    asyncio.run(main())
