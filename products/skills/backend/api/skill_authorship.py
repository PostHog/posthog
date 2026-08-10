from dataclasses import dataclass

from django.http import HttpRequest

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.helpers.impersonation import get_original_user_from_session, is_impersonated
from posthog.models import User

from ..models.skills import LLMSkillProvenance


@dataclass(frozen=True, kw_only=True)
class SkillAuthorship:
    """Who a newly created skill should be credited to, and where it came from."""

    provenance: str
    created_by: User


def resolve_skill_authorship(request: HttpRequest, *, requesting_user: User) -> SkillAuthorship:
    """Resolve the author and provenance of a skill created by this request.

    PostHog staff author skills for a customer through an impersonation session, which swaps the
    request's user to the customer being impersonated. Crediting that user would attribute a skill
    to someone who did not write it, so the operator behind the session is credited instead and the
    row is stamped `posthog` — that stamp is what puts it in the customer's "Written for you" tab.

    Both impersonation routes are covered by `is_impersonated`: a browser session (a CSM using the
    skills editor) and an OAuth token minted during one (a CSM's agent using the MCP tools). If the
    operator can't be recovered from either, the skill is credited to the requesting user as an
    ordinary team-authored skill rather than stamped with an author we can't name.
    """
    if not is_impersonated(request):
        return SkillAuthorship(provenance="", created_by=requesting_user)

    operator = _impersonating_operator(request)
    if operator is None:
        return SkillAuthorship(provenance="", created_by=requesting_user)

    return SkillAuthorship(provenance=LLMSkillProvenance.POSTHOG, created_by=operator)


def _impersonating_operator(request: HttpRequest) -> User | None:
    authenticator = getattr(request, "successful_authenticator", None)
    if isinstance(authenticator, OAuthAccessTokenAuthentication):
        # Falls through rather than returning: an OAuth call can carry a loginas session cookie
        # without the token itself being impersonation-minted, and `is_impersonated` accepts either.
        operator = authenticator.access_token.impersonated_by
        if operator is not None:
            return operator
    return get_original_user_from_session(request)
