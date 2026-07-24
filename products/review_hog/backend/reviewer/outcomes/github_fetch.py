"""The two GitHub reads outcome classification needs, through the gated egress client.

Both are read-only and metered against the installation's budget like every other ReviewHog call.
"""

import logging
from typing import Any

from products.review_hog.backend.reviewer.tools.github_client import github_api_get_paginated, github_api_request
from products.review_hog.backend.reviewer.tools.github_meta import GITHUB_COMPARE_FILES_CAP

logger = logging.getLogger(__name__)

# Compares paginate their `files` array at GitHub's 300-file cap per page. 10 pages (3,000 files)
# comfortably covers a post-review master merge without letting one pathological compare eat the
# installation's egress budget.
_MAX_COMPARE_PAGES = 10


def fetch_compare_files(
    *, owner: str, repo: str, base_sha: str, head_sha: str, token: str, installation_id: str | None = None
) -> list[dict[str, Any]]:
    """The changed files (with ``patch``) between ``base_sha`` and ``head_sha`` — the commits that
    landed after review.

    GitHub returns at most 300 files per compare page, so we paginate until a short page — a
    post-review merge of the default branch routinely exceeds one page, and truncated evidence would
    durably classify findings in dropped files as ``ignored``. Beyond ``_MAX_COMPARE_PAGES`` we log
    loudly and classify on what we have rather than re-sweeping a compare that will never shrink.
    """
    files: list[dict[str, Any]] = []
    for page in range(1, _MAX_COMPARE_PAGES + 1):
        comparison = github_api_request(
            "GET",
            f"/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}",
            token=token,
            installation_id=installation_id,
            endpoint="/repos/{owner}/{repo}/compare/{basehead}",
            params={"page": page},
        ).json()
        chunk: list[dict[str, Any]] = comparison.get("files") or []
        files.extend(chunk)
        if len(chunk) < GITHUB_COMPARE_FILES_CAP:
            return files
    logger.warning(
        "Compare %s/%s %s...%s still capped after %d pages (%d files); findings in dropped files may read as ignored",
        owner,
        repo,
        base_sha[:12],
        head_sha[:12],
        _MAX_COMPARE_PAGES,
        len(files),
    )
    return files


def fetch_review_comments(
    *, owner: str, repo: str, pr_number: int, token: str, installation_id: str | None = None
) -> list[dict[str, Any]]:
    """Every inline review comment on the PR, each carrying ``in_reply_to_id`` and a ``reactions``
    summary — the one read that backs both "which findings were published" and the reacted signal."""
    return list(
        github_api_get_paginated(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/comments",
            token=token,
            installation_id=installation_id,
            endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/comments",
        )
    )
