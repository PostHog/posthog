from datetime import datetime

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType
from products.data_catalog.backend.facade.contracts import DigestRow

from .facade.enums import WarehouseSuggestionStatus
from .logic.access import CATALOG_KINDS, actionable_open_suggestions, is_on_models_surface
from .logic.flags import is_warehouse_suggestions_enabled
from .models import WarehouseSuggestion
from .today_highlights import CATALOG_SURFACE, MODELS_SURFACE

SAMPLE_SIZE = 5


@frozen
class DigestGroup:
    noun: str
    path: str


CATALOG_GROUP = DigestGroup(noun=CATALOG_SURFACE.noun, path="/data-catalog?tab=suggestions")
MODELS_GROUP = DigestGroup(noun=MODELS_SURFACE.noun, path=MODELS_SURFACE.url)


def suggestion_rows(team: Team, user: User, new_since: datetime) -> list[DigestRow]:
    """Runs only for teams `teams_with_open_suggestions` returned, so the organization's flag is already checked."""
    suggestions = actionable_open_suggestions(team, user)
    models = [suggestion for suggestion in suggestions if is_on_models_surface(suggestion)]
    catalog = (
        [s for s in suggestions if not is_on_models_surface(s) and s.kind in CATALOG_KINDS]
        if _can_approve_catalog_items(team, user)
        else []
    )
    rows = [_row(CATALOG_GROUP, catalog, new_since), _row(MODELS_GROUP, models, new_since)]
    return [row for row in rows if row.count]


def _can_approve_catalog_items(team: Team, user: User) -> bool:
    return authorization.check(
        resource=Resource(type=ResourceType.DATA_CATALOG, project_id=team.pk),
        action=Action.EDIT,
        subject=Subject(user_id=user.pk),
    )


def teams_with_open_suggestions(teams: list[Team]) -> set[int]:
    """Teams with a proposed suggestion on show; the flag is per organization, so the first team stands for all."""
    if not teams or not is_warehouse_suggestions_enabled(teams[0]):
        return set()
    return set(
        WarehouseSuggestion.objects.unscoped()
        .filter(
            team_id__in=[team.id for team in teams],
            status=WarehouseSuggestionStatus.PROPOSED,
            surfaced_at__isnull=False,
        )
        .values_list("team_id", flat=True)
        .distinct()
    )


def _row(group: DigestGroup, suggestions: list[WarehouseSuggestion], new_since: datetime) -> DigestRow:
    return DigestRow(
        noun=group.noun,
        count=len(suggestions),
        new_count=sum(
            1 for suggestion in suggestions if suggestion.surfaced_at and suggestion.surfaced_at >= new_since
        ),
        sample_names=[suggestion.payload.get("subject_name", "") for suggestion in suggestions[:SAMPLE_SIZE]],
        path=group.path,
    )
