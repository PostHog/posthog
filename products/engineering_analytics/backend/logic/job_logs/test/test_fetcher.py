import pytest

import requests

from posthog.egress.github.transport import GitHubRateLimitError, GitHubServerError

from products.engineering_analytics.backend.logic.job_logs.fetcher import fetch_job_log

_URL = "https://api.github.com/repos/PostHog/posthog/actions/jobs/123/logs"


def test_returns_log_text_on_success(requests_mock):
    requests_mock.get(_URL, status_code=200, text="2026-06-25T09:14:02.0Z line one")
    assert fetch_job_log("PostHog/posthog", 123, "tok") == "2026-06-25T09:14:02.0Z line one"


def test_returns_none_when_log_expired(requests_mock):
    # GitHub purges Actions logs after retention — a 404 is expected for old jobs and must be a
    # benign "nothing to emit", not a crash that retries the activity forever.
    requests_mock.get(_URL, status_code=404, text="Not Found")
    assert fetch_job_log("PostHog/posthog", 123, "tok") is None


def test_raises_on_rate_limit(requests_mock):
    # A 429 must surface as GitHubRateLimitError so the Temporal retry honors the reset rather than
    # treating the body as a log or hammering the shared installation budget.
    requests_mock.get(_URL, status_code=429, headers={"retry-after": "30"}, text="rate limit exceeded")
    with pytest.raises(GitHubRateLimitError):
        fetch_job_log("PostHog/posthog", 123, "tok")


@pytest.mark.parametrize(
    "status_code,body",
    [
        (503, "Egress is over the account limit"),  # the Azure blob backend throttle we saw
        (500, "boom"),
        (502, "bad gateway"),
    ],
)
def test_raises_retryable_on_transient_server_error(requests_mock, status_code, body):
    # A transient 5xx from the archive backend is a retryable GitHub-side blip, so it must surface as
    # GitHubServerError (which the Temporal interceptor skips) rather than a plain HTTPError that gets
    # reported to error tracking as a defect.
    requests_mock.get(_URL, status_code=status_code, text=body)
    with pytest.raises(GitHubServerError):
        fetch_job_log("PostHog/posthog", 123, "tok")


def test_raises_httperror_on_non_transient_error(requests_mock):
    # A genuine non-retryable failure (e.g. a 403 that isn't a rate limit — access revoked) must still
    # propagate as HTTPError, not be swallowed as a retryable blip or returned as log content.
    requests_mock.get(_URL, status_code=403, text="Forbidden")
    with pytest.raises(requests.HTTPError):
        fetch_job_log("PostHog/posthog", 123, "tok")


def test_caps_log_but_keeps_failure_tail(requests_mock):
    # A connected repo's job can print an arbitrarily large log; the fetch must bound the bytes
    # pulled into memory AND keep the tail, where the failure surfaces — a job padding the start
    # with noise must not push its real error past the cap and out of the emitted text.
    body = ("noise line\n" * 2000) + "##[error]the real failure\n"
    requests_mock.get(_URL, status_code=200, text=body)
    result = fetch_job_log("PostHog/posthog", 123, "tok", max_bytes=400)
    assert result is not None
    assert "##[error]the real failure" in result
    assert "log truncated" in result
    assert len(result.encode()) < len(body.encode())


@pytest.mark.parametrize(
    "bad_repo",
    [
        "PostHog/posthog/contents/secret?ref=main",  # extra path + query steers to another endpoint
        "../../other/repo",  # traversal
        "PostHog/posthog#frag",
        "owner",  # no slash
        "owner/repo/extra",  # too many segments
    ],
)
def test_rejects_unsafe_repo_path(requests_mock, bad_repo):
    # repo is team-writable; a crafted value must be rejected before the authenticated request is
    # built, so it can't fetch a different GitHub endpoint with the installation token.
    with pytest.raises(ValueError):
        fetch_job_log(bad_repo, 123, "tok")
    assert not requests_mock.called
