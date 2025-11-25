"""
GitHub repository data caching using Redis.

Provides caching for repository tree structures and file contents to reduce
GitHub API rate limit usage and improve performance.
"""

import json
import hashlib
from typing import Any

import structlog

from posthog.redis import get_client

logger = structlog.get_logger(__name__)

# Cache TTLs
TREE_CACHE_TTL = 3600  # 1 hour
FILE_CACHE_TTL = 86400  # 24 hours


def _make_tree_cache_key(team_id: int, repo: str, branch: str, sha: str) -> str:
    """
    Generate cache key for repository tree data.

    Args:
        team_id: PostHog team ID
        repo: Repository in format 'owner/repo'
        branch: Branch name
        sha: Commit SHA

    Returns:
        Redis cache key
    """
    return f"live_debugger:repo_tree:{team_id}:{repo}:{branch}:{sha}"


def _make_file_cache_key(team_id: int, repo: str, branch: str, sha: str, path: str) -> str:
    """
    Generate cache key for file content.

    Args:
        team_id: PostHog team ID
        repo: Repository in format 'owner/repo'
        branch: Branch name
        sha: Commit SHA
        path: File path in repository

    Returns:
        Redis cache key
    """
    # Hash the path to keep key length reasonable
    path_hash = hashlib.sha256(path.encode()).hexdigest()[:16]
    return f"live_debugger:file_content:{team_id}:{repo}:{branch}:{sha}:{path_hash}"


def get_cached_tree(team_id: int, repo: str, branch: str, sha: str) -> dict[str, Any] | None:
    """
    Retrieve cached repository tree data.

    Args:
        team_id: PostHog team ID
        repo: Repository in format 'owner/repo'
        branch: Branch name
        sha: Commit SHA

    Returns:
        Cached tree data if found, None otherwise
    """
    try:
        redis_client = get_client()
        cache_key = _make_tree_cache_key(team_id, repo, branch, sha)
        cached_data = redis_client.get(cache_key)

        if cached_data:
            logger.info("Cache hit for repository tree", team_id=team_id, repo=repo, branch=branch, sha=sha[:8])
            return json.loads(cached_data)

        logger.info("Cache miss for repository tree", team_id=team_id, repo=repo, branch=branch, sha=sha[:8])
        return None
    except Exception as e:
        logger.warning("Failed to retrieve cached tree", error=str(e), team_id=team_id, repo=repo)
        return None


def cache_tree(team_id: int, repo: str, branch: str, sha: str, tree_data: dict[str, Any]) -> bool:
    """
    Cache repository tree data.

    Args:
        team_id: PostHog team ID
        repo: Repository in format 'owner/repo'
        branch: Branch name
        sha: Commit SHA
        tree_data: Tree data to cache

    Returns:
        True if cached successfully, False otherwise
    """
    try:
        redis_client = get_client()
        cache_key = _make_tree_cache_key(team_id, repo, branch, sha)
        redis_client.setex(cache_key, TREE_CACHE_TTL, json.dumps(tree_data))
        logger.info("Cached repository tree", team_id=team_id, repo=repo, branch=branch, sha=sha[:8])
        return True
    except Exception as e:
        logger.warning("Failed to cache tree", error=str(e), team_id=team_id, repo=repo)
        return False


def get_cached_file(team_id: int, repo: str, branch: str, sha: str, path: str) -> dict[str, Any] | None:
    """
    Retrieve cached file content.

    Args:
        team_id: PostHog team ID
        repo: Repository in format 'owner/repo'
        branch: Branch name
        sha: Commit SHA
        path: File path in repository

    Returns:
        Cached file data if found, None otherwise
    """
    try:
        redis_client = get_client()
        cache_key = _make_file_cache_key(team_id, repo, branch, sha, path)
        cached_data = redis_client.get(cache_key)

        if cached_data:
            logger.info("Cache hit for file", team_id=team_id, repo=repo, path=path, sha=sha[:8])
            return json.loads(cached_data)

        logger.info("Cache miss for file", team_id=team_id, repo=repo, path=path, sha=sha[:8])
        return None
    except Exception as e:
        logger.warning("Failed to retrieve cached file", error=str(e), team_id=team_id, repo=repo, path=path)
        return None


def cache_file(team_id: int, repo: str, branch: str, sha: str, path: str, file_data: dict[str, Any]) -> bool:
    """
    Cache file content.

    Args:
        team_id: PostHog team ID
        repo: Repository in format 'owner/repo'
        branch: Branch name
        sha: Commit SHA
        path: File path in repository
        file_data: File data to cache

    Returns:
        True if cached successfully, False otherwise
    """
    try:
        redis_client = get_client()
        cache_key = _make_file_cache_key(team_id, repo, branch, sha, path)
        redis_client.setex(cache_key, FILE_CACHE_TTL, json.dumps(file_data))
        logger.info("Cached file content", team_id=team_id, repo=repo, path=path, sha=sha[:8])
        return True
    except Exception as e:
        logger.warning("Failed to cache file", error=str(e), team_id=team_id, repo=repo, path=path)
        return False
