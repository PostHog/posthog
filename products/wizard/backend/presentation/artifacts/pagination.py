from posthog.api.pagination import BoundedLimitOffsetPagination


class WizardRunArtifactPagination(BoundedLimitOffsetPagination):
    default_limit = 100
    max_limit = 100
