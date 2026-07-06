"""Author-familiarity signal for the reviewer (judgment layer only).

Computes how familiar a PR author is with the code their PR touches, from the
trusted checkout's git history plus one `gh` call. The result feeds the LLM
reviewer as TRUSTED facts so the ownership norms can treat strong familiarity
like owning-team membership.

Security / safety posture:
- This is a judgment-layer signal ONLY. It never touches the deterministic
  gates (deny, size, dismiss, tier assignment). Absence of the signal leaves
  behavior exactly as before — a one-way ratchet.
- Every external call (the single `gh` call, each `git blame`/`git log`) is
  timed out and failure-tolerant. A gh failure returns None (signal absent).
  A per-file git failure degrades that file to nothing, never a crash.
- All git history is read from the checked-out working tree passed in as
  `repo_root`; the base sha is an ancestor of the checkout, so blame resolves.
"""

import re
import json
import time
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from policy import FamiliarityPolicy

# Bounds — keep the work predictable on large PRs.
_GH_TIMEOUT_SECONDS = 30
_GIT_TIMEOUT_SECONDS = 30
_MAX_CHANGED_LINES_PER_FILE = 2000
_MAX_BLAME_FILES = 30
_LOG_SINCE = "18.months"
_SECONDS_PER_DAY = 86400
_TWELVE_MONTHS_DAYS = 365
_TOP_PRIOR_AUTHORS = 2

# PostHog squash-merges; commit subjects end in `(#N)`. Take the last match so a
# subject that mentions another PR mid-text still resolves to its own number.
_SQUASH_PR_RE = re.compile(r"\(#(\d+)\)")

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


# ── Public result ────────────────────────────────────────────────


@dataclass(frozen=True)
class AuthorFamiliarity:
    """How familiar the PR author is with the code the PR modifies."""

    band: str  # STRONG / MODERATE / NONE
    blame_overlap_pct: float
    modified_lines_owned: int
    modified_lines_total: int
    prior_prs_in_paths: int
    days_since_last_touch: int | None
    files_prev_frac: float
    files_prev_count: int
    files_total: int
    capped: bool
    # Display-only hint: top prior authors of the modified lines, by git author
    # name (not login) — used to suggest reviewers when the LLM escalates.
    top_prior_authors: tuple[str, ...]


def familiarity_evidence(fam: AuthorFamiliarity | None) -> dict | None:
    """Serialize an AuthorFamiliarity for the evidence bundle (or null)."""
    if fam is None:
        return None
    return {
        "band": fam.band,
        "blame_overlap_pct": round(fam.blame_overlap_pct, 1),
        "modified_lines_owned": fam.modified_lines_owned,
        "modified_lines_total": fam.modified_lines_total,
        "prior_prs_in_paths": fam.prior_prs_in_paths,
        "days_since_last_touch": fam.days_since_last_touch,
        "files_prev_frac": round(fam.files_prev_frac, 2),
        "files_prev_count": fam.files_prev_count,
        "files_total": fam.files_total,
        "capped": fam.capped,
        "top_prior_authors": list(fam.top_prior_authors),
    }


# ── Author's merged-PR set (one gh call) ─────────────────────────


def _fetch_author_pr_numbers(author_login: str, repo: str) -> set[int] | None:
    """The author's merged-PR numbers, or None on any failure (signal absent)."""
    cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--author",
        author_login,
        "--state",
        "merged",
        "--limit",
        "1000",
        "--json",
        "number,mergedAt",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_GH_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    numbers: set[int] = set()
    for item in data:
        number = item.get("number") if isinstance(item, dict) else None
        if isinstance(number, int) and not isinstance(number, bool):
            numbers.add(number)
    return numbers


def _extract_pr_number(subject: str) -> int | None:
    matches = _SQUASH_PR_RE.findall(subject)
    return int(matches[-1]) if matches else None


# ── Diff parsing (base-side modified lines per file) ─────────────


@dataclass
class _FileDiff:
    old_path: str | None = None
    new_path: str | None = None
    base_modified_lines: list[int] = field(default_factory=list)
    changed_lines: int = 0
    is_binary: bool = False

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""


def _strip_diff_path(raw: str) -> str | None:
    raw = raw.strip()
    if raw == "/dev/null":
        return None
    for prefix in ("a/", "b/"):
        if raw.startswith(prefix):
            return raw[len(prefix) :]
    return raw


