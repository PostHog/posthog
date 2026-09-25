from rest_framework.throttling import UserRateThrottle


class DecisionBurstThrottle(UserRateThrottle):
    scope = "ml_inference_decisions_burst"
    rate = "120/minute"


class DecisionSustainedThrottle(UserRateThrottle):
    scope = "ml_inference_decisions_sustained"
    rate = "1200/hour"
