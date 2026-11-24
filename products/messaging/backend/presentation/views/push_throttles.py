from typing import Any

from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.rate_limit import (
    PersonalOrProjectSecretApiKeyRateThrottle,
    ProjectSecretApiKeyTeamRateThrottle,
    hashed_personal_api_key_for_throttling,
)


class _PushSendThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    """Counts per key, and per user for a caller without one, such as a session or an OAuth token."""

    reads_history_from_primary = True

    def allow_request(self, request: Any, view: Any) -> bool:
        return self._allow_request_internal(request, view, personal_api_key_only=False)

    def get_cache_key(self, request: Any, view: Any) -> str:
        if (
            isinstance(request.successful_authenticator, ProjectSecretAPIKeyAuthentication)
            or hashed_personal_api_key_for_throttling(request) is not None
        ):
            return super().get_cache_key(request, view)
        # A caller that is not a user, such as a workload token, has no pk, so its project is counted.
        user_id = getattr(request.user, "pk", None)
        ident = f"user:{user_id}" if user_id is not None else f"team:{view.team_id}"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class TransactionalPushBurstThrottle(_PushSendThrottle):
    scope = "transactional_push_burst"
    rate = "600/minute"


class TransactionalPushSustainedThrottle(_PushSendThrottle):
    scope = "transactional_push_sustained"
    rate = "20000/hour"


class TransactionalPushTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    """Per-team aggregate across all of a project's secret API keys."""

    scope = "transactional_push_psak_team_burst"
    reads_history_from_primary = True
    rate = "600/minute"


class TransactionalPushTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "transactional_push_psak_team_sustained"
    reads_history_from_primary = True
    rate = "20000/hour"


def transactional_push_throttles() -> list[
    PersonalOrProjectSecretApiKeyRateThrottle | ProjectSecretApiKeyTeamRateThrottle
]:
    # Single and batch sends share these scopes. Email has its own, so neither spends the other's limit.
    return [
        TransactionalPushBurstThrottle(),
        TransactionalPushSustainedThrottle(),
        TransactionalPushTeamBurstThrottle(),
        TransactionalPushTeamSustainedThrottle(),
    ]
