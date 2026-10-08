from rest_framework.pagination import LimitOffsetPagination


class WizardRunArtifactPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 100
