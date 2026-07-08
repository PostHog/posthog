import re
import logging

from github import Github, GithubException, PullRequest

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRFileUpdate, PRMetadata

logger = logging.getLogger(__name__)


def _format_diff_section(filename: str, status: str, patch: str) -> str:
    """One reviewed file's raw GitHub patch behind a clear header, for the point-in-time snapshot.

    GitHub omits the patch for binary or very large files, so an empty patch is recorded explicitly
    rather than silently dropped.
    """
    body = patch if patch.strip() else "(no patch available — file too large or binary)"
    return f"=== {filename} [{status}] ===\n{body}"


class PRFilter:
    @staticmethod
    def is_test_file(filename: str) -> bool:
        """Check if a filename matches common test file patterns.

        Every pattern is anchored to a path/name boundary — a bare "test" substring match
        would silently exclude production files like `latest-versions.ts` or
        `0132_team_test_account_filters.py` from review. When in doubt, don't exclude:
        reviewing a test file is cheap, silently skipping production code is not.
        """
        test_patterns = [
            r"(^|/)test[_\-]",  # test_-/test--prefixed filenames, in any directory
            r"[_\-]tests?\.",  # _test./-test./_tests.-suffixed filenames
            r"\.test\.",  # .test. files (common in JS)
            r"\.spec\.",  # .spec. files (common in JS)
            r"(^|/)tests?/",  # files under a test/ or tests/ directory
            r"(^|/)__tests__/",  # files under a __tests__/ directory
        ]

        return any(re.search(pattern, filename, re.IGNORECASE) for pattern in test_patterns)

    @staticmethod
    def is_filtered_file(filename: str) -> bool:
        """Check if a filename should be filtered out from PR analysis.

        Filters out lock files, build artifacts, and other auto-generated files
        that don't need LLM review.
        """
        filter_patterns = [
            # Lock files
            r".*\.lock$",  # package-lock.json, yarn.lock, Cargo.lock, etc.
            r".*lock\.json$",  # package-lock.json specifically
            r".*lock\.yaml$",  # pnpm-lock.yaml, etc.
            r".*lock\.yml$",  # lock.yml files
            r".*\.lockb$",  # bun.lockb (binary lock file)
            r"npm-shrinkwrap\.json$",  # npm shrinkwrap file
            # Sum/hash files
            r".*\.sum$",  # go.sum, etc.
            r"go\.sum$",  # go.sum specifically
            # Minified files
            r".*\.min\.js$",  # minified JavaScript
            r".*\.min\.css$",  # minified CSS
            r".*\.min\.json$",  # minified JSON
            # Source maps
            r".*\.map$",  # source map files
            r".*\.js\.map$",  # JavaScript source maps
            r".*\.css\.map$",  # CSS source maps
            # Build/dist directories
            r"^dist/.*",  # dist directory
            r".*/dist/.*",  # dist directory anywhere
            r"^build/.*",  # build directory
            r".*/build/.*",  # build directory anywhere
            r"^out/.*",  # out directory
            r".*/out/.*",  # out directory anywhere
            r"^target/.*",  # target directory (Rust/Maven)
            r".*/target/.*",  # target directory anywhere
            # Images
            r".*\.png$",  # PNG files
            r".*\.jpg$",  # JPG files
            r".*\.jpeg$",  # JPEG files
            r".*\.gif$",  # GIF files
            r".*\.bmp$",  # BMP files
            r".*\.tiff$",  # TIFF files
            r".*\.ico$",  # ICO files
            r".*\.webp$",  # WebP files
            # Snapshots
            r".*\.snap$",  # Snap files
            r".*\.snapshot$",  # Snapshot files
            r".*\.snapfile$",  # Snapfile files
            # Schema files (for PostHog, mostly)
            r".*\.schema\.py$",  # Schema files
            # TXT files
            r".*\.txt$",  # TXT files
        ]

        return any(re.search(pattern, filename, re.IGNORECASE) for pattern in filter_patterns)


