import pytest

import requests

from posthog.egress.github.transport import GitHubRateLimitError

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


def test_raises_on_unexpected_error(requests_mock):
    # A genuine non-rate-limit failure (e.g. 500) must propagate so the activity retries, not be
    # silently returned as log content.
    requests_mock.get(_URL, status_code=500, text="boom")
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
