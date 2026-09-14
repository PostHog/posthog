"""Markdown rendering for PR comments. Pure formatting — no GitHub calls, no writes."""

from __future__ import annotations

import re
import html
from collections import Counter
from dataclasses import dataclass

from django.conf import settings
from django.db import models as db_models

from ..db import READER_DB
from ..facade.enums import ReviewState, SnapshotResult
from ..models import Artifact, Repo, Run, RunSnapshot
from ..storage import ArtifactStorage


def _format_change_counts(changed: int, new: int, removed: int) -> str:
    """'N changed, M new, K removed', omitting zero counts; '' when all are zero."""
    parts = []
    if changed:
        parts.append(f"{changed} changed")
    if new:
        parts.append(f"{new} new")
    if removed:
        parts.append(f"{removed} removed")
    return ", ".join(parts)


_MARKDOWN_ESCAPE_CHARS = r"\`*_{}[]()#+-.!|<>~"


def _escape_markdown(value: str) -> str:
    """Escape GitHub-flavored markdown control characters in user-supplied text."""
    return "".join(f"\\{c}" if c in _MARKDOWN_ESCAPE_CHARS else c for c in value)


@dataclass(frozen=True)
class _Approver:
    label: str
    is_github_login: bool


# A reviewer should be able to eyeball the approved snapshots straight from the PR.
# GitHub can't render base64 data URIs (its markdown sanitizer strips them) and the
# user-attachments upload path needs a browser session we don't have, so we embed
# presigned object-storage URLs and let GitHub's image proxy (camo) fetch + cache
# them. That proxy fetch can happen well after the comment is posted, so the URL
# must outlive the default hour — use the S3 SigV4 maximum.
_COMMENT_IMAGE_URL_EXPIRATION = 60 * 60 * 24 * 7  # 7 days

_COMMENT_IMAGE_WIDTH = 320

# Keep the comment readable: show the first N snapshots and link out for the rest.
_MAX_COMMENT_IMAGES = 8


def _comment_image_url(repo: Repo, artifact: Artifact | None) -> str | None:
    """Presigned URL for the full-resolution snapshot image in a PR comment.

    Serves the original artifact (not the thumbnail) so the embedded image opens at full
    resolution when clicked — GitHub constrains the rendered size via the ``<img width>``
    attribute but links the original. Returns None when the artifact is missing or object
    storage is disabled — the caller renders an empty cell in that case.
    """
    if artifact is None:
        return None
    storage = ArtifactStorage(str(repo.id))
    return storage.get_presigned_download_url(artifact.content_hash, expiration=_COMMENT_IMAGE_URL_EXPIRATION)


_TABLE_BREAKING_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _run_url(run: Run, repo: Repo) -> str:
    """Link to the run page in PostHog."""
    return f"{settings.SITE_URL}/project/{repo.team_id}/visual_review/runs/{run.id}"


def _snapshot_url(run: Run, repo: Repo, snapshot: RunSnapshot) -> str:
    """Deep link straight to a single snapshot on the run page."""
    return f"{_run_url(run, repo)}?snapshot={snapshot.id}"


def _snapshot_name_cell(identifier: str, suffix: str = "") -> str:
    """Render a snapshot identifier as a single-line table cell (code span, pipe-safe).

    Identifiers come from the run manifest without newline validation, so collapse
    control characters (newlines, tabs, etc.) to spaces first — otherwise a
    malformed or user-controlled story name could break out of the table row and
    inject markdown/HTML into the comment. Then strip backticks and escape pipes so
    it stays inside the code span and the cell.
    """
    safe = _TABLE_BREAKING_CHARS_RE.sub(" ", identifier).replace("`", "").replace("|", "\\|")
    return f"`{safe}`{suffix}"


def _snapshot_link_cell(run: Run, repo: Repo, snapshot: RunSnapshot, suffix: str = "") -> str:
    """Snapshot identifier linked to its deep link on the run page, so a reviewer can jump
    straight to that snapshot rather than the run as a whole."""
    return f"[{_snapshot_name_cell(snapshot.identifier)}]({_snapshot_url(run, repo, snapshot)}){suffix}"


def _image_cell(url: str | None, alt: str) -> str:
    """Render an image (or an empty placeholder) for a before/after table cell.

    The image is constrained to ``_COMMENT_IMAGE_WIDTH`` so the table stays compact, but
    ``src`` points at the full-resolution original — GitHub opens that original when the
    image is clicked.
    """
    if not url:
        return "_(none)_"
    # Escape both attributes — a URL containing a quote would otherwise break out of src.
    src = html.escape(url, quote=True)
    return f'<img src="{src}" width="{_COMMENT_IMAGE_WIDTH}" alt="{html.escape(alt, quote=True)}">'


_IMAGE_TABLE_HEADER = "| Snapshot | Before | After |\n| --- | --- | --- |"

_REVIEWABLE_RESULTS = (SnapshotResult.CHANGED, SnapshotResult.NEW, SnapshotResult.REMOVED)


def _reviewable_snapshot_qs(run: Run) -> db_models.QuerySet[RunSnapshot]:
    return run.snapshots.using(READER_DB).filter(result__in=_REVIEWABLE_RESULTS)