class PRParser:
    @staticmethod
    def parse_github_pr_url(url: str) -> dict[str, str | int]:
        """Parse GitHub PR URL and extract owner, repo, and PR number."""
        pattern = r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)"
        match = re.match(pattern, url)
        if not match:
            raise ValueError(
                f"Invalid GitHub PR URL format: {url}\nExpected format: https://github.com/OWNER/REPO/pull/NUMBER"
            )
        return {
            "owner": match.group(1),
            "repo": match.group(2),
            "pr_number": int(match.group(3)),
        }

    @staticmethod
    def parse_patch(patch: str) -> list[PRFileUpdate]:
        """Parse a unified diff patch string into individual changes."""
        if not patch:
            return []
        changes: list[PRFileUpdate] = []
        lines = patch.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            # Look for hunk header
            if not line.startswith("@@"):
                i += 1
                continue
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if not match:
                i += 1
                continue
            old_start = int(match.group(1))
            new_start = int(match.group(3))
            i += 1
            # Process lines in this hunk
            old_line = old_start
            new_line = new_start
            # Collect consecutive changes
            current_type = None
            current_lines: list[str] = []
            current_old_start = None
            current_new_start = None

            def flush_current() -> None:
                nonlocal current_type, current_lines, current_old_start, current_new_start
                if current_type and current_lines:
                    change = PRFileUpdate(type=current_type, code="\n".join(current_lines))

                    if current_type == "deletion":
                        change.old_start_line = current_old_start
                        change.old_end_line = current_old_start + len(current_lines) - 1
                    elif current_type == "addition":
                        change.new_start_line = current_new_start
                        change.new_end_line = current_new_start + len(current_lines) - 1
                    else:  # context
                        change.old_start_line = current_old_start
                        change.old_end_line = current_old_start + len(current_lines) - 1
                        change.new_start_line = current_new_start
                        change.new_end_line = current_new_start + len(current_lines) - 1

                    changes.append(change)

                current_type = None
                current_lines = []
                current_old_start = None
                current_new_start = None

            while i < len(lines) and not lines[i].startswith("@@"):
                line = lines[i]

                if line.startswith("-"):
                    # Deletion
                    if current_type != "deletion":
                        flush_current()
                        current_type = "deletion"
                        current_old_start = old_line
                    current_lines.append(line[1:])
                    old_line += 1

                elif line.startswith("+"):
                    # Addition
                    if current_type != "addition":
                        flush_current()
                        current_type = "addition"
                        current_new_start = new_line
                    current_lines.append(line[1:])
                    new_line += 1

                elif line.startswith(" ") or line == "":
                    # Context line
                    if current_type != "context":
                        flush_current()
                        current_type = "context"
                        current_old_start = old_line
                        current_new_start = new_line
                    # Handle empty context lines
                    current_lines.append(line[1:] if line else "")
                    old_line += 1
                    new_line += 1

                elif line.startswith("\\"):
                    # Special line (e.g., "\ No newline at end of file")
                    # Skip these
                    pass
                else:
                    # Shouldn't happen in valid patch, but handle gracefully
                    break

                i += 1

            # Flush any remaining changes
            flush_current()
            continue

        return changes


def find_open_pr_for_branch(*, token: str, repository: str, owner: str, head_branch: str) -> tuple[int, str] | None:
    """The first open PR whose head is `head_branch` on the base repo, as (number, html_url), or None.

    One API call. Branch targets are origin branches by construction (the tasks agent pushes to the
    base repo, never a fork), so the head qualifier is always `{base owner}:{branch}`.
    """
    repo_obj = Github(token).get_repo(repository)
    pull = next(iter(repo_obj.get_pulls(state="open", head=f"{owner}:{head_branch}")), None)
    if pull is None:
        return None
    return pull.number, pull.html_url


def fetch_branch_compare(
    *, token: str, repository: str, head_branch: str
) -> tuple[PRMetadata, list[PRComment], list[PRFile], str]:
    """Fetch a PR-less branch target as a compare diff against the repo's default branch.

    Returns the same ``(pr_metadata, pr_comments, pr_files, diff)`` shape as `PRFetcher.fetch_pr_data`
    — the pipeline middle (chunk → review → dedup → validate) consumes files + diff and doesn't care
    where they came from. The metadata is synthesized with ``number=0`` ("no PR"); comments are empty
    (there is no PR to carry them). Files are filtered exactly like the PR path.
    """
    repo_obj = Github(token).get_repo(repository)
    base_branch = repo_obj.default_branch
    head_sha = repo_obj.get_branch(head_branch).commit.sha
    comparison = repo_obj.compare(base_branch, head_branch)

    pr_filter = PRFilter()
    pr_parser = PRParser()
    pr_files: list[PRFile] = []
    diff_sections: list[str] = []
    additions = deletions = 0
    for file in comparison.files:
        additions += file.additions
        deletions += file.deletions
        if pr_filter.is_filtered_file(file.filename) or pr_filter.is_test_file(file.filename):
            continue
        pr_files.append(
            PRFile(
                filename=file.filename,
                status=file.status,
                additions=file.additions,
                deletions=file.deletions,
                changes=pr_parser.parse_patch(file.patch) if file.patch else [],
            )
        )
        diff_sections.append(_format_diff_section(file.filename, file.status, file.patch or ""))

    metadata = PRMetadata(
        number=0,
        title=f"{repository}:{head_branch}",
        body="",
        state="open",
        draft=False,
        created_at="",
        updated_at="",
        author="",
        base_branch=base_branch,
        head_branch=head_branch,
        is_fork=False,
        head_sha=head_sha,
        commits=comparison.total_commits,
        additions=additions,
        deletions=deletions,
        changed_files=len(comparison.files),
    )
    return metadata, [], pr_files, "\n\n".join(diff_sections)


