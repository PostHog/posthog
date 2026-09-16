"""Steering for the sources that emit straight through ``emit_signal``.

Error tracking and health checks never enter the batch pipeline in ``pipeline.py``, so until now
nothing read the ``steering`` text a team wrote for them and the only way to stop a class of report
was to turn the source off. This gate closes that gap: ``emit_signal`` asks it about every signal
from a pair in ``DIRECT_STEERABLE_SOURCES``, and drops the signal when the team's own rules say to
skip it.

Two properties keep the gate cheap and predictable:

- **No steering, no gate.** Written ``steering`` text is the only thing that turns the gate on, so a
  team that wrote nothing gets no LLM call, no added latency, and the behavior it has today. The
  retired ``default_not_actionable`` posture is deliberately ignored here: it tells the model to keep
  only records that clearly match the prompt's ACTIONABLE criteria, and this prompt states none, so
  honoring it would drop nearly everything.
- **The team's rules are the only criteria.** The canonical prompt here states no opinion of its own
  about what deserves a report, unlike the record-shaped prompts in ``_prompts.py`` that the batch
  pipeline applies whether or not a team has steered. So writing a first rule filters what that rule
  describes, and nothing else.

The gate fails open. A steering rule that never runs costs a team one noisy report; a gate that
drops signals when the LLM is unreachable loses real ones.
"""

import asyncio
from typing import Any

import structlog

from posthog.llm.gateway_client import build_async_anthropic_client, resolve_ai_gateway_config
from posthog.models import Organization, Team

from products.signals.backend.emission.pipeline import EMISSION_AI_PRODUCT, capture_pipeline_stage, check_actionability
from products.signals.backend.emission.registry import SignalEmitterOutput
from products.signals.backend.emission.steering import (
    SourceSteering,
    afetch_source_config,
    apply_steering,
    steering_from_config,
)

logger = structlog.get_logger(__name__)

# The whole verdict, retries included, has to fit inside the budget its caller already has, and some
# callers emit many signals in one activity. `check_actionability` alone can spend three attempts of
# up to 120 seconds, which overruns the tightest of those budgets (the 2-minute activity in
# `temporal/backfill_error_tracking.py`) on a single signal. A verdict is not worth holding an emit
# for once it is this late, so the gate gives up and fails open well before its caller has to.
GATE_TIMEOUT_SECONDS = 20

# Keeps the `When in doubt, classify as ACTIONABLE` line `apply_steering` anchors on, and the
# one-word output contract `check_actionability` parses.
DIRECT_SOURCE_ACTIONABILITY_PROMPT = """You are triaging one record a PostHog product raised for the team that owns it, to decide whether the team should see it.

The team's own preferences are the only thing that filters here. Classify the record NOT_ACTIONABLE when those preferences say to skip it. There are no other criteria: a record that no preference excludes is ACTIONABLE.

When in doubt, classify as ACTIONABLE.

<record>
{description}
</record>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""


async def steering_filters_signal(
    *,
    team: Team,
    organization: Organization,
    source_product: str,
    source_type: str,
    source_id: str,
    description: str,
    weight: float,
    extra: dict[str, Any],
) -> bool:
    """Whether this team's steering says to drop the signal.

    Returns False without an LLM call when the team has written no steering for the source. A dropped
    signal reports itself as ``signal_data_source_filtered`` with ``steering_applied``, the same stage
    event the batch pipeline fires, so a filtered signal is distinguishable from one lost to a failure.
    """
    # Text only, dropping any `default_not_actionable` the row carries. See the module docstring.
    steering = SourceSteering(
        text=steering_from_config(await afetch_source_config(team.id, source_product, source_type)).text
    )
    if not steering.text:
        return False

    output = SignalEmitterOutput(
        source_product=source_product,
        source_type=source_type,
        source_id=source_id,
        description=description,
        weight=weight,
        extra=extra,
    )
    try:
        # Closed on the way out: unlike the batch pipeline, which builds one client for a whole run,
        # this path builds one per signal, and each carries its own httpx connection pool.
        async with build_async_anthropic_client(
            product="signals", ai_product=EMISSION_AI_PRODUCT, team_id=team.id
        ) as client:
            actionable = await asyncio.wait_for(
                check_actionability(
                    client,
                    team.id,
                    output,
                    apply_steering(DIRECT_SOURCE_ACTIONABILITY_PROMPT, steering),
                    gateway_mode=resolve_ai_gateway_config() is not None,
                    # Steering rules reference facts the description does not always carry (a host, a
                    # check kind), so the steered gate sees all of `extra`, as in the batch pipeline.
                    include_record_metadata=True,
                ),
                timeout=GATE_TIMEOUT_SECONDS,
            )
    except Exception:
        logger.exception(
            "Source steering gate failed, keeping signal",
            signal_source_product=source_product,
            signal_source_type=source_type,
            signal_source_id=source_id,
        )
        return False

    if actionable:
        return False

    logger.info(
        "Filtered signal by source steering",
        signal_source_product=source_product,
        signal_source_type=source_type,
        signal_source_id=source_id,
    )
    capture_pipeline_stage("signal_data_source_filtered", team, organization, output, {"steering_applied": True})
    return True
