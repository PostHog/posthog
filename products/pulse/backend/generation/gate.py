from products.pulse.backend.generation.schemas import BriefOut
from products.pulse.backend.models import BriefConfig

# Shared say-less defaults; a BriefConfig may override either (null field = use these).
CONFIDENCE_THRESHOLD = 0.6
MAX_OPPORTUNITIES = 3


def gate_thresholds(config: BriefConfig | None) -> tuple[float, int]:
    """Resolve (confidence_threshold, max_opportunities) for a config, falling back to the
    shared defaults for null fields and zero-config briefs."""
    if config is None:
        return CONFIDENCE_THRESHOLD, MAX_OPPORTUNITIES
    confidence = config.confidence_threshold if config.confidence_threshold is not None else CONFIDENCE_THRESHOLD
    max_opportunities = config.max_opportunities if config.max_opportunities is not None else MAX_OPPORTUNITIES
    return confidence, max_opportunities


def apply_say_less_gate(
    out: BriefOut,
    *,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
    max_opportunities: int = MAX_OPPORTUNITIES,
) -> BriefOut:
    confident_opportunities = [o for o in out.opportunities if o.confidence >= confidence_threshold]
    return BriefOut(
        sections=[s for s in out.sections if s.confidence >= confidence_threshold],
        # Deterministic cap and order: the prompt asks for at most max_opportunities with
        # goal-relevant ones marked, but the model may not comply. Goal-relevant first, then
        # by confidence — this sort is what makes the goal-first ranking real.
        opportunities=sorted(confident_opportunities, key=lambda o: (o.goal_relevant, o.confidence), reverse=True)[
            :max_opportunities
        ],
    )
