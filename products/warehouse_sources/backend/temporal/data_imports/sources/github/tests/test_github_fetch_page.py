import json

import pytest
from unittest import mock

import requests
from prometheus_client import REGISTRY
from tenacity import (
    Future as TenacityFuture,
    RetryCallState,
)

from posthog.egress.github.limiter import GitHubRateResource
from posthog.egress.limiter.policies import Priority

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.github import github
from products.warehouse_sources.backend.temporal.data_imports.sources.github.source import GithubSource


def _ok_response() -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = 200
    response.ok = True
    response.text = ""
    # The egress recorder reads response.request.{method,url} and, for a known installation,
    # response.headers; a spec'd mock doesn't expose either instance attribute, so set them
    # explicitly (None falls back to defaults in the recorder, and no headers means no rate-limit
    # sample rather than a parse over a Mock).
    response.request = None
    response.headers = {}
    return response


@pytest.fixture(autouse=True)
def _instant_backoff():
    # The retry wait falls back to exponential backoff for ChunkedEncodingError; zero it so the
    # test doesn't actually sleep between attempts.
    with mock.patch.object(github, "_github_backoff_wait", return_value=0.0):
        yield


def _not_found_response() -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = 404
    response.ok = False
    response.headers = {}
    response.text = "Not Found"
    response.request = None
    response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "404 Client Error: Not Found for url", response=response
    )
    return response


@pytest.mark.parametrize(
    "skip_on_not_found,expected_exc",
    [
        (True, github.GithubOrgNotFoundError),
        (False, requests.exceptions.HTTPError),
    ],
)
def test_fetch_page_404_skips_only_for_org_scoped_endpoints(skip_on_not_found, expected_exc):
    # An org-scoped endpoint (a user-owned repo has no org, so /orgs/{owner}/teams 404s) treats a 404
    # as a benign skip; a repo-scoped one keeps it fatal so a genuinely missing repo still fails loud.
    session = mock.Mock()
    session.request.return_value = _not_found_response()

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        with pytest.raises(expected_exc):
            github._fetch_page(
                "https://api.github.com/orgs/acme/teams", {}, mock.Mock(), skip_on_not_found=skip_on_not_found
            )


def _unprocessable_response(message: str) -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = 422
    response.ok = False
    response.headers = {}
    response.text = json.dumps({"message": message})
    response.json.return_value = {"message": message}
    response.request = None
    response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "422 Client Error: Unprocessable Entity for url", response=response
    )
    return response


def test_fetch_page_raises_repository_too_large_for_code_frequency_422():
    # GitHub permanently 422s /stats/code_frequency once a repo passes 10,000 commits; the caller
    # must treat this as a benign skip, not crash and retry the activity forever.
    session = mock.Mock()
    session.request.return_value = _unprocessable_response("repository must have fewer than 10000 commits")

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        with pytest.raises(github.GithubRepositoryTooLargeError):
            github._fetch_page("https://api.github.com/repos/o/r/stats/code_frequency", {}, mock.Mock())


def _empty_repository_response() -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = 409
    response.ok = False
    response.headers = {}
    response.text = json.dumps({"message": "Git Repository is empty."})
    response.json.return_value = {"message": "Git Repository is empty."}
    response.request = None
    # If the empty-repo 409 check ever regresses, this must raise instead of silently falling
    # through to a passing empty page list, so the test actually fails on that regression.
    response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "409 Client Error: Conflict for url", response=response
    )
    return response


def test_iter_pages_stops_on_empty_repository():
    # commits is a fan_out_parent (check_runs, commit_statuses walk it via _iter_pages), so the same
    # empty-repo 409 that get_rows handles directly for a bare `commits` read must also be swallowed
    # here rather than propagating out of the fan-out walk.
    session = mock.Mock()
    session.request.return_value = _empty_repository_response()

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        pages = list(github._iter_pages("https://api.github.com/repos/o/r/commits", {}, None, mock.Mock()))

    assert pages == []


