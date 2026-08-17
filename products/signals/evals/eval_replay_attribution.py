"""Does report research attribute a session recording moment to the right source file?

A Replay Vision signal carries a moment in a recording, not a file. Each case here builds the
**real** research prompt for one such signal (``build_initial_research_prompt``, including the
attribution block it adds when a signal carries a session id), seeds the events that sit around
that moment into the case's own team, and scores where the agent said the defect lives.

The repository every sandboxed case clones is ``PostHog/hedgebox``, which is the same app as
``tools/hedgebox-dummy/`` in this repo, so the expected paths are real files the agent can open.

Hedgebox is deliberately the hard fixture. It carries no ``data-attr``, ``data-testid``, or
``id`` anywhere in its markup, so the developer-authored-identifier tier the recipe ranks second
is **absent by construction** and is not scored here. What the suite does cover:

* ``exception_names_the_file`` - a stack trace at the moment, the strongest anchor.
* ``element_text_on_files_page`` - on-screen text from the element chain.
* ``route_only_render_failure`` - nothing interactive at the moment, so only the route remains.
* ``scanner_recorded_element_on_signup`` - the element the scanner already recorded in ``extra``.

Track the two causes apart: an interaction-caused defect has an autocapture row behind it and a
render-caused one does not, so they exercise different anchors and should not be averaged into
one number without looking at the split. The ``cause`` metadata on each case carries it.

To run a single case::

    flox activate -- bash -c "hogli evals eval_replay_attribution --eval element_text_on_files_page"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.signals.backend.report_generation.research import _has_replay_signals, build_initial_research_prompt
from products.signals.backend.temporal.types import SignalData
from products.signals.evals.constants import (
    ALL_CASES,
    ELEMENT_TEXT_CASE,
    EXCEPTION_CASE,
    ROUTE_ONLY_CASE,
    SCANNER_ELEMENT_CASE,
    AttributionCase,
)
from products.signals.evals.scorers import AttributionAnyPath, AttributionTopPath, RecordingWindowQueried
from products.signals.evals.seeders import (
    seed_element_text_attribution,
    seed_exception_attribution,
    seed_route_only_attribution,
    seed_scanner_element_attribution,
)

_SEEDERS = {
    EXCEPTION_CASE.name: seed_exception_attribution,
    ELEMENT_TEXT_CASE.name: seed_element_text_attribution,
    ROUTE_ONLY_CASE.name: seed_route_only_attribution,
    SCANNER_ELEMENT_CASE.name: seed_scanner_element_attribution,
}


def _signal_for(case: AttributionCase) -> SignalData:
    """A Replay Vision signal in the shape `emit_observation_signal` actually emits."""
    extra = {
        "scanner_id": "0195f000-0000-7000-8000-0000000000aa",
        "scanner_name": "Broken flows",
        "scanner_type": "monitor",
        "observation_id": "0195f000-0000-7000-8000-0000000000bb",
        "session_id": case.session_id,
        "confidence": 0.8,
        "problem_type": "bug",
        "start_time": case.start_time,
        "end_time": case.start_time + 6,
        "url": case.url,
        "exported_asset_id": 1,
        "recording_start_time": case.recording_start_time.isoformat(),
    }
    if case.element:
        extra["element"] = case.element
    return SignalData(
        signal_id=f"sig-{case.name}",
        content=case.description,
        source_product="replay_vision",
        source_type="scanner_finding",
        source_id=f"observation:{case.name}:0",
        weight=0.5,
        timestamp=case.recording_start_time,
        extra=extra,
    )


def _build_case(case: AttributionCase) -> SandboxedEvalCase:
    signal = _signal_for(case)
    return SandboxedEvalCase(
        name=case.name,
        # The production prompt, built the way `run_multi_turn_research` builds it, so the suite
        # regresses the real thing rather than a copy that can drift away from it.
        prompt=build_initial_research_prompt(signal, 1, has_replay_signals=_has_replay_signals([signal])),
        repo_fixture="posthog/hedgebox",
        expected={
            "attribution_top_path": {"path": case.expected_path},
            "attribution_any_path": {"path": case.expected_path},
            "recording_window_queried": {"session_id": case.session_id},
        },
        metadata={"tier": case.tier, "cause": case.cause, "carries_element": bool(case.element)},
        setup=_SEEDERS[case.name],
    )


async def eval_replay_attribution(ctx: EvalContext) -> None:
    """Does research turn a recording moment into the file a human would change?"""
    await SandboxedPublicEval(
        experiment_name="signals-replay-attribution-cli",
        cases=[_build_case(case) for case in ALL_CASES],
        scorers=[AttributionTopPath(), AttributionAnyPath(), RecordingWindowQueried()],
        ctx=ctx,
    )