def _parse_diff(diff_text: str) -> list[_FileDiff]:
    """Parse a unified diff into per-file base-side modified line numbers.

    Only base-side lines the PR deletes/replaces (unified-diff `-` lines) count:
    a pure addition has no base-side lines to blame, which is correct — blame
    overlap measures how much of the code the PR *changes* the author wrote.
    """
    files: list[_FileDiff] = []
    current: _FileDiff | None = None
    seen_hunk = False
    old_line = 0
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            if current is not None:
                files.append(current)
            current = _FileDiff()
            seen_hunk = False
            old_line = 0
            continue
        if current is None:
            continue
        if line.startswith("Binary files") or line.startswith("GIT binary patch"):
            current.is_binary = True
            continue
        if not seen_hunk and line.startswith("--- "):
            current.old_path = _strip_diff_path(line[4:])
            continue
        if not seen_hunk and line.startswith("+++ "):
            current.new_path = _strip_diff_path(line[4:])
            continue
        hunk = _HUNK_RE.match(line)
        if hunk:
            seen_hunk = True
            old_line = int(hunk.group(1))
            continue
        if not seen_hunk or not line:
            continue
        tag = line[0]
        if tag == "-":
            current.base_modified_lines.append(old_line)
            current.changed_lines += 1
            old_line += 1
        elif tag == "+":
            current.changed_lines += 1
        elif tag == " ":
            old_line += 1
        # "\ No newline at end of file" and anything else: ignore.
    if current is not None:
        files.append(current)
    return files


def _coalesce(lines: list[int]) -> list[tuple[int, int]]:
    """Sorted, de-duplicated line numbers merged into contiguous (start, end) ranges."""
    ranges: list[tuple[int, int]] = []
    for n in sorted(set(lines)):
        if ranges and n == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], n)
        else:
            ranges.append((n, n))
    return ranges


def _select_considered_files(file_diffs: list[_FileDiff]) -> tuple[list[_FileDiff], bool]:
    """Bound the blame work: drop binaries, skip huge files, cap at 30 (largest first).

    Returns (considered, capped) where capped is True when work was dropped for
    a bound (an oversize file or the 30-file cap) — binaries don't count as
    capping, they carry no reviewable lines.
    """
    eligible = [f for f in file_diffs if not f.is_binary and f.changed_lines <= _MAX_CHANGED_LINES_PER_FILE]
    oversize = any(not f.is_binary and f.changed_lines > _MAX_CHANGED_LINES_PER_FILE for f in file_diffs)
    eligible.sort(key=lambda f: f.changed_lines, reverse=True)
    considered = eligible[:_MAX_BLAME_FILES]
    capped = oversize or len(eligible) > _MAX_BLAME_FILES
    return considered, capped


# ── blame overlap ────────────────────────────────────────────────


def _parse_blame_porcelain(text: str) -> list[tuple[str | None, str | None]]:
    """Parse `git blame --line-porcelain` into (author_name, summary) per line."""
    entries: list[tuple[str | None, str | None]] = []
    author: str | None = None
    summary: str | None = None
    for line in text.splitlines():
        if line.startswith("author "):
            author = line[len("author ") :]
        elif line.startswith("summary "):
            summary = line[len("summary ") :]
        elif line.startswith("\t"):
            entries.append((author, summary))
            author = None
            summary = None
    return entries


def _blame_range(
    base_sha: str, path: str, start: int, end: int, repo_root: Path
) -> list[tuple[str | None, str | None]] | None:
    """Blame one base-side range; None on any error (degrade this range)."""
    cmd = ["git", "blame", base_sha, "-L", f"{start},{end}", "--line-porcelain", "--", path]
    try:
        result = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return _parse_blame_porcelain(result.stdout)


def _blame_overlap(
    considered: list[_FileDiff], base_sha: str, author_prs: set[int], repo_root: Path
) -> tuple[int, int, tuple[str, ...]]:
    """(owned lines, total blamed lines, top prior author names)."""
    owned = 0
    total = 0
    author_line_counts: Counter[str] = Counter()
    for file_diff in considered:
        blame_path = file_diff.old_path
        if not blame_path:
            continue
        for start, end in _coalesce(file_diff.base_modified_lines):
            entries = _blame_range(base_sha, blame_path, start, end, repo_root)
            if entries is None:
                continue
            for author_name, summary in entries:
                total += 1
                pr_number = _extract_pr_number(summary or "")
                if pr_number is not None and pr_number in author_prs:
                    owned += 1
                elif author_name:
                    # Reviewer-suggestion hint: count only lines the PR author
                    # does NOT own — suggesting the author to themselves is noise.
                    author_line_counts[author_name] += 1
    top_authors = tuple(name for name, _ in author_line_counts.most_common(_TOP_PRIOR_AUTHORS))
    return owned, total, top_authors


# ── prior PRs / last touch / previously-modified files ───────────


def _path_specs(paths: list[str]) -> list[str]:
    """Directory pathspecs for the changed files (a root-level file maps to itself)."""
    specs: set[str] = set()
    for path in paths:
        parent = str(PurePosixPath(path).parent)
        specs.add(path if parent == "." else parent)
    return sorted(specs)


