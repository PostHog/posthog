"""Keep the workflows scout running exactly where someone asked for suggestions.

The scout only reads workflows whose owner turned on "Suggest improvements", so a project with none
turned on gains nothing from its runs. Turning the first workflow on switches the scout on for the
project, and turning the last one off removes it again.
"""

from django.db.models import Q

from posthog.models import Team, User

from products.signals.backend.facade.api import disable_scout_for_product, enable_scout_for_product
from products.workflows.backend.models import HogFlowOptimization

SUGGESTIONS_SCOUT = "signals-scout-workflows"
SOURCE_PRODUCT = "workflows"
PROPOSAL_WRITE_SCOPE = "hog_flow_proposal:write"


def sync_suggestions_scout(team: Team, *, acting_user: User) -> bool:
    """Switch the scout on or off to match the project's opted-in workflows. Returns whether it is on."""
    # Scouts belong to the project's main environment, while workflows can live in any of its environments.
    project = team.parent_team or team
    environments = Team.objects.filter(Q(id=project.id) | Q(parent_team_id=project.id)).values("id")
    if HogFlowOptimization.objects.unscoped().filter(team_id__in=environments, enabled=True).exists():
        return enable_scout_for_product(
            team=project,
            skill_name=SUGGESTIONS_SCOUT,
            source_product=SOURCE_PRODUCT,
            acting_user=acting_user,
            write_scopes=[PROPOSAL_WRITE_SCOPE],
        )
    disable_scout_for_product(team_id=project.id, skill_name=SUGGESTIONS_SCOUT, source_product=SOURCE_PRODUCT)
    return False
