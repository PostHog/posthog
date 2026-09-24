from datetime import timedelta

import pytest

import requests
from temporalio.exceptions import ApplicationError

from posthog.egress.github.transport import GitHubRateLimitError

from products.engineering_analytics.backend.logic.job_logs.fetcher import fetch_depot_job_log, fetch_job_log

_URL = "https://api.github.com/repos/PostHog/posthog/actions/jobs/123/logs"
_DEPOT_URL = "https://api.depot.dev/depot.ci.v1.CIService/GetJobAttemptLogs"


def _depot_page(*bodies: str, next_page_token: str = "") -> dict:
    lines = [{"stepKey": "tests", "timestampMs": "1790000000000", "lineNumber": 1, "body": body} for body in bodies]
    return {"lines": lines, "nextPageToken": next_page_token} if next_page_token else {"lines": lines}


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


def test_depot_follows_page_tokens_into_github_shaped_lines(requests_mock):
    # Depot pages an attempt's log. Stopping after the first page drops the failure at the end, and a
    # line without the GitHub timestamp prefix reaches Logs with no timestamp.
    requests_mock.post(
        _DEPOT_URL,
        [
            {"json": _depot_page("##[group]Run tests", next_page_token="page-2")},
            {"json": _depot_page("##[error]Process completed with exit code 1")},
        ],
    )
    assert fetch_depot_job_log("zf6sbbn2wh", "depot-tok") == (
        "2026-09-21T14:13:20.000Z ##[group]Run tests\n"
        "2026-09-21T14:13:20.000Z ##[error]Process completed with exit code 1\n"
    )
    assert [request.json() for request in requests_mock.request_history] == [
        {"attemptId": "zf6sbbn2wh"},
        {"attemptId": "zf6sbbn2wh", "pageToken": "page-2"},
    ]
    assert requests_mock.request_history[0].headers["Authorization"] == "Bearer depot-tok"


def test_depot_caps_log_but_keeps_failure_tail(requests_mock):
    requests_mock.post(
        _DEPOT_URL,
        [
            {"json": _depot_page(*["noise line"] * 1000, next_page_token="page-2")},
            {"json": _depot_page(*["noise line"] * 1000, "##[error]the real failure")},
        ],
    )
    result = fetch_depot_job_log("zf6sbbn2wh", "depot-tok", max_bytes=400)
    assert result is not None
    assert "##[error]the real failure" in result
    assert "log truncated" in result
    assert len(result.encode()) < 1000


@pytest.mark.parametrize(
    "status, headers, error, retry_delay",
    [
        # A revoked token must fail the attempt, never read as an empty log that is marked done.
        (401, {}, requests.HTTPError, None),
        # Depot's Retry-After must reach Temporal, so the retry waits as long as Depot asked.
        (429, {"Retry-After": "30"}, ApplicationError, timedelta(seconds=30)),
    ],
)
def test_depot_raises_on_error_status_without_leaking_token(requests_mock, status, headers, error, retry_delay):
    requests_mock.post(_DEPOT_URL, status_code=status, headers=headers, json={"code": "unauthenticated"})
    with pytest.raises(error) as raised:
        fetch_depot_job_log("zf6sbbn2wh", "depot-secret-token")
    assert "depot-secret-token" not in str(raised.value)
    assert getattr(raised.value, "next_retry_delay", None) == retry_delay


def test_depot_returns_none_when_attempt_has_no_log(requests_mock):
    requests_mock.post(_DEPOT_URL, status_code=404, json={"code": "not_found"})
    assert fetch_depot_job_log("zf6sbbn2wh", "depot-tok") is None
