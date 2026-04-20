"""Compatibility shim for error tracking presentation viewsets.

Canonical modules:
- `products.error_tracking.backend.presentation.external_references`
- `products.error_tracking.backend.presentation.git_provider_file_link_resolver`
"""

from products.error_tracking.backend.presentation.external_references import ErrorTrackingExternalReferenceViewSet
from products.error_tracking.backend.presentation.git_provider_file_link_resolver import (
    GitProviderFileLinksViewSet,
    get_github_file_url,
    get_gitlab_file_url,
    prepare_github_search_query,
    prepare_gitlab_search_query,
)

__all__ = [
    "ErrorTrackingExternalReferenceViewSet",
    "prepare_github_search_query",
    "prepare_gitlab_search_query",
    "get_github_file_url",
    "get_gitlab_file_url",
    "GitProviderFileLinksViewSet",
]
