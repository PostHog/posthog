"""Rate limits for the deploy endpoints, which CI calls with a personal or project secret API key.

The general API throttles count personal API keys only, so each limit here pairs a per-key budget,
which also counts personal keys, with a per-project budget across all of the project's secret keys.
"""

from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle


# Each deploy can queue a browser run of every journey, so announcing one is limited far below reads.
class JourneyDeployCreateRateThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "user_journeys_deploy_create"
    rate = "60/hour"


class JourneyDeployCreateTeamRateThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "user_journeys_deploy_create_psak_team"
    rate = "120/hour"


# CI polls a deploy until its runs end, so reads allow a poll every few seconds from many jobs.
class JourneyDeployReadRateThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "user_journeys_deploy_read"
    rate = "240/minute"


class JourneyDeployReadTeamRateThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "user_journeys_deploy_read_psak_team"
    rate = "600/minute"
