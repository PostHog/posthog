from posthog.dataclasses import frozen

from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.data_catalog.backend.facade.api import PendingGroup, PendingKind, build_team_pending_review
from products.today.backend.facade.contracts import HighlightCandidate, HighlightContext, HighlightFindings
from products.today.backend.facade.enums import HighlightLabel

from .facade.contracts import SUBJECT_SCOPE_OBJECTS, WAREHOUSE_SCOPE_OBJECT
from .facade.enums import WarehouseSuggestionKind, WarehouseSuggestionSubjectKind, WarehouseSuggestionSurface
from .logic.access import CATALOG_KINDS, NO_OPEN_SUGGESTIONS, OpenCounts, actionable_open_counts

APPROVER_ACCESS_LEVEL: AccessControlLevel = "editor"
IMPORTANCE = 0.5
ASSIGNED_IMPORTANCE = 0.6

ONE_TITLE = "{counts} waits for {action}"
MANY_TITLE = "{counts} wait for {action}"
ASSIGNED_COUNTS = "{counts} assigned to you"
CERTIFICATION_SUGGESTION_NOUN = "certification suggestion"

MODEL_KINDS = frozenset(
    {WarehouseSuggestionKind.MATERIALIZE, WarehouseSuggestionKind.UNMATERIALIZE, WarehouseSuggestionKind.DEPRECATE}
)
MODEL_SUBJECT_KINDS = frozenset({WarehouseSuggestionSubjectKind.SAVED_QUERY})
SUGGESTION_COUNT_GUARD = "data_catalog_approvals.suggestions"


@frozen
class SuggestionSurface:
    assigned_key: str
    team_key: str
    family: str
    noun: str
    action: str
    one_detail: str
    many_detail: str
    url: str


CATALOG_SURFACE = SuggestionSurface(
    assigned_key="warehouse_suggestions_assigned_catalog",
    team_key="data_catalog_approvals",
    family="data_catalog",
    noun=CERTIFICATION_SUGGESTION_NOUN,
    action="approval",
    one_detail="Review it in the data catalog.",
    many_detail="Review them in the data catalog.",
    url=f"/data-catalog?tab={PendingKind.CERTIFICATIONS}",
)
MODELS_SURFACE = SuggestionSurface(
    assigned_key="warehouse_suggestions_assigned_models",
    team_key="warehouse_model_suggestions",
    family="data_modeling",
    noun="model suggestion",
    action="review",
    one_detail="Review it in Models.",
    many_detail="Review them in Models.",
    url="/models?tab=models",
)


def find_catalog_approvals(context: HighlightContext) -> HighlightFindings:
    access = UserAccessControl(user=context.user, team=context.team)
    if not access.check_access_level_for_resource("data_catalog", APPROVER_ACCESS_LEVEL):
        return HighlightFindings()
    counts = context.guard(SUGGESTION_COUNT_GUARD, lambda: _catalog_open_counts(context), NO_OPEN_SUGGESTIONS)
    return HighlightFindings(
        items=_assigned_to_viewer(CATALOG_SURFACE, counts) + _team_approvals(_pending_groups(context, counts))
    )


def find_model_suggestions(context: HighlightContext) -> HighlightFindings:
    counts = _open_counts(context, MODEL_KINDS, MODEL_SUBJECT_KINDS)
    return HighlightFindings(items=_assigned_to_viewer(MODELS_SURFACE, counts) + _team_model_suggestions(counts))


def _assigned_to_viewer(surface: SuggestionSurface, counts: OpenCounts) -> tuple[HighlightCandidate, ...]:
    count = counts.assigned_to_viewer
    if not count:
        return ()
    return (
        _row(
            surface,
            key=surface.assigned_key,
            importance=ASSIGNED_IMPORTANCE,
            counts=ASSIGNED_COUNTS.format(counts=_counted(count, surface.noun)),
            total=count,
            url=surface.url,
        ),
    )


def _team_approvals(groups: list[PendingGroup]) -> tuple[HighlightCandidate, ...]:
    if not groups:
        return ()
    return (
        _row(
            CATALOG_SURFACE,
            key=CATALOG_SURFACE.team_key,
            importance=IMPORTANCE,
            counts=_join(groups),
            total=sum(group.count for group in groups),
            url=f"/data-catalog?tab={groups[0].kind}",
        ),
    )


def _team_model_suggestions(counts: OpenCounts) -> tuple[HighlightCandidate, ...]:
    count = counts.unassigned
    if not count:
        return ()
    return (
        _row(
            MODELS_SURFACE,
            key=MODELS_SURFACE.team_key,
            importance=IMPORTANCE,
            counts=_counted(count, MODELS_SURFACE.noun),
            total=count,
            url=MODELS_SURFACE.url,
        ),
    )


def _row(
    surface: SuggestionSurface, *, key: str, importance: float, counts: str, total: int, url: str
) -> HighlightCandidate:
    one = total == 1
    return HighlightCandidate(
        key=key,
        label=HighlightLabel.OPPORTUNITY,
        family=surface.family,
        importance=importance,
        relevance=1.0,
        title=(ONE_TITLE if one else MANY_TITLE).format(counts=counts, action=surface.action),
        detail=surface.one_detail if one else surface.many_detail,
        url=url,
    )


def _pending_groups(context: HighlightContext, counts: OpenCounts) -> list[PendingGroup]:
    review = build_team_pending_review(context.team, sample_size=0)
    groups = list(review.groups) if review else []
    if counts.unassigned:
        groups.append(
            PendingGroup(
                kind=PendingKind.CERTIFICATIONS,
                noun=CERTIFICATION_SUGGESTION_NOUN,
                count=counts.unassigned,
                sample_names=[],
            )
        )
    return groups


def _catalog_open_counts(context: HighlightContext) -> OpenCounts:
    return _open_counts(context, CATALOG_KINDS, excluded_surface=WarehouseSuggestionSurface.MODELS)


def _open_counts(
    context: HighlightContext,
    kinds: frozenset[WarehouseSuggestionKind],
    subject_kinds: frozenset[WarehouseSuggestionSubjectKind] = frozenset(WarehouseSuggestionSubjectKind),
    *,
    excluded_surface: WarehouseSuggestionSurface | None = None,
) -> OpenCounts:
    return actionable_open_counts(
        context.team,
        context.user,
        kinds,
        _writable_subject_kinds(context) & subject_kinds,
        excluded_surface=excluded_surface,
    )


def _writable_subject_kinds(context: HighlightContext) -> frozenset[WarehouseSuggestionSubjectKind]:
    return frozenset(
        subject_kind
        for subject_kind, scope_object in SUBJECT_SCOPE_OBJECTS.items()
        if context.allows(f"{WAREHOUSE_SCOPE_OBJECT}:write") or context.allows(f"{scope_object}:write")
    )


def _join(groups: list[PendingGroup]) -> str:
    counts = [_counted(group.count, group.noun) for group in groups]
    return counts[0] if len(counts) == 1 else f"{', '.join(counts[:-1])} and {counts[-1]}"


def _counted(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"
