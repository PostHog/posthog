"""Repo-qualified schema naming for the multi-repo GitHub source.

Multi-repo sources name their schema rows `owner/repo.endpoint` (e.g. `posthog/posthog.issues`),
mirroring the SQL sources' `schema.table` qualified naming. The persisted
`sync_type_config.schema_metadata` (`source_repository` / `source_endpoint`) is the authoritative
source of a row's location — repo names may themselves contain dots, so name parsing is only a
fallback and always matches against the known endpoint catalog rather than splitting blindly.
Legacy single-repo sources keep bare endpoint names (`issues`); those resolve to the config's
`repository` field.
"""

from typing import TYPE_CHECKING, Any

from products.warehouse_sources.backend.temporal.data_imports.sources.github.settings import ENDPOINTS

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GithubSourceConfig

SCHEMA_METADATA_REPOSITORY_KEY = "source_repository"
SCHEMA_METADATA_ENDPOINT_KEY = "source_endpoint"

# Longest first so `pull_requests` wins over any shorter overlapping endpoint name.
_ENDPOINT_SUFFIXES = sorted(ENDPOINTS, key=lambda name: len(name), reverse=True)


def qualified_schema_name(repository: str, endpoint: str) -> str:
    return f"{repository}.{endpoint}"


def split_schema_name(schema_name: str) -> tuple[str | None, str]:
    """`(repository | None, endpoint)` for a schema row name.

    Matches the longest known endpoint suffix (`.endswith(".issues")` etc.) so repo names
    containing dots parse deterministically. Bare or unrecognized names return them unchanged
    with no repository.
    """
    for endpoint in _ENDPOINT_SUFFIXES:
        if schema_name.endswith(f".{endpoint}"):
            repository = schema_name[: -(len(endpoint) + 1)]
            if repository:
                return repository, endpoint
    return None, schema_name


def schema_repo_endpoint(
    schema_metadata: dict[str, Any] | None,
    schema_name: str,
    legacy_repository: str | None,
) -> tuple[str | None, str]:
    """Config-free `(repository | None, endpoint)` for a schema row: metadata first,
    qualified-name parse second, `legacy_repository` for bare rows last.

    Repository is `None` only for a bare row with no legacy repo to attribute it to. Repo
    names are normalized (stripped, lowercased) since GitHub full names are case-insensitive
    and the repo half of schema names and webhook keys must compare stably. Shared by the
    sync-side resolver here and cross-product readers (engineering_analytics) via the facade.
    Argument order mirrors `resolve_schema_repo_endpoint` (metadata, name) so they don't diverge.
    """
    metadata = schema_metadata if isinstance(schema_metadata, dict) else {}
    repository = metadata.get(SCHEMA_METADATA_REPOSITORY_KEY)
    endpoint = metadata.get(SCHEMA_METADATA_ENDPOINT_KEY)
    if isinstance(repository, str) and repository and isinstance(endpoint, str) and endpoint:
        return repository.strip().lower(), endpoint

    parsed_repository, parsed_endpoint = split_schema_name(schema_name)
    if parsed_repository is not None:
        return parsed_repository.strip().lower(), parsed_endpoint

    normalized_legacy = (legacy_repository or "").strip().lower()
    return (normalized_legacy or None), parsed_endpoint


def resolve_schema_repo_endpoint(
    schema_metadata: dict[str, Any] | None,
    schema_name: str,
    config: "GithubSourceConfig",
) -> tuple[str, str]:
    """`(repository, endpoint)` for a schema row: metadata first, qualified-name parse second,
    the config's legacy `repository` for bare rows last."""
    repository, endpoint = schema_repo_endpoint(schema_metadata, schema_name, config.repository)
    if repository is None:
        # Phrase matches get_non_retryable_errors so an unresolvable row fails permanently
        # with the curated message instead of retrying forever.
        raise ValueError(f"No repositories configured for schema '{schema_name}'")
    return repository, endpoint


def schema_metadata_for(repository: str, endpoint: str) -> dict[str, str]:
    return {
        SCHEMA_METADATA_REPOSITORY_KEY: repository,
        SCHEMA_METADATA_ENDPOINT_KEY: endpoint,
    }
