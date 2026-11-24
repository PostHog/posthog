from datetime import datetime

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.data_catalog.backend.facade.contracts import DigestRow

from .facade.enums import (
    WarehouseSuggestionKind,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
    WarehouseSuggestionSurface,
)
from .logic.access import CATALOG_KINDS, actionable_open_suggestions
from .logic.flags import is_warehouse_suggestions_enabled
from .models import WarehouseSuggestion
from .today_highlights import CATALOG_SURFACE, MODEL_KINDS, MODEL_SUBJECT_KINDS, MODELS_SURFACE

SAMPLE_SIZE = 5
ALL_SUBJECT_KINDS = frozenset(WarehouseSuggestionSubjectKind)


@frozen
class DigestGroup:
    noun: str
    path: str
    kinds: frozenset[WarehouseSuggestionKind]
    subject_kinds: frozenset[WarehouseSuggestionSubjectKind]
    excluded_surface: WarehouseSuggestionSurface | None = None


CATALOG_GROUP = DigestGroup(
    noun=CATALOG_SURFACE.noun,
    path="/data-catalog?tab=suggestions",
    kinds=CATALOG_KINDS,
    subject_kinds=ALL_SUBJECT_KINDS,
    excluded_surface=WarehouseSuggestionSurface.MODELS,
)
MODELS_GROUP = DigestGroup(
    noun=MODELS_SURFACE.noun,
    path=MODELS_SURFACE.url,
    kinds=MODEL_KINDS,
    subject_kinds=MODEL_SUBJECT_KINDS,
)


def suggestion_rows(team: Team, user: User, new_since: datetime) -> list[DigestRow]:
    rows = (_row(team, user, group, new_since) for group in (CATALOG_GROUP, MODELS_GROUP))
    return [row for row in rows if row.count]


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


def _row(team: Team, user: User, group: DigestGroup, new_since: datetime) -> DigestRow:
    suggestions = actionable_open_suggestions(
        team, user, group.kinds, group.subject_kinds, excluded_surface=group.excluded_surface
    )
    return DigestRow(
        noun=group.noun,
        count=len(suggestions),
        new_count=sum(
            1 for suggestion in suggestions if suggestion.surfaced_at and suggestion.surfaced_at >= new_since
        ),
        sample_names=[suggestion.payload.get("subject_name", "") for suggestion in suggestions[:SAMPLE_SIZE]],
        path=group.path,
    )
