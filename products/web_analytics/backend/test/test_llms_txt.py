from contextlib import nullcontext

import pytest
from unittest.mock import Mock, patch

import requests

from products.web_analytics.backend.llms_txt import LLMS_TXT_MAX_BYTES, LlmsTxtFetchError, fetch_llms_txt


def _response(
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    chunks: list[bytes] | None = None,
) -> Mock:
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.headers = headers or {"Content-Type": "text/plain; charset=utf-8"}
    response.iter_content.return_value = chunks or [b"# Example\n- https://example.com/docs"]
    return response


def _session(response: Mock) -> Mock:
    session = Mock(spec=requests.Session)
    session.get.return_value = response
    return session


@patch("products.web_analytics.backend.llms_txt.pinned_session")
def test_fetch_llms_txt_revalidates_redirect_targets(pinned_session_mock: Mock) -> None:
    redirect = _response(status_code=302, headers={"Location": "/llms-full.txt"})
    success = _response(chunks=[b"# Example\n", b"- https://example.com/docs"])
    pinned_session_mock.side_effect = [nullcontext(_session(redirect)), nullcontext(_session(success))]

    fetched = fetch_llms_txt("https://example.com/llms.txt")

    assert fetched.content == "# Example\n- https://example.com/docs"
    assert fetched.url == "https://example.com/llms-full.txt"
    assert [call.args[0] for call in pinned_session_mock.call_args_list] == [
        "https://example.com/llms.txt",
        "https://example.com/llms-full.txt",
    ]


@patch("products.web_analytics.backend.llms_txt.pinned_session")
def test_fetch_llms_txt_stops_streams_over_the_size_limit(pinned_session_mock: Mock) -> None:
    response = _response(chunks=[b"x" * LLMS_TXT_MAX_BYTES, b"x"])
    pinned_session_mock.return_value = nullcontext(_session(response))

    with pytest.raises(LlmsTxtFetchError, match="larger than 1 MB"):
        fetch_llms_txt("https://example.com/llms.txt")


@patch("products.web_analytics.backend.llms_txt.pinned_session")
def test_fetch_llms_txt_rejects_html_responses(pinned_session_mock: Mock) -> None:
    response = _response(headers={"Content-Type": "text/html"}, chunks=[b"<html>Not found</html>"])
    pinned_session_mock.return_value = nullcontext(_session(response))

    with pytest.raises(LlmsTxtFetchError, match="HTML page"):
        fetch_llms_txt("https://example.com/llms.txt")
