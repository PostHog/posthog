"""Data capabilities of the web_analytics facade.

Kept free of HogQL/temporal imports so config-only consumers don't drag them
onto the django.setup() path — query-runner and worker wiring live in the
`queries`, `hogql`, and `temporal` submodules.
"""

from __future__ import annotations

from products.web_analytics.backend.facade.contracts import FilterPreset, UserRef
from products.web_analytics.backend.models import WebAnalyticsFilterPreset


def _user_ref(user: object | None) -> UserRef | None:
    if user is None:
        return None
    return UserRef(id=user.id, email=user.email, first_name=user.first_name, last_name=user.last_name)


def _to_contract(preset: WebAnalyticsFilterPreset) -> FilterPreset:
    return FilterPreset(
        id=preset.id,
        short_id=preset.short_id,
        name=preset.name,
        description=preset.description,
        pinned=preset.pinned,
        deleted=preset.deleted,
        filters=preset.filters,
        created_at=preset.created_at,
        last_modified_at=preset.last_modified_at,
        created_by=_user_ref(preset.created_by),
        last_modified_by=_user_ref(preset.last_modified_by),
    )


def list_filter_presets(team_id: int, *, include_deleted: bool = False) -> list[FilterPreset]:
    qs = WebAnalyticsFilterPreset.objects.filter(team_id=team_id).select_related("created_by", "last_modified_by")
    if not include_deleted:
        qs = qs.filter(deleted=False)
    return [_to_contract(p) for p in qs.order_by("-last_modified_at")]


def get_filter_preset(team_id: int, short_id: str) -> FilterPreset | None:
    preset = (
        WebAnalyticsFilterPreset.objects.filter(team_id=team_id, short_id=short_id)
        .select_related("created_by", "last_modified_by")
        .first()
    )
    return _to_contract(preset) if preset is not None else None