class PRFetcher:
    def __init__(self, owner: str, repo: str, pr_number: int, token: str) -> None:
        self.owner = owner
        self.repo = repo
        self.pr_number = pr_number
        self.github_client = self.initialize_github_client(token)

    def initialize_github_client(self, token: str) -> Github:
        # `token` is the team's GitHub App installation token, resolved server-side by the caller.
        if not token:
            raise ValueError("A GitHub installation token is required to authenticate with the GitHub API.")
        return Github(token)

    def fetch_pr_metadata(self, pr: PullRequest) -> PRMetadata:
        # A missing head repo (deleted fork) counts as a fork — we can't trust/reach the head ref.
        head_repo = pr.head.repo.full_name if pr.head.repo else None
        base_repo = pr.base.repo.full_name if pr.base.repo else None
        is_fork = head_repo is None or head_repo != base_repo
        return PRMetadata(
            number=pr.number,
            title=pr.title,
            body=pr.body or "",
            state=pr.state,
            draft=pr.draft,
            created_at=pr.created_at.isoformat() if pr.created_at else "",
            updated_at=pr.updated_at.isoformat() if pr.updated_at else "",
            author=pr.user.login,
            author_association=pr.raw_data.get("author_association", "NONE"),
            base_branch=pr.base.ref,
            head_branch=pr.head.ref,
            is_fork=is_fork,
            head_sha=pr.head.sha,
            mergeable_state=pr.mergeable_state,
            requested_reviewers=[r.login for r in pr.get_review_requests()[0]],  # users
            assignee=pr.assignee.login if pr.assignee else None,
            labels=[label.name for label in pr.labels],
            commits=pr.commits,
            additions=pr.additions,
            deletions=pr.deletions,
            changed_files=pr.changed_files,
        )

    def fetch_pr_comments(self, pr: PullRequest, pr_filter: PRFilter) -> list[PRComment]:
        """Fetch the PR's review comments (filtered files / test files dropped)."""
        pr_comments: list[PRComment] = []
        try:
            for comment in pr.get_review_comments():
                if pr_filter.is_filtered_file(comment.path):
                    continue
                if pr_filter.is_test_file(comment.path):
                    continue
                pr_comments.append(
                    PRComment(
                        id=comment.id,
                        path=comment.path,
                        line=comment.line,
                        start_line=comment.start_line,
                        body=comment.body,
                        diff_hunk=comment.diff_hunk,
                        user=comment.user.login,
                        created_at=comment.created_at.isoformat(),
                    )
                )
        except GithubException as e:
            logger.warning(f"Could not fetch review comments: {e}")
        return pr_comments

    def fetch_pr_files(self, pr: PullRequest, pr_filter: PRFilter, pr_parser: PRParser) -> tuple[list[PRFile], str]:
        """Fetch the PR's reviewable files and the point-in-time unified diff snapshot.

        Returns ``(pr_files, diff)``. The raw per-file patch is captured here — the only place with
        ``file.patch`` — into the ``diff`` snapshot, kept out of ``PRFile`` so it doesn't bloat the
        prompts that dump ``pr_files``. The snapshot is the source for the durable per-turn `commit`
        artefact (it anchors a finding to the exact reviewed code even after later force-pushes).
        """
        pr_files: list[PRFile] = []
        diff_sections: list[str] = []
        try:
            for file in pr.get_files():
                if pr_filter.is_filtered_file(file.filename):
                    continue
                if pr_filter.is_test_file(file.filename):
                    continue
                pr_files.append(
                    PRFile(
                        filename=file.filename,
                        status=file.status,
                        additions=file.additions,
                        deletions=file.deletions,
                        changes=pr_parser.parse_patch(file.patch) if file.patch else [],
                    )
                )
                diff_sections.append(_format_diff_section(file.filename, file.status, file.patch or ""))
        except GithubException as e:
            raise ValueError(f"Failed to fetch PR files: {e.data.get('message', str(e))}") from e
        return pr_files, "\n\n".join(diff_sections)

    def fetch_pr_data(self) -> tuple[PRMetadata, list[PRComment], list[PRFile], str]:
        """Fetch PR data from the GitHub API, returning everything in-process (no files).

        Returns ``(pr_metadata, pr_comments, pr_files, diff)`` where ``diff`` is the reviewed files'
        point-in-time unified patch.
        """
        repo_obj = self.github_client.get_repo(f"{self.owner}/{self.repo}")
        pr = repo_obj.get_pull(self.pr_number)
        pr_filter = PRFilter()
        pr_parser = PRParser()
        pr_metadata = self.fetch_pr_metadata(pr)
        pr_comments = self.fetch_pr_comments(pr, pr_filter)
        pr_files, diff = self.fetch_pr_files(pr, pr_filter, pr_parser)
        logger.info("PR data fetched successfully")
        return pr_metadata, pr_comments, pr_files, diff
