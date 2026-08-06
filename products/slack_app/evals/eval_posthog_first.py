"""Does the Slack app answer "how do I set up X?" with PostHog's own product?

A customer asked the Slack app what they needed to set up PostHog's support
features and got pointed at third-party support tools instead. The agent has no
grounding step for product questions, so an ambiguous "how do I set up X" falls
through to whatever the model remembers about the category — and for every
capability PostHog sells, the model remembers competitors too.

Cases are the shape that fails: a short question about a capability PostHog
ships, with no explicit mention of PostHog's product name. Each runs with
``interaction_origin="slack"`` so the agent gets the real Slack system prompt
rather than the plain-task one.

Metrics:

* ``docs_searched`` — did the agent ground the answer in our docs at all?
* ``posthog_product_answer`` — is the answer about PostHog's own product?
* ``no_third_party_recommendation`` — does it avoid sending the customer to a competitor?

To run::

    hogli evals eval_posthog_first
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall
from products.slack_app.evals.scorers import (
    DOCS_SEARCH_TOOL_NAME,
    AnsweredAboutPostHogProduct,
    NoThirdPartyRecommendation,
)


async def eval_posthog_first(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="support_setup",
            prompt="what do I need to set up to start using the support features?",
            expected={"posthog_product_answer": {"capability": "customer support / a support inbox"}},
            interaction_origin="slack",
        ),
        SandboxedEvalCase(
            name="drip_emails",
            prompt=(
                "we want to email people who signed up but never uploaded a file, "
                "a couple of days after they sign up. how do we set that up?"
            ),
            expected={"posthog_product_answer": {"capability": "automated / drip email to users"}},
            interaction_origin="slack",
        ),
        SandboxedEvalCase(
            name="stripe_alongside_events",
            prompt="how do we get our Stripe billing data sitting next to our product data so we can join them?",
            expected={"posthog_product_answer": {"capability": "syncing an external source into a data warehouse"}},
            interaction_origin="slack",
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-slack-posthog-first-cli",
        cases=cases,
        scorers=[
            RequiredToolCall({DOCS_SEARCH_TOOL_NAME}, name="docs_searched"),
            AnsweredAboutPostHogProduct(),
            NoThirdPartyRecommendation(),
        ],
        ctx=ctx,
    )
