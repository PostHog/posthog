from typing import Any

from posthog.auth import ProjectSecretAPIKeyAuthentication, WorkloadAccessTokenAuthentication
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle


class _PushSendThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    """Counts per key, and per user for a caller without one, such as a session or an OAuth token."""

    reads_history_from_primary = True

    def allow_request(self, request: Any, view: Any) -> bool:
        return self._allow_request_internal(request, view, personal_api_key_only=False)

    def get_cache_key(self, request: Any, view: Any) -> str:
        auth = request.successful_authenticator
        # Only the key that authenticated counts. A workload token is also a bearer value, and it can be minted again.
        if (
            isinstance(auth, ProjectSecretAPIKeyAuthentication)
            or getattr(auth, "personal_api_key_hash", None) is not None
        ):
            return super().get_cache_key(request, view)
        # A workload token acts as an organization owner, and its sends must not spend that person's limit.
        user_id = None if isinstance(auth, WorkloadAccessTokenAuthentication) else getattr(request.user, "pk", None)
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
