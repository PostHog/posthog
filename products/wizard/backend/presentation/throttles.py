from django.conf import settings

from rest_framework.throttling import UserRateThrottle


class WizardRunReadThrottle(UserRateThrottle):
    scope = "wizard_run_read"

    def get_rate(self) -> str:
        return settings.WIZARD_RUN_READ_THROTTLE_RATE


class WizardRunCreateThrottle(UserRateThrottle):
    scope = "wizard_run_create"

    def get_rate(self) -> str:
        return settings.WIZARD_RUN_CREATE_THROTTLE_RATE
