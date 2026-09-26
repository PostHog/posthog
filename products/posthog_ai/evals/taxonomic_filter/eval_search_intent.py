"""Does the decision model read a filter picker search the way the person meant it?

The unit tests in `posthog/taxonomic_search_intent/test_classify.py` feed the classifier canned answers. They cover
the value patterns, the offered tabs, the cache and the switch rule, and they pass whatever the model
says. This suite covers the model itself: given a search, the open tab and the tabs the picker shows,
does it pick a tab that holds what the person typed?

The cases come from the shapes the picker's own telemetry shows, not from any person's search:

- Most searches are a few canonical words. `email` is nearly always a person property and `url` an
  event property, and both come back empty in the events tab and the wrong property tab.
- People type the start of a word (`em`, `ur`) and a switch suggestion is only useful that early.
- The same word means a different tab on a different page: flag targeting has no event properties.

`SwitchWhenNeeded` and `NoWrongSwitch` read as the recall and the precision of the banner variant.
Precision is the number to protect: a wrong suggestion is worse than none. The question, the tab
meanings and `confident_threshold` live in the managed `taxonomic-filter-search-intent` prompt
(see `posthog/taxonomic_search_intent/prompt.py`). Score a new version here before the `production`
label moves to it, and expect the baseline to step when the prompt or the model change.

Public rather than private: the value is the comparison across runs, and every case is synthetic.

No CI job runs this suite. Run it by hand, with AI_GATEWAY_URL and AI_GATEWAY_API_KEY set for the
decision model, and with the harness's own BRAINTRUST_API_KEY and LLM_GATEWAY_ANTHROPIC_API_KEY:
    hogli evals eval_search_intent
    hogli evals eval_search_intent --eval email_in_events_tab

It scores the `production` version of the managed prompt. Set SEARCH_INTENT_PROMPT_VERSION to score
another version. Fetching it needs POSTHOG_PERSONAL_API_KEY with read access to the PostHog project;
without it the suite scores the bundled copy, and the output reports `prompt_version: None`.
"""

from __future__ import annotations

import os
import time
import asyncio
import dataclasses

from posthog.llm.system_one_client import system_one_configured
from posthog.taxonomic_search_intent.classify import SEARCH_INTENT_MODEL, classify_search_intent
from posthog.taxonomic_search_intent.contracts import SearchIntentRequest
from posthog.taxonomic_search_intent.prompt import SEARCH_INTENT_PROMPT_LABEL, fetch_search_intent_prompt

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPublicEval
from products.posthog_ai.evals.taxonomic_filter.scorers import (
    SEARCH_INTENT_KEY,
    NoWrongSwitch,
    SearchIntentMatch,
    SwitchWhenNeeded,
)

SUITE_KIND = SuiteKind.ONE_SHOT

# The tab sets of the pickers people open most, so the model faces the choices it faces in production.
PROPERTY_FILTER = (
    "suggested_filters",
    "event_properties",
    "person_properties",
    "session_properties",
    "cohorts",
    "event_feature_flags",
    "elements",
    "pageview_urls",
    "email_addresses",
)
REPLAY_FILTER = ("suggested_filters", "events", "actions", *PROPERTY_FILTER[1:])
SERIES = ("suggested_filters", "events", "actions")
BREAKDOWN = ("event_properties", "person_properties", "session_properties", "event_feature_flags", "cohorts")
FLAG_TARGETING = ("person_properties", "cohorts", "feature_flags")


def _case(
    name: str,
    query: str,
    *,
    active: str,
    tabs: tuple[str, ...],
    acceptable: tuple[str, ...],
    scene: str = "Insight",
) -> BaseEvalCase:
    return BaseEvalCase(
        name=name,
        prompt=query,
        metadata={"active_group_type": active, "available_group_types": list(tabs), "scene": scene},
        expected={SEARCH_INTENT_KEY: {"active": active, "acceptable": list(acceptable)}},
    )


# The open tab cannot hold the answer. A banner helps here, and only here.
WRONG_TAB_CASES = [
    _case(
        "email_in_event_properties_tab",
        "email",
        active="event_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("person_properties",),
    ),
    _case(
        "email_in_events_tab",
        "email",
        active="events",
        tabs=REPLAY_FILTER,
        acceptable=("person_properties",),
        scene="Replay",
    ),
    _case(
        "url_in_person_properties_tab",
        "url",
        active="person_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("event_properties",),
    ),
    _case(
        "current_url_in_events_tab",
        "current url",
        active="events",
        tabs=REPLAY_FILTER,
        acceptable=("event_properties",),
        scene="Replay",
    ),
    _case(
        "utm_in_person_properties_tab",
        "utm_source",
        active="person_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("event_properties", "session_properties"),
    ),
    _case(
        "browser_in_person_properties_tab",
        "browser",
        active="person_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("event_properties",),
    ),
    _case(
        "plan_in_event_properties_tab",
        "subscription plan",
        active="event_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("person_properties",),
    ),
    _case(
        "session_length_in_event_properties_tab",
        "session duration",
        active="event_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("session_properties",),
    ),
    _case(
        "signup_in_event_properties_tab",
        "signed up",
        active="event_properties",
        tabs=REPLAY_FILTER,
        acceptable=("events",),
        scene="Replay",
    ),
    _case(
        "pageview_in_person_properties_tab",
        "pageview",
        active="person_properties",
        tabs=REPLAY_FILTER,
        acceptable=("events",),
        scene="Replay",
    ),
    _case(
        "cohort_name_in_person_properties_tab",
        "beta testers cohort",
        active="person_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("cohorts",),
    ),
    _case(
        "flag_in_event_properties_tab",
        "feature flag new-onboarding",
        active="event_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("event_feature_flags",),
    ),
    _case(
        "button_in_event_properties_tab",
        "sign up button",
        active="event_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("elements",),
    ),
]

