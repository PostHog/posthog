from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.cache import cache

import structlog

from posthog.models import Team, User

from products.notebooks.backend.kernel import notebook_kernel_service
from products.notebooks.backend.models import Notebook

logger = structlog.get_logger(__name__)

NOTEBOOK_QUERY_VARIABLE_CACHE_KEY = "notebook_query_variable:{team_id}:{query_id}"
PENDING_NOTEBOOK_QUERY_TIMEOUT_SECONDS = 60 * 60


@dataclass
class NotebookQueryVariable:
    team_id: int
    notebook_short_id: str
    user_id: int | None
    variable_name: str


def cache_notebook_query_variable(
    query_id: str, payload: NotebookQueryVariable, ttl: int = PENDING_NOTEBOOK_QUERY_TIMEOUT_SECONDS
) -> None:
    cache.set(_cache_key(payload.team_id, query_id), payload.__dict__, ttl)


def get_cached_notebook_query_variable(team_id: int, query_id: str) -> NotebookQueryVariable | None:
    cached_value = cache.get(_cache_key(team_id, query_id))
    if not cached_value:
        return None

    try:
        return NotebookQueryVariable(**cached_value)
    except TypeError:
        return None


def clear_cached_notebook_query_variable(team_id: int, query_id: str) -> None:
    cache.delete(_cache_key(team_id, query_id))


def store_query_result_in_kernel(team: Team, user: User | None, pending: NotebookQueryVariable, result: Any) -> bool:
    if team.pk != pending.team_id:
        logger.warning(
            "notebook_kernel_team_mismatch",
            team_id=team.pk,
            notebook_short_id=pending.notebook_short_id,
        )
        return False

    notebook_user = _resolve_user(user, pending.user_id)
    notebook = _resolve_notebook(team, pending.notebook_short_id, notebook_user)
    if not notebook:
        return False

    success = notebook_kernel_service.store_value(notebook, pending.variable_name, result)
    if not success:
        logger.warning(
            "notebook_kernel_store_failed",
            notebook_short_id=pending.notebook_short_id,
            variable_name=pending.variable_name,
        )

    return success


def _cache_key(team_id: int, query_id: str) -> str:
    return NOTEBOOK_QUERY_VARIABLE_CACHE_KEY.format(team_id=team_id, query_id=query_id)


def _resolve_notebook(team: Team, notebook_short_id: str, user: User | None) -> Notebook | None:
    if notebook_short_id == "scratchpad":
        return Notebook(
            short_id="scratchpad",
            team=team,
            created_by=user,
            last_modified_by=user,
            visibility=Notebook.Visibility.INTERNAL,
        )

    try:
        return Notebook.objects.get(team=team, short_id=notebook_short_id)
    except Notebook.DoesNotExist:
        logger.warning("notebook_kernel_notebook_missing", team_id=team.pk, notebook_short_id=notebook_short_id)
        return None


def _resolve_user(user: User | None, user_id: int | None) -> User | None:
    if isinstance(user, User):
        return user

    if user_id:
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

    return None
