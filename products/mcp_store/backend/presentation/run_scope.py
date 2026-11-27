from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from posthog.oauth_provenance import get_oauth_access_token

from ..facade.run_scope_hooks import run_installation_allowlist


def request_run_installation_allowlist(request: Request) -> list[str] | None:
    """The allowlist for the sandbox token a request authenticated with. None for any other caller."""
    access_token = get_oauth_access_token(request)
    sandbox_task_id = getattr(access_token, "sandbox_task_id", None)
    token_id = getattr(access_token, "id", None)
    if sandbox_task_id is None or token_id is None:
        return None
    return run_installation_allowlist(sandbox_task_id, str(token_id))


class DenyRunWithConnectionSelection(BasePermission):
    """For a view that lists the person's connections beyond the ones a run selected."""

    message = "This run can only use the connections it selected."

    def has_permission(self, request: Request, view: object) -> bool:
        return request_run_installation_allowlist(request) is None
