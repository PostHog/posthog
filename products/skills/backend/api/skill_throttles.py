"""Rate limits for the skill endpoints that cost more than a plain read."""

from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.auth import PersonalAPIKeyAuthentication
from posthog.rate_limit import BurstRateThrottle, PersonalApiKeyOrUserRateThrottle, SustainedRateThrottle


class _CommunityPublishThrottle(PersonalApiKeyOrUserRateThrottle):
    # Publishing opens a pull request in a public repo, so the ceiling is "a handful, by hand", not
    # the API-shaped hundreds-per-minute of BurstRateThrottle. That one also extends
    # PersonalApiKeyRateThrottle, which ignores session traffic.
    def get_cache_key(self, request, view):
        # Per team, not per credential. The inherited key prefers the personal API key hash, so one
        # member holding several keys would get a fresh budget with each of them — and the skill
        # being published belongs to the team either way.
        team_id = self.safely_get_team_id_from_view(view)
        if team_id is None:
            return super().get_cache_key(request, view)
        return self.cache_format % {"scope": self.scope, "ident": f"team-{team_id}"}


class CommunityPublishBurstThrottle(_CommunityPublishThrottle):
    scope = "community_skill_publish_burst"
    rate = "6/hour"


class CommunityPublishSustainedThrottle(_CommunityPublishThrottle):
    scope = "community_skill_publish_sustained"
    rate = "20/day"


class _SkillUserThrottle(PersonalApiKeyOrUserRateThrottle):
    """Per-credential throttling for skill endpoints, including OAuth and sessions.

    The general BurstRateThrottle/SustainedRateThrottle only count personal-API-key traffic, so an
    OAuth or session caller would reach expensive skill operations unthrottled.
    PersonalApiKeyOrUserRateThrottle counts every auth method, but its inherited key identifies
    session and OAuth callers by project, so one user's burst would 429 every other user in the
    project. Those callers get a per-user bucket instead; a personal API key keeps its own.
    """

    def get_cache_key(self, request: Request, view: APIView) -> str:
        if not request.user.is_authenticated or isinstance(
            request.successful_authenticator, PersonalAPIKeyAuthentication
        ):
            return super().get_cache_key(request, view)
        return self.cache_format % {"scope": self.scope, "ident": f"user:{request.user.pk}"}


class SkillBundleBurstThrottle(_SkillUserThrottle):
    # A sandbox fetches the bundle once at session start, so 30/minute clears a burst of concurrent
    # starts for one user while still catching a scripted loop hammering the zip build.
    scope = "skills_bundle_burst"
    rate = "30/minute"


class SkillBundleSustainedThrottle(_SkillUserThrottle):
    # A few hundred session starts an hour per user is well beyond normal use and short of what
    # sustained abuse of the 5 MB zip build could cost unthrottled.
    scope = "skills_bundle_sustained"
    rate = "300/hour"


class SkillSearchBurstThrottle(_SkillUserThrottle):
    scope = "skills_search_burst"
    rate = BurstRateThrottle.rate


class SkillSearchSustainedThrottle(_SkillUserThrottle):
    scope = "skills_search_sustained"
    rate = SustainedRateThrottle.rate
