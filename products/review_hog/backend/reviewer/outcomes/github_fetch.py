"""The two GitHub reads outcome classification needs, through the gated egress client.

Both are read-only and metered against the installation's budget like every other ReviewHog call.
"""

import logging
from typing import Any

from products.review_hog.backend.reviewer.tools.github_client import github_api_get_paginated, github_api_request
from products.review_hog.backend.reviewer.tools.github_meta import GITHUB_COMPARE_FILES_CAP

logger = logging.getLogger(__name__)


def fetch_compare_files(
    *, owner: str, repo: str, base_sha: str, head_sha: str, token: str, installation_id: str | None = None
) -> list[dict[str, Any]]:
    """The changed files (with ``patch``) between ``base_sha`` and ``head_sha`` — the commits that
    landed after review.

    One call; GitHub caps the compare at 300 files with no pagination, so a very large post-review
    diff is truncated. We log the truncation so a finding in a dropped file reading as ``ignored`` is
    never silent.
    """
    comparison = github_api_request(
        "GET",
        f"/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}",
        token=token,
        installation_id=installation_id,
        endpoint="/repos/{owner}/{repo}/compare/{basehead}",
    ).json()
    files: list[dict[str, Any]] = comparison.get("files") or []
    if len(files) >= GITHUB_COMPARE_FILES_CAP:
        logger.warning(
            "Compare %s/%s %s...%s hit GitHub's %d-file cap; findings in dropped files may read as ignored",
            owner,
            repo,
            base_sha[:12],
            head_sha[:12],
            GITHUB_COMPARE_FILES_CAP,
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
