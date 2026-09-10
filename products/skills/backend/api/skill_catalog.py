"""The filters and orderings the skill list endpoint offers."""

from typing import Any

from django.db.models import Q, QuerySet
from django.http import QueryDict

from posthog.models import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..models.skills import LLMSkill
from .skill_services import get_latest_skills_queryset, skill_names_owned_by

ALLOWED_LIST_ORDERINGS = frozenset(
    {
        "name",
        "-name",
        "created_at",
        "-created_at",
        "updated_at",
        "-updated_at",
        "version",
        "-version",
        "latest_version",
        "-latest_version",
        "version_count",
        "-version_count",
    }
)


def list_queryset(
    *, team: Team, user_access_control: UserAccessControl, params: dict[str, Any], query_params: QueryDict
) -> QuerySet[LLMSkill]:
    queryset = user_access_control.filter_queryset_by_access_level(
        get_latest_skills_queryset(team), resource="llm_skill"
    )

    search = params.get("search", "").strip()
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))

    created_by_id = params.get("created_by_id")
    if created_by_id:
        queryset = queryset.filter(created_by_id=created_by_id)

    # Owners are keyed on the logical skill name, not on a version row, so the filter matches by
    # name across every version the queryset could surface.
    owner_id = params.get("owner_id")
    if owner_id:
        queryset = queryset.filter(name__in=skill_names_owned_by(team, owner_id))

    # Presence of the param — even as an empty string — is a filter: `?category=` returns only
    # uncategorized skills, `?category=scout` only scouts. Omitting it returns every category.
    if "category" in query_params:
        queryset = queryset.filter(category=params.get("category") or "")

    order_by = query_params.get("order_by", "-created_at")
    queryset = queryset.order_by(order_by if order_by in ALLOWED_LIST_ORDERINGS else "-created_at", "-id")
    return queryset
