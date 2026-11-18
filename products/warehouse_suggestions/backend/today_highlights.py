from posthog.dataclasses import frozen

from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.data_catalog.backend.facade.api import PendingGroup, PendingKind, build_team_pending_review
from products.today.backend.facade.contracts import HighlightCandidate, HighlightContext, HighlightFindings
from products.today.backend.facade.enums import HighlightLabel

from .facade.contracts import SUBJECT_SCOPE_OBJECTS, WAREHOUSE_SCOPE_OBJECT
from .facade.enums import WarehouseSuggestionKind, WarehouseSuggestionSubjectKind
from .logic.access import CATALOG_KINDS, NO_OPEN_SUGGESTIONS, OpenCounts, actionable_open_counts

APPROVER_ACCESS_LEVEL: AccessControlLevel = "editor"
IMPORTANCE = 0.5
ASSIGNED_IMPORTANCE = 0.6

ONE_TITLE = "{counts} waits for approval"
MANY_TITLE = "{counts} wait for approval"
ONE_DETAIL = "Review it in the data catalog."
MANY_DETAIL = "Review them in the data catalog."
CERTIFICATION_SUGGESTION_NOUN = "certification suggestion"
ONE_ASSIGNED_TITLE = "1 {noun} assigned to you waits for review"
MANY_ASSIGNED_TITLE = "{count} {noun}s assigned to you wait for review"

MODEL_KINDS = frozenset(
    {WarehouseSuggestionKind.MATERIALIZE, WarehouseSuggestionKind.UNMATERIALIZE, WarehouseSuggestionKind.DEPRECATE}
)
MODEL_SUBJECT_KINDS = frozenset({WarehouseSuggestionSubjectKind.SAVED_QUERY})
ONE_MODEL_TITLE = "1 model suggestion waits for review"
MANY_MODEL_TITLE = "{count} model suggestions wait for review"
ONE_MODEL_DETAIL = "Review it in Models."
MANY_MODEL_DETAIL = "Review them in Models."
MODEL_SUGGESTION_NOUN = "model suggestion"
MODELS_URL = "/models?tab=models"
SUGGESTION_COUNT_GUARD = "data_catalog_approvals.suggestions"


@frozen
class SuggestionSurface:
    assigned_key: str
    family: str
    noun: str
    one_detail: str
    many_detail: str
    url: str


CATALOG_SURFACE = SuggestionSurface(
    assigned_key="warehouse_suggestions_assigned_catalog",
    family="data_catalog",
    noun=CERTIFICATION_SUGGESTION_NOUN,
    one_detail=ONE_DETAIL,
    many_detail=MANY_DETAIL,
    url=f"/data-catalog?tab={PendingKind.CERTIFICATIONS}",
)
MODELS_SURFACE = SuggestionSurface(
    assigned_key="warehouse_suggestions_assigned_models",
    family="data_modeling",
    noun=MODEL_SUGGESTION_NOUN,
    one_detail=ONE_MODEL_DETAIL,
    many_detail=MANY_MODEL_DETAIL,
    url=MODELS_URL,
)


def find_catalog_approvals(context: HighlightContext) -> HighlightFindings:
    access = UserAccessControl(user=context.user, team=context.team)
    if not access.check_access_level_for_resource("data_catalog", APPROVER_ACCESS_LEVEL):
        return HighlightFindings()
    counts = context.guard(SUGGESTION_COUNT_GUARD, lambda: _open_counts(context, CATALOG_KINDS), NO_OPEN_SUGGESTIONS)
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
    one = count == 1
    return (
        _opportunity(
            key=surface.assigned_key,
            family=surface.family,
            importance=ASSIGNED_IMPORTANCE,
            title=(ONE_ASSIGNED_TITLE if one else MANY_ASSIGNED_TITLE).format(count=count, noun=surface.noun),
            detail=surface.one_detail if one else surface.many_detail,
            url=surface.url,
        ),
    )


def _team_approvals(groups: list[PendingGroup]) -> tuple[HighlightCandidate, ...]:
    if not groups:
        return ()
    one = sum(group.count for group in groups) == 1
    return (
        _opportunity(
            key="data_catalog_approvals",
            family=CATALOG_SURFACE.family,
            importance=IMPORTANCE,
            title=(ONE_TITLE if one else MANY_TITLE).format(counts=_join(groups)),
            detail=ONE_DETAIL if one else MANY_DETAIL,
            url=f"/data-catalog?tab={groups[0].kind}",
        ),
    )


def _team_model_suggestions(counts: OpenCounts) -> tuple[HighlightCandidate, ...]:
    count = counts.unassigned
    if not count:
        return ()
    one = count == 1
    return (
        _opportunity(
            key="warehouse_model_suggestions",
            family=MODELS_SURFACE.family,
            importance=IMPORTANCE,
            title=ONE_MODEL_TITLE if one else MANY_MODEL_TITLE.format(count=count),
            detail=ONE_MODEL_DETAIL if one else MANY_MODEL_DETAIL,
            url=MODELS_URL,
        ),
    )


def _opportunity(*, key: str, family: str, importance: float, title: str, detail: str, url: str) -> HighlightCandidate:
    return HighlightCandidate(
        key=key,
        label=HighlightLabel.OPPORTUNITY,
        family=family,
        importance=importance,
        relevance=1.0,
        title=title,
        detail=detail,
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


def _open_counts(
    context: HighlightContext,
    kinds: frozenset[WarehouseSuggestionKind],
    subject_kinds: frozenset[WarehouseSuggestionSubjectKind] = frozenset(WarehouseSuggestionSubjectKind),
) -> OpenCounts:
    return actionable_open_counts(context.team, context.user, kinds, _writable_subject_kinds(context) & subject_kinds)


def _writable_subject_kinds(context: HighlightContext) -> frozenset[WarehouseSuggestionSubjectKind]:
    return frozenset(
        subject_kind
        for subject_kind, scope_object in SUBJECT_SCOPE_OBJECTS.items()
        if context.allows(f"{WAREHOUSE_SCOPE_OBJECT}:write") or context.allows(f"{scope_object}:write")
    )


def _join(groups: list[PendingGroup]) -> str:
    counts = [f"{group.count} {group.noun}{'' if group.count == 1 else 's'}" for group in groups]
    return counts[0] if len(counts) == 1 else f"{', '.join(counts[:-1])} and {counts[-1]}"
