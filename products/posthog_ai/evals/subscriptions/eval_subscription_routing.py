"""Subscription-vs-scout routing evals.

Proves the routing guidance in ``managing-subscriptions`` (and the scout skills)
behaves as intended when Max meets a recurring-delivery request:

* fixed, known metrics on a schedule become a dashboard/insight **subscription**;
* an ambiguous "set up a scout to post this dashboard daily" is steered to a
  subscription (confirming, not silently building a scout);
* a genuine open-ended-watching request is still allowed to become a **scout** —
  the routing does not over-correct into always-subscription.

One suite (one Braintrust experiment), three cases; scorers self-skip per case
via ``expected`` (see ``scorers.py``). The behavior under test is routing, not
completion — recommend-and-confirm is a valid outcome — so the judges pass on a
recommendation and the only hard tool-call assertion is the deterministic
"did not build a scout" guardrail.

To run:
    flox activate -- bash -c "set -a; source .env; set +a; \
      python -m products.posthog_ai.eval_harness.harness eval_subscription_routing"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.subscriptions.scorers import (
    NoScoutCreated,
    NoUnilateralSubscription,
    OffersInformedChoice,
    RespectedScoutRequest,
    RoutedToSubscription,
)

# A pinned dashboard in the seeded Hedgebox project (products/posthog_ai/evals/CLAUDE.md),
# so the agent can resolve it by name without a seeder.
DASHBOARD_NAME = "🔑 Key metrics"


async def eval_subscription_routing(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        # Fixed metrics, fully-specified delivery → dashboard subscription, no scout.
        # Channel + address + cadence are all given, so the agent has everything it
        # needs to route (and can create outright or confirm first).
        SandboxedEvalCase(
            name="explicit_dashboard_subscription",
            prompt=(
                f"Email me a daily snapshot of the '{DASHBOARD_NAME}' dashboard at paul@example.com every morning."
            ),
            expected={"routed_to_subscription": True, "no_scout_created": True},
        ),
        # The user says "scout" but describes fixed dashboard numbers on a schedule —
        # genuinely ambiguous. Right move: explain the subscription-vs-scout tradeoff
        # and ask which they want, rather than silently picking either. Must still not
        # build a scout while asking.
        SandboxedEvalCase(
            name="ambiguous_scout_phrasing",
            prompt=(
                f"Set up a scout to post the numbers from our '{DASHBOARD_NAME}' dashboard "
                f"to the team in Slack every morning."
            ),
            expected={
                "offers_informed_choice": True,
                "no_scout_created": True,
                "no_unilateral_subscription": True,
            },
        ),
        # Genuine open-ended watching, user is explicit about wanting a scout →
        # respect it. Guards against the routing guidance over-correcting into a
        # subscription against the user's stated intent.
        SandboxedEvalCase(
            name="genuine_scout_watching",
            prompt=(
                "I want a scout to keep an eye on our web analytics and flag anything "
                "unusual or worth a look. Can you set that up?"
            ),
            expected={"respected_scout_request": True},
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-subscription-routing-cli",
        cases=cases,
        scorers=[
            RoutedToSubscription(),
            OffersInformedChoice(),
            NoScoutCreated(),
            NoUnilateralSubscription(),
            RespectedScoutRequest(),
        ],
        ctx=ctx,
    )
