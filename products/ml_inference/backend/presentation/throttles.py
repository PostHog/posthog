from django.conf import settings

from rest_framework.throttling import UserRateThrottle


class DecisionBurstRateThrottle(UserRateThrottle):
    scope = "ml_inference_decisions_burst"

    def get_rate(self) -> str:
        return settings.ML_INFERENCE_DECISIONS_BURST_RATE


class DecisionSustainedRateThrottle(UserRateThrottle):
    scope = "ml_inference_decisions_sustained"

    def get_rate(self) -> str:
        return settings.ML_INFERENCE_DECISIONS_SUSTAINED_RATE
