import pytest
from unittest import mock

import requests
from prometheus_client import REGISTRY

from posthog.egress.github.limiter import GitHubRateResource
from posthog.egress.limiter.policies import Priority

from products.warehouse_sources.backend.temporal.data_imports.sources.github import github


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
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Client Error: Not Found for url")
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
