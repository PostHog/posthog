from collections.abc import Callable
from contextlib import nullcontext
from itertools import repeat

import pytest
from unittest.mock import Mock, patch

import requests

from posthog.security.pinned_requests import SSRFBlockedError

from products.web_analytics.backend.llms_txt import (
    LLMS_TXT_MAX_BYTES,
    LLMS_TXT_MAX_REDIRECTS,
    LLMS_TXT_TOTAL_BUDGET_SECONDS,
    LlmsTxtFetchError,
    fetch_llms_txt,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _response(
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    chunks: list[bytes] | None = None,
    on_read: Callable[[], None] | None = None,
) -> Mock:
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.headers = headers or {"Content-Type": "text/plain; charset=utf-8"}
    reads = iter([*(chunks or [b"# Example\n- https://example.com/docs"]), b""])

    def read1(_amt: int) -> bytes:
        if on_read is not None:
            on_read()
        return next(reads, b"")

    response.raw = Mock(read1=read1)
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


@patch("products.web_analytics.backend.llms_txt.pinned_session")
def test_fetch_llms_txt_reports_ssrf_blocked_targets_as_a_user_error(pinned_session_mock: Mock) -> None:
    pinned_session_mock.side_effect = SSRFBlockedError("Private IP address not allowed")

    with pytest.raises(LlmsTxtFetchError, match="publicly accessible"):
        fetch_llms_txt("https://internal.example/llms.txt")


@patch("products.web_analytics.backend.llms_txt.pinned_session")
def test_fetch_llms_txt_gives_up_once_the_redirect_limit_is_reached(pinned_session_mock: Mock) -> None:
    redirect = _response(status_code=302, headers={"Location": "/next"})
    pinned_session_mock.side_effect = [nullcontext(_session(redirect)) for _ in range(LLMS_TXT_MAX_REDIRECTS + 1)]

    with pytest.raises(LlmsTxtFetchError, match="redirected too many times"):
        fetch_llms_txt("https://example.com/llms.txt")

    assert pinned_session_mock.call_count == LLMS_TXT_MAX_REDIRECTS + 1


@patch("products.web_analytics.backend.llms_txt.pinned_session")
def test_fetch_llms_txt_gives_up_on_a_host_that_trickles_bytes(pinned_session_mock: Mock) -> None:
    clock = _Clock()
    response = _response(chunks=list(repeat(b"x", 10_000)), on_read=lambda: clock.advance(1.0))
    pinned_session_mock.return_value = nullcontext(_session(response))

    with patch("products.web_analytics.backend.llms_txt.time.monotonic", clock):
        with pytest.raises(LlmsTxtFetchError, match="took too long"):
            fetch_llms_txt("https://example.com/llms.txt")

    assert clock.now <= LLMS_TXT_TOTAL_BUDGET_SECONDS + 1.0


@patch("products.web_analytics.backend.llms_txt.pinned_session")
def test_fetch_llms_txt_rejects_a_body_the_host_compressed_anyway(pinned_session_mock: Mock) -> None:
    response = _response(
        headers={"Content-Type": "text/plain", "Content-Encoding": "gzip"},
        chunks=[b"\x1f\x8b\x08\x00"],
    )
    pinned_session_mock.return_value = nullcontext(_session(response))

    with pytest.raises(LlmsTxtFetchError, match="compressed"):
        fetch_llms_txt("https://example.com/llms.txt")
