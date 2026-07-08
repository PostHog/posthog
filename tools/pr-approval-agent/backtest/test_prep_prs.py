import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from parameterized import parameterized
from prep_prs import SUBJECT_PR_RE, build_subject_index, head_at_review


class TestSubjectIndex:
    @parameterized.expand(
        [
            ("squash_subject", "fix(stamphog): thing (#123)", 123),
            ("trailing_space", "feat: other (#9) ", 9),
            ("pr_ref_mid_subject_not_a_merge", "revert (#123) partially", None),
            ("no_pr_ref", "chore: bump", None),
        ]
    )
    def test_end_anchored_pr_extraction(self, _name: str, subject: str, expected: int | None) -> None:
        match = SUBJECT_PR_RE.search(subject)
        assert (int(match.group(1)) if match else None) == expected


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str, date: str | None = None) -> None:
        env = {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin",
        }
        if date:
            env["GIT_COMMITTER_DATE"] = date
            env["GIT_AUTHOR_DATE"] = date
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)

    git("init", "-q", "-b", "master")
    (repo / "f").write_text("1")
    git("add", "f")
    git("commit", "-qm", "one", date="2026-07-01T10:00:00+00:00")
    (repo / "f").write_text("2")
    git("commit", "-aqm", "two", date="2026-07-03T10:00:00+00:00")
    (repo / "f").write_text("3")
    git("commit", "-aqm", "three", date="2026-07-05T10:00:00+00:00")
    git("update-ref", "refs/backtest/42", "HEAD")
    return repo


class TestHeadAtReview:
    def test_picks_newest_commit_at_or_before_review(self, fixture_repo: Path) -> None:
        review_ts = datetime(2026, 7, 4, 0, 0, tzinfo=UTC)
        sha = head_at_review(fixture_repo, 42, review_ts)
        out = subprocess.run(
            ["git", "-C", str(fixture_repo), "log", "-1", "--format=%s", sha],
            check=True,
            capture_output=True,
            text=True,
        )
        assert out.stdout.strip() == "two"

    def test_review_before_all_commits_returns_none(self, fixture_repo: Path) -> None:
        review_ts = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
        assert head_at_review(fixture_repo, 42, review_ts) is None

    def test_timezone_offsets_compare_correctly(self, fixture_repo: Path) -> None:
        # 2026-07-05 03:00 PDT is 10:00 UTC — exactly the third commit's time;
        # a naive string comparison would misorder offset-bearing dates.
        review_ts = datetime.fromisoformat("2026-07-05T03:00:00-07:00")
        sha = head_at_review(fixture_repo, 42, review_ts)
        out = subprocess.run(
            ["git", "-C", str(fixture_repo), "log", "-1", "--format=%s", sha],
            check=True,
            capture_output=True,
            text=True,
        )
        assert out.stdout.strip() == "three"


class TestBuildSubjectIndex:
    def test_first_match_wins_for_duplicate_pr_refs(self, fixture_repo: Path) -> None:
        subprocess.run(
            ["git", "-C", str(fixture_repo), "commit", "-qm", "fix: landed (#42)", "--allow-empty"],
            check=True,
            capture_output=True,
            env={
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
                "PATH": "/usr/bin:/bin",
            },
        )
        subprocess.run(
            ["git", "-C", str(fixture_repo), "update-ref", "refs/remotes/origin/master", "HEAD"],
            check=True,
            capture_output=True,
        )
        index = build_subject_index(fixture_repo, days=3650)
        assert 42 in index