def _postable_snapshot_qs(run: Run) -> db_models.QuerySet[RunSnapshot]:
    """Reviewable snapshots minus the ones an approval comment should not surface.

    Quarantined snapshots are suppressed by policy and tolerated ones are
    intentional known drift, so neither belongs in the comment.
    """
    return _reviewable_snapshot_qs(run).exclude(is_quarantined=True).exclude(review_state=ReviewState.TOLERATED)


def _build_snapshot_image_tables(run: Run, repo: Repo) -> str:
    """Before/after image tables for the approved snapshots.

    Changed and removed snapshots share one table (removed ones leave the *after*
    cell empty); new snapshots get their own table (empty *before* cell). Capped
    at ``_MAX_COMMENT_IMAGES`` rows total, prioritizing changed/removed diffs;
    anything beyond links back to PostHog. Returns "" when no image could be
    resolved (e.g. object storage disabled) so the comment stays text-only.
    """
    snapshots = list(
        _postable_snapshot_qs(run)
        .select_related(
            "current_artifact",
            "baseline_artifact",
        )
        .order_by("identifier")
    )
    if not snapshots:
        return ""

    # Changed/removed first — they carry a baseline diff a reviewer most needs to
    # see — then new snapshots fill whatever's left of the image budget.
    changed = [s for s in snapshots if s.result in (SnapshotResult.CHANGED, SnapshotResult.REMOVED)]
    new = [s for s in snapshots if s.result == SnapshotResult.NEW]

    total = len(changed) + len(new)
    shown_changed = changed[:_MAX_COMMENT_IMAGES]
    shown_new = new[: max(0, _MAX_COMMENT_IMAGES - len(shown_changed))]
    shown = len(shown_changed) + len(shown_new)

    any_image = False

    def cell(artifact: Artifact | None, alt: str) -> str:
        nonlocal any_image
        url = _comment_image_url(repo, artifact)
        if url:
            any_image = True
        return _image_cell(url, alt)

    def row(s: RunSnapshot, before: Artifact | None) -> str:
        suffix = " _(removed)_" if s.result == SnapshotResult.REMOVED else ""
        name = _snapshot_link_cell(run, repo, s, suffix)
        return f"| {name} | {cell(before, 'before')} | {cell(s.current_artifact, 'after')} |"

    changed_rows = [row(s, s.baseline_artifact) for s in shown_changed]
    new_rows = [row(s, None) for s in shown_new]

    if not any_image:
        return ""

    def table(heading: str, rows: list[str]) -> str:
        return "\n".join((f"**{heading}**", "", _IMAGE_TABLE_HEADER, *rows))

    sections = [table(heading, rows) for heading, rows in (("Changed", changed_rows), ("New", new_rows)) if rows]
    if shown < total:
        sections.append(f"…and {total - shown} more — [view all in PostHog]({_run_url(run, repo)}).")

    return "\n\n".join(sections)


def _build_approval_comment_body(run: Run, repo: Repo, approver: _Approver | None, add_images: bool = False) -> str:
    """Build the markdown body of the post-approval PR comment.

    Always a textual summary of what changed. When ``add_images`` is set, a
    before/after table of the approved snapshot images is appended so another
    reviewer can eyeball them without leaving the PR (omitted when no image can
    be resolved).
    """
    counts = Counter(_postable_snapshot_qs(run).values_list("result", flat=True))
    suppressed_only = not counts and _reviewable_snapshot_qs(run).exists()

    if approver is None:
        approver_text = "a reviewer"
    elif approver.is_github_login:
        approver_text = f"@{approver.label}"
    else:
        approver_text = _escape_markdown(approver.label)
    baseline_sha = run.metadata.get("baseline_commit_sha")
    sha_text = f" — baseline updated in `{baseline_sha[:7]}`" if isinstance(baseline_sha, str) and baseline_sha else ""

    summary = _format_change_counts(
        counts[SnapshotResult.CHANGED], counts[SnapshotResult.NEW], counts[SnapshotResult.REMOVED]
    )

    sections = [
        f"✅ **Visual changes approved** by {approver_text}{sha_text}.",
        f"[View this run in PostHog]({_run_url(run, repo)})",
    ]
    if summary:
        sections.append(f"{summary}.")
    elif suppressed_only:
        sections.append("All visual changes in this run were quarantined or tolerated.")
    if add_images:
        tables = _build_snapshot_image_tables(run, repo)
        if tables:
            sections.append(tables)

    return "\n\n".join(sections) + "\n"


def _resolve_approver(user_id: int | None) -> _Approver | None:
    """Resolve the approver's identity for the PR comment.

    Prefers a verified GitHub login (safe to mention with `@`); otherwise
    falls back to email local-part or first name, which the caller must
    treat as untrusted markdown.
    """
    if user_id is None:
        return None

    from posthog.models.user import User
    from posthog.models.user_integration import UserGitHubIntegration, UserIntegration

    gh = (
        UserIntegration.objects.filter(user_id=user_id, kind=UserIntegration.IntegrationKind.GITHUB)
        .order_by("-created_at")
        .first()
    )
    if gh is not None:
        github_login = UserGitHubIntegration(gh).github_login
        if github_login:
            return _Approver(label=github_login, is_github_login=True)

    user = User.objects.filter(id=user_id).only("email", "first_name").first()
    if user is None:
        return None
    if user.email and "@" in user.email:
        return _Approver(label=user.email.split("@", 1)[0], is_github_login=False)
    if user.first_name:
        return _Approver(label=user.first_name, is_github_login=False)
    return None