def test_fetch_page_reraises_other_422_errors():
    # A generic 422 (e.g. malformed request params) is a real, fixable problem and must stay fatal
    # rather than being swallowed by the too-large-repository check.
    session = mock.Mock()
    session.request.return_value = _unprocessable_response("Validation failed")

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        with pytest.raises(requests.exceptions.HTTPError):
            github._fetch_page("https://api.github.com/repos/o/r/stats/code_frequency", {}, mock.Mock())


def test_fetch_page_treats_topics_422_as_resource_unavailable():
    # GitHub 422s the topics endpoint for some repositories; it's optional metadata, so the caller
    # must sync zero rows rather than crash and fail the schema over a raw 422.
    session = mock.Mock()
    session.request.return_value = _unprocessable_response("Validation failed")

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        with pytest.raises(github.GithubResourceUnavailableError):
            github._fetch_page("https://api.github.com/repos/o/r/topics?per_page=100", {}, mock.Mock())


def test_fetch_page_retries_chunked_encoding_error():
    session = mock.Mock()
    session.request.side_effect = [requests.exceptions.ChunkedEncodingError("Connection broken"), _ok_response()]

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        response = github._fetch_page("https://api.github.com/repos/o/r/issues", {}, mock.Mock())

    assert response.status_code == 200
    assert session.request.call_count == 2


def test_fetch_page_treats_unmapped_4xx_as_retryable():
    # GitHub's edge has been observed returning the nginx-style 499 ("client closed request") on an
    # upstream hiccup. It's not a real denial, so it must retry like a 5xx rather than crash the sync
    # on a raw, unclassified HTTPError.
    session = mock.Mock()
    session.request.return_value = _error_response(499, "Unknown")

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        with pytest.raises(github.GithubRetryableError):
            github._fetch_page("https://api.github.com/repos/o/r/issues", {}, mock.Mock())

    assert session.request.call_count == 5


def test_fetch_page_reraises_chunked_encoding_error_after_exhausting_retries():
    session = mock.Mock()
    session.request.side_effect = [requests.exceptions.ChunkedEncodingError("Connection broken")] * 5

    exception_labels = {
        "installation_id": "",
        "method": "GET",
        "endpoint": "/repos/{owner}/{repo}/issues",
        "status_code": "exception",
        "source": "warehouse",
    }
    before = REGISTRY.get_sample_value("github_integration_api_requests_total", exception_labels) or 0

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        with pytest.raises(requests.exceptions.ChunkedEncodingError):
            github._fetch_page("https://api.github.com/repos/o/r/issues", {}, mock.Mock())

    assert session.request.call_count == 5
    # Every transport failure is recorded, so a GitHub outage doesn't silently zero warehouse telemetry.
    after = REGISTRY.get_sample_value("github_integration_api_requests_total", exception_labels) or 0
    assert after - before == session.request.call_count


def _failed_retry_state(exc: BaseException) -> RetryCallState:
    state = RetryCallState(retry_object=mock.Mock(), fn=mock.Mock(), args=(), kwargs={})
    outcome: TenacityFuture = TenacityFuture(attempt_number=1)
    outcome.set_exception(exc)
    state.outcome = outcome
    return state


@pytest.mark.parametrize(
    "pace,expected_floor,expected_ceiling",
    [
        # The limiter's own answer, which the blind exponential backoff (capped at 30s) cannot reach.
        (120.0, 120.0, 121.0),
        # Clamped to the same ceiling the GitHub-side Retry-After path honors.
        (9999.0, github.GITHUB_MAX_RETRY_AFTER_SECONDS, github.GITHUB_MAX_RETRY_AFTER_SECONDS + 1.0),
        # Budget already refilled: fall through to backoff rather than retrying with no wait at all.
        (0.0, 0.0, 0.0),
    ],
    ids=["waits-the-limiters-pace", "clamped-to-ceiling", "refilled-falls-through"],
)
def test_retry_wait_asks_the_limiter_how_long_our_own_budget_needs(pace, expected_floor, expected_ceiling):
    # Our budget, so the limiter knows when it frees. Leaving this on the 30s-capped exponential
    # meant a shed page burned five attempts in ~2 minutes and failed the activity, letting Temporal
    # restart the whole extraction.
    exc = github.GitHubEgressBudgetExhausted(
        "GitHub egress budget exhausted for installation 42; deferring", scope="42"
    )

    with mock.patch.object(github, "github_installation_pace_seconds", return_value=pace) as paced:
        wait = github._github_retry_wait(_failed_retry_state(exc))

    assert expected_floor <= wait <= expected_ceiling
    assert paced.call_args.args[0] == "42"
    assert paced.call_args.kwargs["priority"] == Priority.BATCH


