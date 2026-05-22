"""Inject synthetic intents on MCPSession rows for local clustering tests.

Bypasses OpenAI by picking from a curated pool of phrasings grouped into
themes. Use this when you want to validate the clustering pipeline at scale
without burning LLM credits.

Themes are intentionally redundant — multiple phrasings of "investigate a
checkout-failure spike", multiple phrasings of "confirm a flag rollout", etc.
— so clustering has clear signal to detect.

Usage:
  flox activate -- python scripts/inject_mcp_intents.py [--team-id N] [--seed N]
"""

import os
import sys
import random
import argparse
from pathlib import Path

# Allow `python scripts/inject_mcp_intents.py` from the repo root without
# requiring PYTHONPATH — django.setup() needs the posthog package on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

# Each list is a cluster theme. Variants share semantic meaning so the embedding
# space groups them together, but lexical phrasing differs so the cluster has
# non-trivial intra-cluster variance — closer to real LLM output.
INTENT_THEMES: list[list[str]] = [
    [
        "Investigate yesterday's spike in checkout failures using revenue and error events.",
        "Drill into the unusual jump in failed checkouts that started last night.",
        "Diagnose the checkout-error surge by correlating revenue and exception events.",
        "Triage the increase in checkout failures by pulling related error tracking issues.",
        "Look into the overnight checkout-error spike and identify the affected segments.",
    ],
    [
        "Pull funnel conversion numbers for the new pricing page for the weekly product review.",
        "Compare pricing-page funnel performance week over week ahead of the product review.",
        "Summarise the pricing-page conversion funnel for the leadership update.",
        "Build a funnel from pricing-page view to checkout to assess the new layout.",
    ],
    [
        "Check whether the new pricing feature flag is fully rolled out to the affected cohort.",
        "Confirm the rollout percentage of the pricing flag for a support escalation.",
        "Verify the new pricing flag is enabled for the customer who reported the issue.",
        "Audit the pricing feature flag's targeting rules after a complaint.",
    ],
    [
        "Review the active pricing experiment and decide whether we have the power to call a winner.",
        "Check the statistical significance of the current pricing experiment results.",
        "Decide whether to ship the winning variant of the pricing A/B test this week.",
    ],
    [
        "Pull active users metrics to share growth trends in the leadership Slack channel.",
        "Compile weekly active user counts for the growth update.",
        "Generate a DAU/WAU/MAU summary to post in the leadership channel.",
    ],
    [
        "Compare last cohort's retention curve to the previous one for the product review.",
        "Pull the 7-day retention chart for the latest signup cohort.",
        "Analyse retention drop-off for the most recent product launch.",
    ],
    [
        "Triage user-reported latency complaints from this morning using the platform health dashboard.",
        "Open the platform health dashboard to investigate API latency reports.",
        "Diagnose this morning's slowness complaints by reviewing the health dashboard.",
    ],
    [
        "Look up the reporter of a paid plan billing complaint before processing a refund.",
        "Find the customer profile tied to the billing escalation for the refund decision.",
        "Resolve the billing-complaint identity by querying recent paid-plan events.",
    ],
    [
        "Replay the signup session where the user got stuck so we can file a precise bug report.",
        "Watch the session recording of the stuck-signup user to identify the friction point.",
        "Investigate the stuck-signup complaint via session replay.",
    ],
    [
        "Pull the latest exception issue tied to the deploy so on-call can triage the regression.",
        "Identify the new error-tracking issue linked to today's deploy.",
        "Investigate the deploy-related regression by inspecting the freshest exception.",
    ],
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--team-id",
        type=int,
        default=None,
        help="Only inject for this team (default: all teams).",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible output.")
    args = parser.parse_args()

    from products.mcp_analytics.backend.models import MCPSession

    qs = MCPSession.objects.unscoped().filter(intent__isnull=True)
    if args.team_id is not None:
        qs = qs.filter(team_id=args.team_id)

    pending = qs.count()
    if pending == 0:
        sys.stdout.write("No NULL-intent sessions to inject.\n")
        return

    rng = random.Random(args.seed)
    pool = [phrase for theme in INTENT_THEMES for phrase in theme]
    sys.stdout.write(
        f"Injecting intents into {pending} sessions from {len(pool)} phrasings across {len(INTENT_THEMES)} themes...\n"
    )

    # Iterate ids only so we don't hold the full queryset in memory; use update()
    # per row to skip ORM signals and stay fast on large batches.
    updated = 0
    for session_id in qs.values_list("id", flat=True):
        intent = rng.choice(pool)
        MCPSession.objects.unscoped().filter(id=session_id).update(intent=intent)
        updated += 1
        if updated % 100 == 0:
            sys.stdout.write(f"  {updated}/{pending}\n")

    sys.stdout.write(f"\nDone. injected={updated}\n")


if __name__ == "__main__":
    main()
