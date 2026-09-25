from rest_framework.request import Request

from posthog.oauth_provenance import (
    is_interactive_desktop_grant,
    is_sandbox_oauth_request as is_sandbox_oauth_request,
    is_sandbox_origin_request as is_sandbox_origin_request,
)

from products.tasks.backend.models import TaskClientProvenance


def is_personal_api_key_request(request: Request) -> bool:
    """Whether this request authenticated with a personal API key.

    ``posthog.auth`` is imported inside the function, matching
    ``posthog.oauth_provenance``: importing it at module level cycles back through
    the model layer.
    """
    from posthog.auth import PersonalAPIKeyAuthentication  # noqa: PLC0415 — circular at module level

    return isinstance(getattr(request, "successful_authenticator", None), PersonalAPIKeyAuthentication)


def get_task_client_provenance(request: Request) -> TaskClientProvenance | None:
    if is_interactive_desktop_grant(request):
        return TaskClientProvenance.POSTHOG_DESKTOP
    return None
