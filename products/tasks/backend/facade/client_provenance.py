from rest_framework.request import Request

from posthog.oauth_provenance import (
    is_interactive_desktop_grant,
    is_sandbox_oauth_request as is_sandbox_oauth_request,
    is_sandbox_origin_request as is_sandbox_origin_request,
)

from products.tasks.backend.models import TaskClientProvenance


def is_api_key_request(authenticator: object) -> bool:
    """Whether ``authenticator`` — a request's ``successful_authenticator`` — is a
    long-lived API key acting as a user.

    "As a user" is the load-bearing half. Callers use this to decide things that are
    charged or attributed to a person, so a key that resolves to a team or a project
    rather than a user — ``TeamSecretTokenAuthentication`` hands back a synthetic
    ``TeamSecretTokenUser``, ``ProjectSecretAPIKeyAuthentication`` is project-scoped —
    must not qualify, however server-to-server it looks.

    Takes the authenticator rather than the request itself: the facade boundary must not
    put a DRF type on its signature (products/architecture.md § Facades: The Public
    Interface), and the authenticator is the only part of the request this needs.

    Personal API keys are the only kind that qualifies today; ``isinstance`` also covers
    the delegated variant. A future key type (BYOK, say) belongs in the tuple below once
    it resolves to a real user.

    ``posthog.auth`` is imported inside the function, matching ``posthog.oauth_provenance``:
    importing it at module level cycles back through the model layer.
    """
    from posthog.auth import PersonalAPIKeyAuthentication  # noqa: PLC0415 — circular at module level

    user_api_key_authenticators: tuple[type, ...] = (PersonalAPIKeyAuthentication,)
    return isinstance(authenticator, user_api_key_authenticators)


def get_task_client_provenance(request: Request) -> TaskClientProvenance | None:
    if is_interactive_desktop_grant(request):
        return TaskClientProvenance.POSTHOG_DESKTOP
    return None
