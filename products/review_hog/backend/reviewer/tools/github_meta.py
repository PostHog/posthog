#!/usr/bin/env python3

import json
import logging
import os
import re
import subprocess
from pathlib import Path

from github import Github, GithubException, PullRequest

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRFileUpdate, PRMetadata

logger = logging.getLogger(__name__)


class PRFilter:
    @staticmethod
    def is_test_file(filename: str) -> bool:
        """Check if a filename matches common test file patterns."""
        test_patterns = [
            r".*[_\-]test[_\-]?.*",  # files with _test_ or -test- in the name
            r".*test[_\-].*",  # files starting with test_
            r".*\.test\.",  # files with .test. in the name
            r"^test_.*",  # files starting with test_
            r"^Test.*",  # files starting with Test (capital T)
            r".*_test\..*",  # files ending with _test
            r"^tests?/.*",  # files in test/tests directories (at start)
            r".*/tests?/.*",  # files in test/tests directories (anywhere)
            r".*\.spec\.",  # spec files (common in JS)
            r".*/__tests__/.*",  # __tests__ directories
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

            i += 1

        return changes


class PRFetcher:
    def __init__(self, owner: str, repo: str, pr_number: int, review_dir: str):
        self.owner = owner
        self.repo = repo
        self.pr_number = pr_number
        self.github_client = self.initialize_github_client()
        self.review_path = Path(review_dir)

    def initialize_github_client(self) -> Github:
        # Check for GitHub token
        github_token = os.environ.get("GITHUB_TOKEN")
        if not github_token:
            raise ValueError(
                "GITHUB_TOKEN environment variable not set. Please set it to authenticate with GitHub API."
            )
        try:
            # Initialize GitHub client
            return Github(github_token)
        except GithubException as e:
            if e.status == 401:
                raise ValueError("Invalid GitHub token. Please check your GITHUB_TOKEN environment variable.") from e
            elif e.status == 404:
                raise ValueError(f"PR #{self.pr_number} not found in repository {self.owner}/{self.repo}") from e
            else:
                raise ValueError(f"GitHub API error: {e.data.get('message', str(e))}") from e

    def fetch_pr_metadata(self, pr: PullRequest) -> PRMetadata:
        # Fetch PR metadata
        pr_meta_path = self.review_path / "pr_meta.json"
        if pr_meta_path.exists():
            logger.info("pr_meta.json already exists, skipping")
            with pr_meta_path.open() as f:
                pr_metadata = PRMetadata.model_validate_json(f.read())
            return pr_metadata
        pr_metadata = PRMetadata(
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
            mergeable_state=pr.mergeable_state,
            requested_reviewers=[r.login for r in pr.get_review_requests()[0]],  # users
            assignee=pr.assignee.login if pr.assignee else None,
            labels=[label.name for label in pr.labels],
            commits=pr.commits,
            additions=pr.additions,
            deletions=pr.deletions,
            changed_files=pr.changed_files,
        )

        with pr_meta_path.open("w") as f:
            json.dump(pr_metadata.model_dump(), f, indent=2)
        return pr_metadata

    def fetch_pr_comments(self, pr: PullRequest, pr_filter: PRFilter) -> list[PRComment]:
        """Fetch PR comments from GitHub API and save to files."""
        pr_comments_path = self.review_path / "pr_comments.jsonl"
        if pr_comments_path.exists():
            logger.info("pr_comments.jsonl already exists, skipping")
            with pr_comments_path.open() as f:
                pr_comments = [PRComment.model_validate_json(x) for x in f.readlines()]
        else:
            pr_comments = []
            try:
                for comment in pr.get_review_comments():
                    # Skip comments on filtered files
                    if pr_filter.is_filtered_file(comment.path):
                        continue
                    if pr_filter.is_test_file(comment.path):
                        continue
                    comment_obj = PRComment(
                        path=comment.path,
                        line=comment.line,
                        start_line=comment.start_line,
                        body=comment.body,
                        diff_hunk=comment.diff_hunk,
                        user=comment.user.login,
                        created_at=comment.created_at.isoformat(),
                    )
                    pr_comments.append(comment_obj)
            except GithubException as e:
                logger.warning(f"Could not fetch review comments: {e}")
            with pr_comments_path.open("w") as f:
                f.write("\n".join([x.model_dump_json() for x in pr_comments]))
        return pr_comments

    def fetch_pr_files(self, pr: PullRequest, pr_filter: PRFilter, pr_parser: PRParser) -> list[PRFile]:
        """Fetch PR files from GitHub API and save to files."""
        pr_files_path = self.review_path / "pr_files.jsonl"
        if pr_files_path.exists():
            logger.info("pr_files.jsonl already exists, skipping")
            with pr_files_path.open() as f:
                pr_files = [PRFile.model_validate_json(x) for x in f.readlines()]
        else:
            pr_files = []
            try:
                for file in pr.get_files():
                    # Skip filtered files
                    if pr_filter.is_filtered_file(file.filename):
                        continue
                    # Skip test files
                    if pr_filter.is_test_file(file.filename):
                        continue
                    file_obj = PRFile(
                        filename=file.filename,
                        status=file.status,
                        additions=file.additions,
                        deletions=file.deletions,
                        changes=pr_parser.parse_patch(file.patch) if file.patch else [],
                    )
                    pr_files.append(file_obj)
            except GithubException as e:
                raise ValueError(f"Failed to fetch PR files: {e.data.get('message', str(e))}") from e
            with pr_files_path.open("w") as f:
                f.write("\n".join([x.model_dump_json() for x in pr_files]))
        return pr_files

    def generate_pr_files_scope(self, pr_files: list[PRFile]) -> None:
        """Generate pr_files_scope.jsonl (same as pr_files but without code)"""
        pr_files_scope_path = self.review_path / "pr_files_scope.jsonl"
        if pr_files_scope_path.exists():
            logger.info("pr_files_scope.jsonl already exists, skipping")
        else:
            # Create scope version by dumping to dict and removing code fields
            pr_files_scope = []
            for pr_file in pr_files:
                pr_file_dict = pr_file.model_dump()
                # Remove the code field from each change
                for change in pr_file_dict.get("changes", []):
                    if "code" in change:
                        del change["code"]
                pr_files_scope.append(pr_file_dict)

            with pr_files_scope_path.open("w") as f:
                f.write("\n".join([json.dumps(x) for x in pr_files_scope]))
        return None

    def fetch_pr_data(self) -> tuple[PRMetadata, list[PRComment], list[PRFile]]:
        """Fetch PR data from GitHub API and save to files."""
        repo_obj = self.github_client.get_repo(f"{self.owner}/{self.repo}")
        pr = repo_obj.get_pull(self.pr_number)
        pr_filter = PRFilter()
        pr_parser = PRParser()
        # Fetch PR data
        pr_metadata = self.fetch_pr_metadata(pr)
        pr_comments = self.fetch_pr_comments(pr, pr_filter)
        pr_files = self.fetch_pr_files(pr, pr_filter, pr_parser)
        # Generate scope of the changed files
        self.generate_pr_files_scope(pr_files)
        logger.info("PR data fetched successfully")
        return pr_metadata, pr_comments, pr_files


def switch_to_pr_branch(pr_metadata: PRMetadata, project_dir: str) -> None:
    """Switch to the PR's head branch in the project directory"""
    logger.info(f"Switching to branch '{pr_metadata.head_branch}' in {project_dir}")
    # First fetch the latest changes
    subprocess.run(  # noqa: S603
        ["git", "fetch", "origin"],  # noqa: S607
        cwd=project_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    # Checkout to branch
    subprocess.run(  # noqa: S603
        ["git", "checkout", pr_metadata.head_branch],  # noqa: S607
        cwd=project_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    # Fetch the latest changes
    subprocess.run(  # noqa: S603
        ["git", "fetch", "origin"],  # noqa: S607
        cwd=project_dir,
        check=True,
        capture_output=True,
        text=True,
    )