def test_retry_wait_falls_through_when_the_budget_error_carries_no_scope():
    # An identity-blind caller has no budget key, so there is nothing to ask the limiter about.
    exc = github.GitHubEgressBudgetExhausted("GitHub egress budget exhausted; deferring")

    with mock.patch.object(github, "github_installation_pace_seconds") as paced:
        wait = github._github_retry_wait(_failed_retry_state(exc))

    assert wait == 0.0
    paced.assert_not_called()


def test_fetch_page_gates_on_egress_budget_when_installation_known():
    # App path: a denied BATCH gate must defer (raise the retryable error) without ever sending the
    # request, and the gate must run on every retry attempt before reraising.
    session = mock.Mock()
    session.request.return_value = _ok_response()
    identity = github.GithubEgressIdentity(installation_id="123")

    with (
        mock.patch("posthog.egress.github.transport.consume_github_installation_sync", return_value=False) as gate,
        mock.patch.object(github, "make_tracked_session", return_value=session),
    ):
        with pytest.raises(github.GitHubEgressBudgetExhausted):
            github._fetch_page("https://api.github.com/repos/o/r/issues", {}, mock.Mock(), identity)

    assert session.request.call_count == 0
    assert gate.call_count == 5
    assert gate.call_args.args[0] == "123"
    assert gate.call_args.kwargs == {
        "priority": Priority.BATCH,
        "source": "warehouse",
        "resource": GitHubRateResource.CORE,
    }


@pytest.mark.parametrize(
    "installation_id,pace,expected_wait",
    [
        # Budget with room to spare, which is every sync short enough never to spend its share.
        # Waiting here would add latency to all of them and prevent nothing.
        ("123", 0.0, None),
        ("123", 12.5, 12.5),
        # Spreading a nearly spent budget can imply most of a window. A source that holds a worker
        # slot that long is worse than being shed and resuming, so the wait stops at the ceiling.
        ("123", 9_999.0, github.GITHUB_MAX_RETRY_AFTER_SECONDS),
        # PAT path: no installation, so no budget to pace against. Asking anyway would key the
        # lookup on a missing installation and wait on a budget that is not this caller's.
        (None, 12.5, None),
    ],
)
def test_fetch_page_waits_for_egress_budget_before_asking_for_it(installation_id, pace, expected_wait):
    # Waiting first is what keeps a long walk inside the budget rather than recovering from it. Every
    # way of breaking this is silent: no wait means the run drains its share and is shed for the rest
    # of the window, and waiting when there is headroom slows every small sync instead.
    session = mock.Mock()
    session.request.return_value = _ok_response()
    identity = github.GithubEgressIdentity(installation_id=installation_id)

    with (
        mock.patch.object(github, "github_installation_pace_seconds", return_value=pace) as pace_for,
        mock.patch.object(github, "activity") as temporal_activity,
        mock.patch.object(github, "make_tracked_session", return_value=session),
    ):
        temporal_activity.in_activity.return_value = True
        github._fetch_page("https://api.github.com/repos/o/r/issues", {}, mock.Mock(), identity)

    expected_waits = [] if expected_wait is None else [mock.call(timeout=expected_wait)]
    assert temporal_activity.wait_for_worker_shutdown_sync.call_args_list == expected_waits
    assert pace_for.called is (installation_id is not None)
    assert session.request.call_count == 1


