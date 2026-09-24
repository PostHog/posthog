import pytest

from products.tasks.backend.logic.services.git_auth import classify_git_failure


@pytest.mark.parametrize(
    "stderr,expected",
    [
        ("fatal: could not read Username for 'https://github.com': terminal prompts disabled", "credentials"),
        ("remote: Invalid username or token. Password authentication is not supported.", "credentials"),
        ("fatal: Authentication failed for 'https://github.com/acme/widgets.git/'", "credentials"),
        ("fatal: unable to access '...': The requested URL returned error: 401", "credentials"),
        ("git@github.com: Permission denied (publickey).", "credentials"),
        # GitHub answers 404 for a repository the account cannot see, so this is an access
        # question, not proof that the credential plumbing failed.
        ("remote: Repository not found.", "access"),
        ("fatal: unable to access '...': The requested URL returned error: 403", "access"),
        # The server's identity failed verification, which says nothing about the credential.
        ("Host key verification failed.", None),
        # The resume fallback re-clones the default branch when the requested one is gone.
        # Reading that as an auth failure would turn a recoverable miss into a fatal error.
        ("fatal: Remote branch feature-x not found in upstream origin", None),
        ("warning: Could not find remote branch feature-x to clone.", None),
        ("fatal: unable to access '...': Could not resolve host: github.com", None),
        ("error: RPC failed; curl 92 HTTP/2 stream 0 was not closed cleanly", None),
        ("", None),
    ],
)
def test_classify_git_failure_separates_credentials_access_and_other_failures(stderr, expected):
    assert classify_git_failure(stderr) == expected


def test_classify_git_failure_scans_every_captured_stream():
    assert classify_git_failure(None, "", "fatal: could not read Username for 'https://github.com'") == "credentials"
