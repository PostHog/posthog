"""The permission limit for work that an external client delegates to PostHog AI.

The sandbox agent mints its own PostHog token, so the caller's limits do not reach it unless they
are copied onto the run. The grant is the full sandbox preset narrowed to what the calling
credential holds. The run stores the grant as an explicit scope list, so a resume or a token
renewal mints the same grant and never the wider default.
"""

from posthog.dataclasses import frozen
from posthog.models.oauth import OAuthRefreshToken, live_oauth_access_tokens
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.user import User
from posthog.permissions import get_authenticator_scopes, get_authenticator_user_credential
from posthog.scopes import scopes_not_covered
from posthog.temporal.oauth import resolve_scopes

from products.posthog_ai.backend.models import AgentOperation


@frozen
class ParentCredential:
    kind: str
    ref: str | None


def granted_scopes(caller_scopes: list[str] | None) -> list[str]:
    """The sandbox scopes that the caller may delegate.

    ``None`` is a credential without scopes (a browser session), which acts with the user's full access.
    The run-control scopes are not part of the grant: dispatch adds them separately.
    """
    preset = resolve_scopes("full", include_internal_scopes=False)
    if caller_scopes is None or "*" in caller_scopes:
        return list(preset)
    return [scope for scope in preset if not scopes_not_covered(caller_scopes, [scope])]


def caller_scopes(authenticator: object) -> list[str] | None:
    return get_authenticator_scopes(authenticator)


def parent_credential(authenticator: object) -> ParentCredential:
    credential = get_authenticator_user_credential(authenticator)
    if isinstance(credential, PersonalAPIKey):
        return ParentCredential(kind=AgentOperation.ParentCredentialKind.PERSONAL_API_KEY, ref=str(credential.id))
    if credential is not None:
        refresh_token = getattr(credential, "source_refresh_token", None)
        family = getattr(refresh_token, "token_family", None)
        if family is not None:
            return ParentCredential(kind=AgentOperation.ParentCredentialKind.OAUTH_TOKEN_FAMILY, ref=str(family))
        application_id = getattr(credential, "application_id", None)
        if application_id is not None:
            return ParentCredential(kind=AgentOperation.ParentCredentialKind.OAUTH_APPLICATION, ref=str(application_id))
    return ParentCredential(kind=AgentOperation.ParentCredentialKind.NONE, ref=None)


def parent_credential_active(operation: AgentOperation) -> bool:
    """Whether the credential that started the operation can still act. Rotation of an OAuth token does
    not end the operation; revocation of the key, the refresh-token family, or the app grant does."""
    kind, ref = operation.parent_credential_kind, operation.parent_credential_ref
    if kind == AgentOperation.ParentCredentialKind.PERSONAL_API_KEY:
        return PersonalAPIKey.objects.filter(id=ref, user_id=operation.user_id).exists()
    if kind == AgentOperation.ParentCredentialKind.OAUTH_TOKEN_FAMILY:
        return OAuthRefreshToken.objects.filter(
            token_family=ref, user_id=operation.user_id, revoked__isnull=True
        ).exists()
    if kind == AgentOperation.ParentCredentialKind.OAUTH_APPLICATION:
        user = User.objects.filter(id=operation.user_id).first()
        return user is not None and live_oauth_access_tokens(user).filter(application_id=ref).exists()
    return True
