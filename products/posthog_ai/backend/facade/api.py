from posthog.models.team import Team
from posthog.models.user import User

from products.posthog_ai.backend.models.assistant import CoreMemory

from ee.hogai.utils.feature_flags import is_core_memory_disabled


def core_memory_text(team: Team, user: User) -> str:
    """The team's core memory (what the company does and is trying to learn), for grounding prompts.

    Empty string when no memory exists. Applies the core-memory kill switch here so callers
    outside this product can't forget it.
    """
    if is_core_memory_disabled(team, user):
        return ""
    memory = CoreMemory.objects.filter(team=team).only("text").first()
    if memory is None:
        return ""
    return memory.formatted_text.strip()
