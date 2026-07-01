import pytest
from unittest import mock

import requests
from prometheus_client import REGISTRY

from products.warehouse_sources.backend.temporal.data_imports.sources.github import github


def _ok_response() -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = 200
    response.ok = True
    response.text = ""
    return response


@pytest.fixture(autouse=True)
def _instant_backoff():
    # The retry wait falls back to exponential backoff for ChunkedEncodingError; zero it so the
    # test doesn't actually sleep between attempts.
    with mock.patch.object(github, "_github_backoff_wait", return_value=0.0):
        yield


def test_fetch_page_retries_chunked_encoding_error():
    session = mock.Mock()
    session.get.side_effect = [requests.exceptions.ChunkedEncodingError("Connection broken"), _ok_response()]

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        response = github._fetch_page("https://api.github.com/repos/o/r/issues", {}, mock.Mock())

    assert response.status_code == 200
    assert session.get.call_count == 2


def test_fetch_page_reraises_chunked_encoding_error_after_exhausting_retries():
    session = mock.Mock()
    session.get.side_effect = [requests.exceptions.ChunkedEncodingError("Connection broken")] * 5

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

    assert session.get.call_count == 5
    # Every transport failure is recorded, so a GitHub outage doesn't silently zero warehouse telemetry.
    after = REGISTRY.get_sample_value("github_integration_api_requests_total", exception_labels) or 0
    assert after - before == session.get.call_count
