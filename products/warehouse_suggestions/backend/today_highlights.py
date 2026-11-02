from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.data_catalog.backend.facade.api import PendingGroup, PendingKind, build_team_pending_review
from products.today.backend.facade.contracts import HighlightCandidate, HighlightContext, HighlightFindings
from products.today.backend.facade.enums import HighlightLabel

from .facade.contracts import SUBJECT_SCOPE_OBJECTS, WAREHOUSE_SCOPE_OBJECT
from .facade.enums import WarehouseSuggestionKind, WarehouseSuggestionSubjectKind
from .logic.access import CATALOG_KINDS, actionable_open_count

APPROVER_ACCESS_LEVEL: AccessControlLevel = "editor"
IMPORTANCE = 0.5

ONE_TITLE = "{counts} waits for approval"
MANY_TITLE = "{counts} wait for approval"
ONE_DETAIL = "Review it in the data catalog."
MANY_DETAIL = "Review them in the data catalog."
CERTIFICATION_SUGGESTION_NOUN = "certification suggestion"

MODEL_KINDS = frozenset({WarehouseSuggestionKind.MATERIALIZE, WarehouseSuggestionKind.UNMATERIALIZE})
ONE_MODEL_TITLE = "1 model suggestion waits for review"
MANY_MODEL_TITLE = "{count} model suggestions wait for review"
ONE_MODEL_DETAIL = "Review it in Models."
MANY_MODEL_DETAIL = "Review them in Models."
MODELS_URL = "/models?tab=models"
SUGGESTION_COUNT_GUARD = "data_catalog_approvals.suggestions"


def find_catalog_approvals(context: HighlightContext) -> HighlightFindings:
    access = UserAccessControl(user=context.user, team=context.team)
    if not access.check_access_level_for_resource("data_catalog", APPROVER_ACCESS_LEVEL):
        return HighlightFindings()
    groups = _pending_groups(context)
    if not groups:
        return HighlightFindings()
    one = sum(group.count for group in groups) == 1
    return HighlightFindings(
        items=(
            HighlightCandidate(
                key="data_catalog_approvals",
                label=HighlightLabel.OPPORTUNITY,
                family="data_catalog",
                importance=IMPORTANCE,
                relevance=1.0,
                title=(ONE_TITLE if one else MANY_TITLE).format(counts=_join(groups)),
                detail=ONE_DETAIL if one else MANY_DETAIL,
                url=f"/data-catalog?tab={groups[0].kind}",
            ),
        )
    )


def find_model_suggestions(context: HighlightContext) -> HighlightFindings:
    count = _open_count(context, MODEL_KINDS)
    if not count:
        return HighlightFindings()
    one = count == 1
    return HighlightFindings(
        items=(
            HighlightCandidate(
                key="warehouse_model_suggestions",
                label=HighlightLabel.OPPORTUNITY,
                family="data_modeling",
                importance=IMPORTANCE,
                relevance=1.0,
                title=ONE_MODEL_TITLE if one else MANY_MODEL_TITLE.format(count=count),
                detail=ONE_MODEL_DETAIL if one else MANY_MODEL_DETAIL,
                url=MODELS_URL,
            ),
        )
    )


def _pending_groups(context: HighlightContext) -> list[PendingGroup]:
    review = build_team_pending_review(context.team, sample_size=0)
    groups = list(review.groups) if review else []
    suggested = context.guard(SUGGESTION_COUNT_GUARD, lambda: _open_count(context, CATALOG_KINDS), 0)
    if suggested:
        groups.append(
            PendingGroup(
                kind=PendingKind.CERTIFICATIONS,
                noun=CERTIFICATION_SUGGESTION_NOUN,
                count=suggested,
                sample_names=[],
            )
        )
    return groups


def _open_count(context: HighlightContext, kinds: frozenset[WarehouseSuggestionKind]) -> int:
    return actionable_open_count(context.team, context.user, kinds, _writable_subject_kinds(context))


def _writable_subject_kinds(context: HighlightContext) -> frozenset[WarehouseSuggestionSubjectKind]:
    return frozenset(
        subject_kind
        for subject_kind, scope_object in SUBJECT_SCOPE_OBJECTS.items()
        if context.allows(f"{WAREHOUSE_SCOPE_OBJECT}:write") or context.allows(f"{scope_object}:write")
    )


def _join(groups: list[PendingGroup]) -> str:
    counts = [f"{group.count} {group.noun}{'' if group.count == 1 else 's'}" for group in groups]
    return counts[0] if len(counts) == 1 else f"{', '.join(counts[:-1])} and {counts[-1]}"