def _prior_prs_in_paths(paths: list[str], author_prs: set[int], repo_root: Path, now: float) -> tuple[int, int | None]:
    """(author's merged PRs touching these paths in 12 months, days since last touch)."""
    specs = _path_specs(paths)
    if not specs:
        return 0, None
    cmd = ["git", "log", f"--since={_LOG_SINCE}", "--format=%ct%x09%s", "--", *specs]
    try:
        result = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return 0, None
    if result.returncode != 0:
        return 0, None

    cutoff = now - _TWELVE_MONTHS_DAYS * _SECONDS_PER_DAY
    prs_recent: set[int] = set()
    last_touch: int | None = None
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        ct_str, subject = line.split("\t", 1)
        try:
            commit_time = int(ct_str)
        except ValueError:
            continue
        pr_number = _extract_pr_number(subject)
        if pr_number is None or pr_number not in author_prs:
            continue
        if last_touch is None or commit_time > last_touch:
            last_touch = commit_time
        if commit_time >= cutoff:
            prs_recent.add(pr_number)

    days_since = int((now - last_touch) // _SECONDS_PER_DAY) if last_touch is not None else None
    return len(prs_recent), days_since


def _files_previously_modified(paths: list[str], author_prs: set[int], repo_root: Path) -> tuple[int, int]:
    """(changed files the author previously modified, total changed files considered)."""
    if not paths:
        return 0, 0
    count = 0
    for path in paths:
        cmd = ["git", "log", "-n", "50", "--format=%s", "--", path]
        try:
            result = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        for subject in result.stdout.splitlines():
            pr_number = _extract_pr_number(subject)
            if pr_number is not None and pr_number in author_prs:
                count += 1
                break
    return count, len(paths)


# ── Band ─────────────────────────────────────────────────────────


def _band(
    blame_overlap_pct: float,
    prior_prs_in_paths: int,
    files_prev_frac: float,
    days_since_last_touch: int | None,
    thresholds: FamiliarityPolicy,
) -> str:
    """STRONG / MODERATE / NONE from the policy thresholds (numbers-only diff to tune)."""
    strong = thresholds.strong
    moderate = thresholds.moderate

    strong_blame = blame_overlap_pct >= strong.min_blame_overlap_pct
    strong_alt = (
        prior_prs_in_paths >= strong.alt_min_prior_prs
        and files_prev_frac >= strong.alt_min_files_prev_frac
        and days_since_last_touch is not None
        and days_since_last_touch <= strong.alt_max_days_since_touch
    )
    if strong_blame or strong_alt:
        return "STRONG"

    if (
        prior_prs_in_paths >= moderate.min_prior_prs
        and days_since_last_touch is not None
        and days_since_last_touch <= moderate.max_days_since_touch
    ):
        return "MODERATE"
    return "NONE"


# ── Orchestration ────────────────────────────────────────────────


def _read_diff(diff_path: Path) -> str:
    try:
        return diff_path.read_text()
    except OSError:
        return ""


def compute_familiarity(
    author_login: str,
    diff_path: Path,
    base_sha: str,
    repo: str,
    repo_root: Path,
    thresholds: FamiliarityPolicy,
    *,
    now: float | None = None,
) -> AuthorFamiliarity | None:
    """Compute the author's familiarity with the code the PR modifies.

    Returns None only when the signal is genuinely absent (the gh call failed) —
    every other degradation yields a populated result (possibly band NONE), so
    the reviewer sees either a trustworthy fact or nothing at all.
    """
    author_prs = _fetch_author_pr_numbers(author_login, repo)
    if author_prs is None:
        return None

    now = time.time() if now is None else now
    file_diffs = _parse_diff(_read_diff(diff_path))
    considered, capped = _select_considered_files(file_diffs)
    considered_paths = [f.path for f in considered if f.path]

    owned, total, top_authors = _blame_overlap(considered, base_sha, author_prs, repo_root)
    blame_overlap_pct = (100.0 * owned / total) if total else 0.0

    prior_prs, days_since = _prior_prs_in_paths(considered_paths, author_prs, repo_root, now)
    files_prev_count, files_total = _files_previously_modified(considered_paths, author_prs, repo_root)
    files_prev_frac = (files_prev_count / files_total) if files_total else 0.0

    band = _band(blame_overlap_pct, prior_prs, files_prev_frac, days_since, thresholds)

    return AuthorFamiliarity(
        band=band,
        blame_overlap_pct=blame_overlap_pct,
        modified_lines_owned=owned,
        modified_lines_total=total,
        prior_prs_in_paths=prior_prs,
        days_since_last_touch=days_since,
        files_prev_frac=files_prev_frac,
        files_prev_count=files_prev_count,
        files_total=files_total,
        capped=capped,
        top_prior_authors=top_authors,
    )
