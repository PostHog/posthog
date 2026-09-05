import subprocess
from pathlib import Path

import pytest

from products.reaperhog.backend.logic.repo import SWEEP_FILE_THRESHOLD, RepoIndex, is_test_path

CONSTANTS = """\
export const OTHER = {
    NOPE: 'nope',
}
export const FEATURE_FLAGS = {
    // Eternal flags
    HOG: 'hog', // owner: #team-data-tools
    HOGQL_EDITOR: 'hogql-editor',
    WITH_DASH: 'with-dash', // trailing comment
} as const
export const AFTER = {
    LATER: 'later',
}
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        },
    )


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


@pytest.fixture
def repo(tmp_path: Path) -> RepoIndex:
    _git(tmp_path, "init", "-q")
    _write(tmp_path, "frontend/src/lib/constants.tsx", CONSTANTS)
    _write(
        tmp_path,
        "frontend/src/scenes/a.tsx",
        "if (featureFlags[FEATURE_FLAGS.HOG]) {}\nuse(FEATURE_FLAGS.HOGQL_EDITOR)\n",
    )
    _write(tmp_path, "posthog/api/b.py", 'if feature_enabled("hog", user):\n    pass\nx = "hogql-editor-v2"\n')
    _write(tmp_path, "posthog/api/test/test_b.py", "assert flag == 'hog'\n")
    _write(tmp_path, "frontend/__snapshots__/a.snap", "'hog'\n")
    _write(tmp_path, "products/old/thing.py", "print('old')\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "Add fixture files")
    return RepoIndex(tmp_path)


def test_frontend_flag_keys_only_reads_the_feature_flags_block(repo: RepoIndex) -> None:
    assert repo.frontend_flag_keys() == {"HOG": "hog", "HOGQL_EDITOR": "hogql-editor", "WITH_DASH": "with-dash"}


def test_references_are_attributed_per_key_on_word_boundaries(repo: RepoIndex) -> None:
    references = repo.references_many(
        {
            "hog": ["'hog'", '"hog"', "FEATURE_FLAGS.HOG"],
            "hogql-editor": ["'hogql-editor'", '"hogql-editor"', "FEATURE_FLAGS.HOGQL_EDITOR"],
            "with-dash": ["'with-dash'", '"with-dash"', "FEATURE_FLAGS.WITH_DASH"],
        }
    )
    assert references["hog"].files == ("frontend/src/scenes/a.tsx", "posthog/api/b.py", "posthog/api/test/test_b.py")
    assert references["hog"].code_files == ("frontend/src/scenes/a.tsx", "posthog/api/b.py")
    assert references["hog"].total == 3
    assert references["hogql-editor"].files == ("frontend/src/scenes/a.tsx",)
    assert references["with-dash"].files == ()


def test_last_real_commit_skips_sweeps(repo: RepoIndex) -> None:
    for index in range(SWEEP_FILE_THRESHOLD):
        _write(repo.root, f"sweep/{index}.txt", "x\n")
    _write(repo.root, "products/old/thing.py", "print('formatted')\n")
    _git(repo.root, "add", ".")
    _git(repo.root, "commit", "-q", "-m", "chore: format everything")

    stamp = repo.last_real_commit("products/old")

    assert stamp is not None
    assert stamp.subject == "Add fixture files"


@pytest.mark.parametrize(
    "path,expected",
    [
        ("posthog/api/test/test_b.py", True),
        ("frontend/src/lib/utils.test.ts", True),
        ("products/x/backend/tests/conftest.py", True),
        ("frontend/src/scenes/a.tsx", False),
        ("posthog/latest_thing.py", False),
    ],
)
def test_is_test_path(path: str, expected: bool) -> None:
    assert is_test_path(path) is expected
