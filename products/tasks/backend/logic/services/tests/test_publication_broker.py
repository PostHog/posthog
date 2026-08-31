import pytest

from products.tasks.backend.logic.services import publication_broker


@pytest.mark.parametrize(
    "fixture",
    [
        "ghp_abcdefghijklmnopqrstuvwxyz",
        "github_pat_abcdefghijklmnopqrstuvwxyz",
        "sk-abcdefghijklmnop",
        "AKIAABCDEFGHIJKLMNOP",
        "xoxb-abcdefghijklmnop",
        "phx_abcdefghijklmnopqrst",
        "Bearer abcdefghijklmnop",
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_publication_scanner_rejects_registered_secret_fixture(fixture: str) -> None:
    with pytest.raises(publication_broker.PublicationScanError, match="secret"):
        publication_broker.scan_publication_text({"commit_message": fixture})


def test_publication_scanner_rejects_binary_and_generated_files() -> None:
    with pytest.raises(publication_broker.PublicationScanError, match="binary"):
        publication_broker.validate_publication_paths(["assets/agent.bin"])

    with pytest.raises(publication_broker.PublicationScanError, match="generated"):
        publication_broker.validate_publication_paths(["frontend/src/generated/api.ts"])

    with pytest.raises(publication_broker.PublicationScanError, match="invalid"):
        publication_broker.validate_publication_paths(["safe\x00name.py"])


@pytest.mark.parametrize(
    ("path", "mode", "object_type", "content"),
    [
        ("src/link", "120000", "blob", "target"),
        ("src/submodule", "160000", "commit", "a" * 40),
        ("src/special", "040000", "tree", ""),
        ("src/unknown", "100644", "commit", "a" * 40),
    ],
)
def test_publication_scanner_rejects_non_regular_git_entries(
    path: str, mode: str, object_type: str, content: str
) -> None:
    request = publication_broker.PublicationScanRequest(
        branch="codex/0123456789abcdef0123456789abcdef",
        commit_message="server draft",
        pr_title="Draft",
        pr_body="",
        unified_diff="",
        changed_paths=(path,),
        expected_added_paths=(path,),
        added_files=(
            publication_broker.PublicationTextFile(path=path, mode=mode, object_type=object_type, content=content),
        ),
    )

    with pytest.raises(publication_broker.PublicationScanError, match="regular text"):
        publication_broker.scan_draft_publication(request)


@pytest.mark.parametrize("path", ["./file.py", "dir//file.py", "dir/./file.py", "dir/../file.py"])
def test_publication_scanner_rejects_non_canonical_paths(path: str) -> None:
    with pytest.raises(publication_broker.PublicationScanError, match="invalid"):
        publication_broker.validate_publication_paths([path])


@pytest.mark.parametrize("path", ["deleted/../secret.txt", "renamed//unsafe.py"])
def test_publication_scanner_checks_deleted_and_renamed_paths(path: str) -> None:
    request = publication_broker.PublicationScanRequest(
        branch="codex/0123456789abcdef0123456789abcdef",
        commit_message="server draft",
        pr_title="Draft",
        pr_body="",
        unified_diff="",
        changed_paths=("src/safe.py", path),
        expected_added_paths=("src/safe.py",),
        added_files=(
            publication_broker.PublicationTextFile(
                path="src/safe.py", mode="100644", object_type="blob", content="safe text"
            ),
        ),
    )

    with pytest.raises(publication_broker.PublicationScanError, match="invalid"):
        publication_broker.scan_draft_publication(request)


@pytest.mark.parametrize("surface", ["branch", "commit_message", "pr_title", "pr_body", "unified_diff", "added_text"])
def test_publication_scanner_scans_every_publication_surface(surface: str) -> None:
    values = {
        "branch": "codex/0123456789abcdef0123456789abcdef",
        "commit_message": "server draft",
        "pr_title": "Draft",
        "pr_body": "",
        "unified_diff": "",
        "added_text": "safe text",
    }
    values[surface] = "ghp_abcdefghijklmnopqrstuvwxyz"
    request = publication_broker.PublicationScanRequest(
        branch=values["branch"],
        commit_message=values["commit_message"],
        pr_title=values["pr_title"],
        pr_body=values["pr_body"],
        unified_diff=values["unified_diff"],
        changed_paths=("src/safe.py",),
        expected_added_paths=("src/safe.py",),
        added_files=(
            publication_broker.PublicationTextFile(
                path="src/safe.py", mode="100644", object_type="blob", content=values["added_text"]
            ),
        ),
    )

    with pytest.raises(publication_broker.PublicationScanError, match="secret"):
        publication_broker.scan_draft_publication(request)


def test_publication_scanner_fails_closed_on_malformed_added_text() -> None:
    request = publication_broker.PublicationScanRequest(
        branch="codex/0123456789abcdef0123456789abcdef",
        commit_message="server draft",
        pr_title="Draft",
        pr_body="",
        unified_diff="",
        changed_paths=("src/malformed.py",),
        expected_added_paths=("src/malformed.py",),
        added_files=(
            publication_broker.PublicationTextFile(
                path="src/malformed.py", mode="100644", object_type="blob", content="\ud800"
            ),
        ),
    )

    with pytest.raises(publication_broker.PublicationScanError, match="invalid text"):
        publication_broker.scan_draft_publication(request)


@pytest.mark.parametrize(
    ("added_paths", "expected_paths", "message"),
    [
        (("src/omitted.py",), (), "canonical upsert"),
        (("src/duplicate.py", "src/duplicate.py"), ("src/duplicate.py",), "duplicate"),
        (("src/outside.py",), ("src/outside.py",), "changed paths"),
    ],
)
def test_publication_scanner_requires_the_canonical_added_file_set(
    added_paths: tuple[str, ...], expected_paths: tuple[str, ...], message: str
) -> None:
    request = publication_broker.PublicationScanRequest(
        branch="codex/0123456789abcdef0123456789abcdef",
        commit_message="server draft",
        pr_title="Draft",
        pr_body="",
        unified_diff="",
        changed_paths=("src/safe.py",),
        expected_added_paths=expected_paths,
        added_files=tuple(
            publication_broker.PublicationTextFile(path=path, mode="100644", object_type="blob", content="safe text")
            for path in added_paths
        ),
    )

    with pytest.raises(publication_broker.PublicationScanError, match=message):
        publication_broker.scan_draft_publication(request)
