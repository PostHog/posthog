"""The say-less gate lives here — trusted code shared by BOTH engines.

The synthesize engine gates its own LLM output; the agent engine gates the
sandbox report on the trusted side of the activity edge. Neither engine may
carry its own copy.
"""

from products.pulse.backend.generation.schemas import BriefOut

CONFIDENCE_THRESHOLD = 0.6
MAX_OPPORTUNITIES = 3


def apply_say_less_gate(out: BriefOut) -> BriefOut:
    confident_opportunities = [o for o in out.opportunities if o.confidence >= CONFIDENCE_THRESHOLD]
    return BriefOut(
        sections=[s for s in out.sections if s.confidence >= CONFIDENCE_THRESHOLD],
        # Deterministic cap and order: the prompt asks for at most MAX_OPPORTUNITIES with
        # goal-relevant ones marked, but the model may not comply. Goal-relevant first, then
        # by confidence — this sort is what makes the goal-first ranking real.
        opportunities=sorted(confident_opportunities, key=lambda o: (o.goal_relevant, o.confidence), reverse=True)[
            :MAX_OPPORTUNITIES
        ],
    )
