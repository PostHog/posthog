"""Compatibility shim for git provider file link resolver API classes/functions.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.git_provider_file_link_resolver import (
    GitProviderFileLinksViewSet,
    get_github_file_url,
    get_gitlab_file_url,
    prepare_github_search_query,
    prepare_gitlab_search_query,
)

__all__ = [
    "prepare_github_search_query",
    "prepare_gitlab_search_query",
    "get_github_file_url",
    "get_gitlab_file_url",
    "GitProviderFileLinksViewSet",
]
