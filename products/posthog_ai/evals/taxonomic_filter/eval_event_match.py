"""Does the decision model find the core event a person describes when no event name matches their search?

The unit tests in `posthog/taxonomic_search_intent/test_event_match.py` feed the matcher canned answers. They
cover the value rules, the request chunks, the ingested-event check and the cache, and they pass whatever the
model says. This suite covers the model itself: given a search that matched no event name, does it pick the
core events the search describes, and nothing else?

The cases are invented from the shapes people type when they do not know an event's name: a description of
what the event records ("browser capture"), a synonym ("page visit"), a feeling ("angry clicks"). The no-match
cases are business events that no core event covers, where any suggestion is wrong.

`EventMatchFound` reads as recall and `NoWrongEventMatch` as precision. Precision is the number to protect,
because a wrong suggestion is worse than none. `MATCH_THRESHOLD` in `posthog/taxonomic_search_intent/event_match.py`
decides what the picker shows; tune it from this suite.

The suite scores the model's likely events before the ingested-event check, so the demo project's own events
do not change the result. It shows at most `MAX_MATCHES` events, like the picker.

No CI job runs this suite. Run it by hand, with AI_GATEWAY_URL and AI_GATEWAY_API_KEY set for the decision
model, and with the harness's own BRAINTRUST_API_KEY and LLM_GATEWAY_ANTHROPIC_API_KEY:
    hogli evals eval_event_match
"""

from __future__ import annotations

import time
import asyncio

from posthog.llm.system_one_client import system_one_configured
from posthog.taxonomic_search_intent.classify import SEARCH_INTENT_MODEL
from posthog.taxonomic_search_intent.event_match import MAX_MATCHES, likely_core_events

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPublicEval
from products.posthog_ai.evals.taxonomic_filter.scorers import EVENT_MATCH_KEY, EventMatchFound, NoWrongEventMatch

SUITE_KIND = SuiteKind.ONE_SHOT


def _case(name: str, query: str, *acceptable: str) -> BaseEvalCase:
    return BaseEvalCase(name=name, prompt=query, expected={EVENT_MATCH_KEY: {"acceptable": list(acceptable)}})


DESCRIBED_CASES = [
    _case("browser_capture", "browser capture", "$autocapture"),
    _case("automatic_clicks", "automatic clicks", "$autocapture"),
    _case("page_visit", "page visit", "$pageview"),
    _case("left_the_page", "left the page", "$pageleave"),
    _case("angry_clicks", "angry clicks", "$rageclick"),
    _case("clicks_that_do_nothing", "clicks that do nothing", "$dead_click"),
    _case("js_error", "js error", "$exception"),
    _case("app_screen", "app screen view", "$screen"),
    _case("page_speed", "page speed", "$web_vitals"),
    _case("llm_call", "llm call", "$ai_generation"),
    _case("copied_text", "copied text", "$copy_autocapture"),
]

NO_MATCH_CASES = [
    _case("invoice_paid", "invoice paid"),
    _case("subscription_upgraded", "subscription upgraded"),
    _case("file_shared", "file shared"),
]


async def eval_event_match(ctx: EvalContext) -> None:
    # Without a gateway every case errors, which reads as a model regression instead of a setup gap.
    if not system_one_configured():
        raise RuntimeError(
            "eval_event_match needs AI_GATEWAY_URL (https) and AI_GATEWAY_API_KEY to reach the decision model"
        )

    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        if task_ctx.demo_data is None:
            raise RuntimeError("one-shot suites run against the master Hedgebox team")
        started = time.monotonic()
        try:
            # Sync and blocking on the gateway, so keep it off the event loop. No cache: every run asks the model.
            # A failed chunk leaves its events out, which would score as a model miss, so a partial answer is an error.
            likely = await asyncio.to_thread(
                likely_core_events,
                task_ctx.demo_data.master_team_id,
                case.prompt,
                use_cache=False,
                require_complete=True,
            )
        except Exception as error:
            return {"model": SEARCH_INTENT_MODEL, "suggested": [], "error": f"{type(error).__name__}: {error}"}
        suggested = [match.name for match in likely[:MAX_MATCHES]]
        return {
            "model": SEARCH_INTENT_MODEL,
            "suggested": suggested,
            "probabilities": {match.name: match.probability for match in likely[:MAX_MATCHES]},
            "latency_ms": round((time.monotonic() - started) * 1000),
            "last_message": f"{case.prompt!r}: {suggested}",
        }

    await OneShotPublicEval(
        experiment_name="taxonomic-filter-event-match",
        cases=[*DESCRIBED_CASES, *NO_MATCH_CASES],
        scorers=[EventMatchFound(), NoWrongEventMatch()],
        task=task,
        ctx=ctx,
    )
