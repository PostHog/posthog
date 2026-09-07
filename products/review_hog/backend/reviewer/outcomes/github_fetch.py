"""The two GitHub reads outcome classification needs, through the gated egress client.

Both are read-only and metered against the installation's budget like every other ReviewHog call.
"""

import logging
from itertools import islice
from typing import Any

from products.review_hog.backend.reviewer.tools.github_client import github_api_get_paginated, github_api_request
from products.review_hog.backend.reviewer.tools.github_meta import GITHUB_COMPARE_FILES_CAP

logger = logging.getLogger(__name__)

# Ceiling on inline review comments read for one report, at 100 per request. Comment volume is set by
# whoever comments on the PR, so without a bound a thread long enough to span hundreds of pages spends
# the installation's shared egress budget on a single report. Exhausting it stops the team's whole
# sweep with this report still unstamped, so the next hourly sweep drains the same pages again and the
# team never gets past it. 1,000 covers any real review thread.
_MAX_REVIEW_COMMENTS = 1_000


def fetch_compare_files(
    *, owner: str, repo: str, base_sha: str, head_sha: str, token: str, installation_id: str | None = None
) -> list[dict[str, Any]]:
    """The changed files (with ``patch``) between ``base_sha`` and ``head_sha`` — the commits that
    landed after review.

    GitHub caps this at 300 changed files for the entire comparison and returns them only on the
    first page: `page` / `per_page` paginate the compare's `commits` array, not its `files`, so
    re-requesting later pages yields no further files (only "Get a commit" pages files, up to 3,000).
    A post-review merge of the default branch can exceed the cap, and a finding in a dropped file
    then looks untouched and classifies as ``ignored``, so warn rather than let that gap be silent.
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
    """The PR's inline review comments, each carrying ``in_reply_to_id`` and a ``reactions`` summary —
    the one read that backs both "which findings were published" and the reacted signal.

    Capped at ``_MAX_REVIEW_COMMENTS``; the paginator is lazy, so stopping early also stops the
    requests. GitHub returns these oldest-first, which is the order that degrades best: ReviewHog's
    own finding comments are posted before any reply to them, so a truncated read keeps the comments
    findings are paired by and can only lose late replies. A finding whose reply was cut then reads as
    judged or ignored rather than reacted, so say so rather than under-reporting engagement silently.
    """
    # One over the cap so a full slice is distinguishable from an exactly-full one.
    comments = list(
        islice(
            github_api_get_paginated(
                f"/repos/{owner}/{repo}/pulls/{pr_number}/comments",
                token=token,
                installation_id=installation_id,
                endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/comments",
            ),
            _MAX_REVIEW_COMMENTS + 1,
        )
    )
    if len(comments) > _MAX_REVIEW_COMMENTS:
        logger.warning(
            "PR %s/%s#%d has more than %d review comments; classifying on the oldest %d, so a late "
            "reply may read as ignored instead of reacted",
            owner,
            repo,
            pr_number,
            _MAX_REVIEW_COMMENTS,
            _MAX_REVIEW_COMMENTS,
        )
        return comments[:_MAX_REVIEW_COMMENTS]
    return comments
