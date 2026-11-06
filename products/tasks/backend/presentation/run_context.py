from collections.abc import Callable
from uuid import UUID

from rest_framework.request import Request

from posthog.permissions import get_authenticator_scopes

from products.tasks.backend.facade import access
from products.tasks.backend.facade.client_provenance import is_sandbox_oauth_request


def analytics_context_reader(*, request: Request, team_id: int) -> Callable[[object], bool]:
    return access.analytics_context_reader(
        team_id=team_id,
        user_id=getattr(request.user, "id", None),
        token_scopes=get_authenticator_scopes(request.successful_authenticator),
    )


def is_sandbox_run_request(
    *, request: Request, team_id: int, task_id: str, run_id: str | None, include_resume_sources: bool = False
) -> bool:
    if not is_sandbox_oauth_request(request):
        return False
    token = getattr(request.successful_authenticator, "access_token", None)
    try:
        if token is None or token.sandbox_task_id != UUID(task_id):
            return False
    except (ValueError, TypeError):
        return False
    return access.is_sandbox_run_request(
        team_id=team_id,
        task_id=task_id,
        run_id=run_id,
        token_id=token.id,
        include_resume_sources=include_resume_sources,
    )


def may_read_task_run_context(*, request: Request, team_id: int, task_id: str, run_id: str | None) -> bool:
    return access.may_read_task_run_context(
        team_id=team_id,
        task_id=task_id,
        run_id=run_id,
        reader=analytics_context_reader(request=request, team_id=team_id),
    )