# The open tab already holds the answer. The picker must stay quiet: any banner here is noise.
RIGHT_TAB_CASES = [
    _case(
        "email_in_person_properties_tab",
        "email",
        active="person_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("person_properties",),
    ),
    _case(
        "url_in_event_properties_tab",
        "url",
        active="event_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("event_properties",),
    ),
    # Country is on the event and on the person, and people pick either, so both count as right.
    _case(
        "country_in_event_properties_tab",
        "country",
        active="event_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("event_properties", "person_properties"),
    ),
    _case(
        "country_in_person_properties_tab",
        "country",
        active="person_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("event_properties", "person_properties"),
    ),
    _case("purchase_in_events_tab", "purchase", active="events", tabs=SERIES, acceptable=("events",)),
    _case(
        "company_in_person_properties_tab",
        "company name",
        active="person_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("person_properties",),
    ),
    _case(
        "channel_in_session_properties_tab",
        "channel type",
        active="session_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("session_properties",),
    ),
    _case(
        "path_in_breakdown_event_properties_tab",
        "path",
        active="event_properties",
        tabs=BREAKDOWN,
        acceptable=("event_properties",),
    ),
]

# The start of a word, a misspelling or another word for the same thing.
PARTIAL_CASES = [
    _case("email_prefix", "em", active="events", tabs=REPLAY_FILTER, acceptable=("person_properties",)),
    _case(
        "email_misspelled",
        "emial",
        active="event_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("person_properties",),
    ),
    _case(
        "email_hyphenated",
        "e-mail",
        active="events",
        tabs=REPLAY_FILTER,
        acceptable=("person_properties",),
        scene="Replay",
    ),
    _case(
        "url_prefix",
        "ur",
        active="person_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("event_properties",),
    ),
    _case(
        "page_address",
        "page address",
        active="person_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("event_properties",),
    ),
    _case("email_in_spanish", "correo", active="events", tabs=REPLAY_FILTER, acceptable=("person_properties",)),
]

# The page changes the answer: a flag's release conditions only target people.
CONTEXT_CASES = [
    _case(
        "email_in_flag_cohorts_tab",
        "email",
        active="cohorts",
        tabs=FLAG_TARGETING,
        acceptable=("person_properties",),
        scene="FeatureFlag",
    ),
    _case(
        "country_in_flag_targeting",
        "country",
        active="cohorts",
        tabs=FLAG_TARGETING,
        acceptable=("person_properties",),
        scene="FeatureFlag",
    ),
    _case(
        "entry_page_in_web_analytics",
        "entry page",
        active="event_properties",
        tabs=PROPERTY_FILTER,
        acceptable=("session_properties",),
        scene="WebAnalytics",
    ),
]


async def eval_search_intent(ctx: EvalContext) -> None:
    # Without a gateway every case errors and scores 0, which reads as a model regression instead of a setup gap.
    if not system_one_configured():
        raise RuntimeError(
            "eval_search_intent needs AI_GATEWAY_URL (https) and AI_GATEWAY_API_KEY to reach the decision model"
        )
    version = os.environ.get("SEARCH_INTENT_PROMPT_VERSION")
    prompt = await asyncio.to_thread(
        fetch_search_intent_prompt,
        label=None if version else SEARCH_INTENT_PROMPT_LABEL,
        version=int(version) if version else None,
    )

    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        if task_ctx.demo_data is None:
            raise RuntimeError("one-shot suites run against the master Hedgebox team")
        request = SearchIntentRequest(
            team_id=task_ctx.demo_data.master_team_id,
            query=case.prompt,
            active_group_type=case.metadata["active_group_type"],
            available_group_types=tuple(case.metadata["available_group_types"]),
            scene=case.metadata["scene"],
        )
        started = time.monotonic()
        try:
            # Sync and blocking on the gateway, so keep it off the event loop. No cache: every run asks the model.
            intent = await asyncio.to_thread(classify_search_intent, request, use_cache=False, prompt=prompt)
        except Exception as error:
            return {
                "model": SEARCH_INTENT_MODEL,
                "prompt_version": prompt.version,
                "intent": None,
                "error": f"{type(error).__name__}: {error}",
            }
        answer = dataclasses.asdict(intent)
        return {
            "model": SEARCH_INTENT_MODEL,
            "prompt_version": prompt.version,
            "intent": answer,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "last_message": f"{case.prompt!r} in {request.active_group_type}: {answer}",
        }

    await OneShotPublicEval(
        experiment_name="ml-inference-search-intent",
        cases=[*WRONG_TAB_CASES, *RIGHT_TAB_CASES, *PARTIAL_CASES, *CONTEXT_CASES],
        scorers=[SearchIntentMatch(), SwitchWhenNeeded(), NoWrongSwitch()],
        task=task,
        ctx=ctx,
    )
