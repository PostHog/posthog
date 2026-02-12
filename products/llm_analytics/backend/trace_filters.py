from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from posthog.models import Team

TRACE_FILTERS_SETTING_KEY = "llm_analytics_trace_filters"


def sanitize_trace_filters(raw_filters: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_filters, list):
        return []
    return [filter_item for filter_item in raw_filters if isinstance(filter_item, dict)]


def get_trace_filters_from_extra_settings(extra_settings: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not extra_settings:
        return []
    return sanitize_trace_filters(extra_settings.get(TRACE_FILTERS_SETTING_KEY))


def get_team_trace_filters(team: Team) -> list[dict[str, Any]]:
    return get_trace_filters_from_extra_settings(team.extra_settings)


def get_team_trace_filters_bulk(team_ids: Iterable[int]) -> dict[str, list[dict[str, Any]]]:
    team_ids_list = list(team_ids)
    if not team_ids_list:
        return {}

    filters_by_team: dict[str, list[dict[str, Any]]] = {}
    for team_id, extra_settings in Team.objects.filter(id__in=team_ids_list).values_list("id", "extra_settings"):
        filters_by_team[str(team_id)] = get_trace_filters_from_extra_settings(extra_settings)

    return filters_by_team


def set_team_trace_filters(team: Team, trace_filters: list[dict[str, Any]]) -> None:
    extra_settings = team.extra_settings or {}
    extra_settings[TRACE_FILTERS_SETTING_KEY] = trace_filters
    team.extra_settings = extra_settings
    team.save(update_fields=["extra_settings"])
