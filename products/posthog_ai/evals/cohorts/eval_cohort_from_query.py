"""Cohort-from-query eval cases for the sandboxed agent.

Each case asks the agent to turn a SQL query or a product-analytics insight
into a static cohort. The agent should populate the cohort *from the query*
(``cohorts-create`` with ``is_static: true`` + ``query``, or a ``query`` set
via ``cohorts-partial-update``) rather than materializing the actor list and
looping ``cohorts-add-persons-to-static-cohort-partial-update`` over the UUIDs
— the batching path caps out on large sets and is the failure mode this guards.

Runs against the Hedgebox demo team, which already has persons and ``$pageview``
events, so no per-case seeding is needed: the scorers grade tool usage, not the
resulting cohort size.

To run::

    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_cohort_from_query"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import NoToolCall
from products.posthog_ai.evals.cohorts.scorers import (
    COHORTS_ADD_PERSONS_TOOL,
    CohortFromQueryUsed,
    QueryTargetsActorColumn,
)


async def eval_cohort_from_query(ctx: EvalContext) -> None:
    cases = [
        SandboxedEvalCase(
            name="cohort_from_sql_query",
            prompt=(
                "Create a static cohort called 'Power users (snapshot)' containing every person "
                "who has triggered more than 10 $pageview events. I already think of this as a SQL "
                "query — make it a one-time snapshot, not a dynamic cohort."
            ),
        ),
        SandboxedEvalCase(
            name="cohort_from_trends_insight",
            prompt=(
                "Save the people behind my pageview trend over the last 7 days as a static cohort "
                "named 'Active last 7 days' — i.e. everyone who did a $pageview in the last week. "
                "It should be a fixed snapshot."
            ),
        ),
        SandboxedEvalCase(
            name="cohort_from_large_query_no_batching",
            prompt=(
                "I have a SQL query that returns several hundred users (everyone who did a $pageview) "
                "and I want them all saved as a static cohort named 'Pageviewers snapshot'. Save the "
                "whole set as a one-time snapshot — do not add them one by one."
            ),
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cohorts-from-query-cli",
        cases=cases,
        scorers=[
            CohortFromQueryUsed(),
            QueryTargetsActorColumn(),
            NoToolCall(forbidden={COHORTS_ADD_PERSONS_TOOL}, name="no_uuid_batching"),
        ],
        ctx=ctx,
    )
