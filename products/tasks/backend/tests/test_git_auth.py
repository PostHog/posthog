import pytest

from products.tasks.backend.logic.services.git_auth import is_git_auth_failure


@pytest.mark.parametrize(
    "stderr,expected",
    [
        ("fatal: could not read Username for 'https://github.com': terminal prompts disabled", True),
        ("remote: Invalid username or token. Password authentication is not supported.", True),
        ("fatal: Authentication failed for 'https://github.com/acme/widgets.git/'", True),
        ("remote: Repository not found.", True),
        ("fatal: unable to access '...': The requested URL returned error: 403", True),
        ("git@github.com: Permission denied (publickey).", True),
        ("Host key verification failed.", True),
        # The resume fallback re-clones the default branch when the requested one is gone. Reading
        # that as an auth failure would turn a recoverable miss into a fatal, non-retryable error.
        ("fatal: Remote branch feature-x not found in upstream origin", False),
        ("warning: Could not find remote branch feature-x to clone.", False),
        ("fatal: unable to access '...': Could not resolve host: github.com", False),
        ("error: RPC failed; curl 92 HTTP/2 stream 0 was not closed cleanly", False),
        ("", False),
    ],
)
def test_is_git_auth_failure_separates_missing_credentials_from_other_clone_failures(stderr, expected):
    assert is_git_auth_failure(stderr) is expected


def test_is_git_auth_failure_scans_every_captured_stream():
    assert is_git_auth_failure(None, "", "fatal: could not read Username for 'https://github.com'") is True