@pytest.mark.parametrize(
    "in_activity,expect_drain_wait,expect_sleep",
    [
        (True, True, False),
        # Outside an activity there is no worker to drain, so a plain sleep is the whole behavior.
        (False, False, True),
    ],
)
def test_fetch_page_budget_wait_yields_to_a_draining_worker(in_activity, expect_drain_wait, expect_sleep):
    # The pipeline tests for worker shutdown only between the chunks a source yields, so a wait that
    # slept would hold a draining pod for its full duration and delay the hand-off by that much.
    # Waiting on the shutdown event returns the moment the pod starts draining. Nothing about the
    # sync looks wrong when this regresses; drains just get slower.
    session = mock.Mock()
    session.request.return_value = _ok_response()
    identity = github.GithubEgressIdentity(installation_id="123")

    with (
        mock.patch.object(github, "github_installation_pace_seconds", return_value=30.0),
        mock.patch.object(github, "activity") as temporal_activity,
        mock.patch.object(github.time, "sleep") as sleep,
        mock.patch.object(github, "make_tracked_session", return_value=session),
    ):
        temporal_activity.in_activity.return_value = in_activity
        github._fetch_page("https://api.github.com/repos/o/r/issues", {}, mock.Mock(), identity)

    assert temporal_activity.wait_for_worker_shutdown_sync.called is expect_drain_wait
    assert sleep.called is expect_sleep


def _error_response(status_code: int, message: str, headers: dict[str, str] | None = None) -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    response.ok = False
    response.headers = headers or {}
    response.text = json.dumps({"message": message})
    response.json.return_value = {"message": message}
    response.request = None
    response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        f"{status_code} Client Error: for url", response=response
    )
    return response


@pytest.mark.parametrize(
    "message,expected_exc",
    [
        # GitHub uses 403 for a repository feature the owner switched off. Nothing to sync, now or
        # ever, so the table must skip rather than fail the schema and stop syncing.
        ("Dependabot alerts are disabled for this repository.", github.GithubResourceUnavailableError),
        (
            "Advanced Security must be enabled for this repository to use code scanning.",
            github.GithubResourceUnavailableError,
        ),
        ("Secret scanning is disabled on this repository.", github.GithubResourceUnavailableError),
        # A real denial stays fatal, and carries GitHub's own reason so the curated copy can name it.
        ("Resource not accessible by integration", github.GithubAccessDeniedError),
        ("Must have admin rights to Repository.", github.GithubAccessDeniedError),
        ("Resource protected by organization SAML enforcement", github.GithubAccessDeniedError),
    ],
)
def test_fetch_page_403_separates_switched_off_features_from_denials(message, expected_exc):
    session = mock.Mock()
    session.request.return_value = _error_response(403, message)

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        with pytest.raises(expected_exc) as raised:
            github._fetch_page("https://api.github.com/repos/o/r/dependabot/alerts", {}, mock.Mock(), repository="o/r")

    assert message in str(raised.value)


@pytest.mark.parametrize(
    "message,required_permission,expected_advice,carries_url",
    [
        # This message reaches the user as the schema's error, so a denial that omits the grant
        # leaves them with a disabled table and no stated way to re-enable it. The user reads it,
        # so the API URL stays in the log line instead.
        ("Resource not accessible by integration", "deployments", "Deployments: read", False),
        # An endpoint with no mapped grant still has to end in an action.
        ("Resource not accessible by integration", None, "Add the missing permission", False),
        # An organization-level denial is not about this table's grant, and naming one would send
        # the user to the wrong setting. Curated copy replaces this one, so it keeps the URL.
        ("Resource protected by organization SAML enforcement", "deployments", "GitHub denied access", True),
    ],
)
def test_fetch_page_denial_states_the_action_that_fits_the_denial(
    message, required_permission, expected_advice, carries_url
):
    session = mock.Mock()
    session.request.return_value = _error_response(403, message)

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        with pytest.raises(github.GithubAccessDeniedError) as raised:
            github._fetch_page(
                "https://api.github.com/repos/o/r/deployments",
                {},
                mock.Mock(),
                repository="o/r",
                required_permission=required_permission,
            )

    assert expected_advice in str(raised.value)
    assert ("api.github.com" in str(raised.value)) is carries_url


