import pytest

import requests

from posthog.models.integration import GitHubRateLimitError

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
