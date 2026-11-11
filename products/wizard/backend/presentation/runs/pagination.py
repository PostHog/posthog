from posthog.api.pagination import FacadeLimitOffsetPagination


class WizardRunPagination(FacadeLimitOffsetPagination):
    default_limit = 100
    max_limit = 100