@pytest.mark.parametrize(
    "message",
    [
        "Resource not accessible by integration",
        # Per-endpoint wording no enumerated error key can match; only the message prefix does.
        "Must have push access to view repository collaborators",
    ],
)
def test_denials_raised_by_fetch_page_are_classified_non_retryable(message):
    # The raised message and GithubSource.get_non_retryable_errors are two halves of one contract:
    # a denial that matches no key there keeps retrying and never disables the schema. Drive the
    # real raised message through the real key set, so rewording either side alone fails here.
    session = mock.Mock()
    session.request.return_value = _error_response(403, message)

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        with pytest.raises(github.GithubAccessDeniedError) as raised:
            github._fetch_page("https://api.github.com/repos/o/r/collaborators", {}, mock.Mock(), repository="o/r")

    errors = GithubSource().get_non_retryable_errors()
    assert any(error_message_matches(str(raised.value), [key]) for key in errors)


def test_fetch_page_403_from_rate_limit_is_not_a_denial():
    # The denial classification must stay behind the rate-limit check: a rate-limited 403 has to keep
    # backing off and retrying, not become a permanent "GitHub denied access" that stops the schema.
    session = mock.Mock()
    session.request.return_value = _error_response(
        403, "You have exceeded a secondary rate limit. Please wait a few minutes before you try again."
    )

    with (
        mock.patch.object(github, "make_tracked_session", return_value=session),
        mock.patch("tenacity.nap.time.sleep"),
    ):
        with pytest.raises(github.GitHubRateLimitError):
            github._fetch_page("https://api.github.com/repos/o/r/issues", {}, mock.Mock(), repository="o/r")


@pytest.mark.parametrize(
    "page_url,probe_response,expected_exc,expected_calls",
    [
        # The repository still resolves, so the 404 is about this endpoint alone (a feature that was
        # never turned on) — sync zero rows instead of blaming the repository.
        (
            "https://api.github.com/repos/o/r/issue-types",
            _ok_response,
            github.GithubResourceUnavailableError,
            2,
        ),
        # The repository itself is gone, which no retry can fix.
        (
            "https://api.github.com/repos/o/r/issue-types",
            lambda: _error_response(404, "Not Found"),
            github.GithubRepositoryNotFoundError,
            2,
        ),
        # GitHub couldn't tell us either way, so keep the old cautious behavior.
        (
            "https://api.github.com/repos/o/r/issue-types",
            lambda: _error_response(500, "Server Error"),
            requests.exceptions.HTTPError,
            2,
        ),
        # An org-scoped endpoint addresses a different resource, so the repository resolving says
        # nothing about it: don't probe, and keep the 404 fatal.
        (
            "https://api.github.com/orgs/o/teams/core/members",
            _ok_response,
            requests.exceptions.HTTPError,
            1,
        ),
    ],
)
def test_fetch_page_404_probes_the_repository_before_blaming_it(page_url, probe_response, expected_exc, expected_calls):
    session = mock.Mock()
    session.request.side_effect = [_error_response(404, "Not Found"), probe_response()]

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        with pytest.raises(expected_exc):
            github._fetch_page(page_url, {}, mock.Mock(), repository="o/r")

    assert session.request.call_count == expected_calls
    if expected_calls > 1:
        assert session.request.call_args_list[1].args[1] == "https://api.github.com/repos/o/r"


def test_fetch_page_skips_gate_on_pat_path():
    # PAT path has no installation budget, so the gate must never run and the request proceeds.
    session = mock.Mock()
    session.request.return_value = _ok_response()

    with (
        mock.patch("posthog.egress.github.transport.consume_github_installation_sync") as gate,
        mock.patch.object(github, "make_tracked_session", return_value=session),
    ):
        response = github._fetch_page(
            "https://api.github.com/repos/o/r/issues", {}, mock.Mock(), github.GithubEgressIdentity()
        )

    assert response.status_code == 200
    assert gate.call_count == 0
    assert session.request.call_count == 1
