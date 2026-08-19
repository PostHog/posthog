import json

import pytest
from unittest import mock

import requests
from prometheus_client import REGISTRY

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
    # The egress recorder reads response.request.{method,url}; a spec'd mock doesn't expose the
    # instance attribute, so set it explicitly (None falls back to defaults in the recorder).
    response.request = None
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
