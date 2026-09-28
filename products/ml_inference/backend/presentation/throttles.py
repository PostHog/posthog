from rest_framework.throttling import UserRateThrottle

from posthog.rate_limit import _TeamBucketRateThrottle


class DecisionBurstThrottle(UserRateThrottle):
    scope = "ml_inference_decisions_burst"
    rate = "60/minute"


class DecisionSustainedThrottle(UserRateThrottle):
    scope = "ml_inference_decisions_sustained"
    rate = "300/hour"


class DecisionProjectSustainedThrottle(_TeamBucketRateThrottle):
    scope = "ml_inference_decisions_project_sustained"
    rate = "600/hour"
