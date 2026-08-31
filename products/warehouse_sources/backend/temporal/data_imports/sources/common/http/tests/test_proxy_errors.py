import time
import socket

import pytest
from unittest import mock

from parameterized import parameterized
from requests.exceptions import ProxyError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import proxy_errors

PROXY_502 = (
    "HTTPSConnectionPool(host='gone.my.salesforce.com', port=443): Max retries exceeded with url: "
    "/services/oauth2/token (Caused by ProxyError('Cannot connect to proxy.', "
    "OSError('Tunnel connection failed: 502 Bad gateway')))"
)


def _gaierror(errno: int) -> socket.gaierror:
    return socket.gaierror(errno, "resolver said so")


@parameterized.expand(
    [
        # The bug this module exists for: a hostname that no longer exists is replayed on every
        # scheduled run because the proxy reports it as a gateway status.
        ("nxdomain", _gaierror(socket.EAI_NONAME), "gone.my.salesforce.com"),
        # A resolver outage on our side must never disable a customer's working source, so
        # anything short of "this name does not exist" stays retryable.
        ("temporary_resolver_failure", _gaierror(socket.EAI_AGAIN), None),
        ("resolver_socket_error", OSError("resolver socket blew up"), None),
    ]
)
@pytest.mark.asyncio
async def test_only_a_definitive_nxdomain_is_treated_as_permanent(
    _name: str, resolver_error: Exception, expected: str | None
):
    with mock.patch.object(socket, "getaddrinfo", side_effect=resolver_error):
        assert await proxy_errors.unresolvable_host_behind_proxy(ProxyError(PROXY_502)) == expected


@pytest.mark.asyncio
async def test_a_resolver_error_that_is_not_a_name_verdict_does_not_escape():
    # `getaddrinfo` raises UnicodeError (not OSError) for a DNS label over 63 characters. Letting it
    # escape replaces the source's real error with a spurious one inside the shared error handler,
    # which loses the actual cause and burns the retry budget.
    long_label = "a" * 64
    error = ProxyError(
        f"HTTPSConnectionPool(host='{long_label}.example.com', port=443): Max retries exceeded "
        "(Caused by ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 502 Bad gateway')))"
    )

    assert await proxy_errors.unresolvable_host_behind_proxy(error) is None


@pytest.mark.asyncio
async def test_host_comes_from_the_pool_repr_not_from_echoed_response_text():
    # A source can echo `host='...'` back in a response body. Taking the first match in the message
    # would resolve that text, get NXDOMAIN, and disable a schema whose real host is alive.
    error = ProxyError(
        'Source responded: {"detail": "host=\'wat is this\' Cannot connect to proxy."} '
        "HTTPSConnectionPool(host='real-and-alive.example.com', port=443)"
    )

    with mock.patch.object(socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]) as resolve:
        assert await proxy_errors.unresolvable_host_behind_proxy(error) is None

    assert resolve.call_args.args[0] == "real-and-alive.example.com"


@pytest.mark.asyncio
async def test_a_resolver_that_does_not_answer_in_time_stays_retryable():
    # `getaddrinfo` has no timeout of its own, so a wedged resolver would otherwise hold this path
    # until the activity's own start-to-close timeout.
    def _hang(*_args: object, **_kwargs: object) -> None:
        time.sleep(30)

    with (
        mock.patch.object(proxy_errors, "_RESOLVE_TIMEOUT_SECONDS", 0.05),
        mock.patch.object(socket, "getaddrinfo", side_effect=_hang),
    ):
        assert await proxy_errors.unresolvable_host_behind_proxy(ProxyError(PROXY_502)) is None


@pytest.mark.asyncio
async def test_proxy_failure_against_a_live_host_stays_retryable():
    with mock.patch.object(socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
        assert await proxy_errors.unresolvable_host_behind_proxy(ProxyError(PROXY_502)) is None


@parameterized.expand(
    [
        ("connection_reset", ProxyError("Connection reset by peer")),
        ("unrelated", ValueError("nothing to do with the proxy")),
    ]
)
@pytest.mark.asyncio
async def test_errors_that_are_not_proxy_connect_failures_are_ignored(_name: str, error: Exception):
    # No resolver patch: a non-CONNECT error must be rejected before any DNS lookup happens.
    assert await proxy_errors.unresolvable_host_behind_proxy(error) is None


@pytest.mark.asyncio
async def test_host_is_read_from_the_request_url_when_the_message_has_no_pool_repr():
    error = ProxyError("Cannot connect to proxy.")
    error.request = mock.MagicMock(url="https://gone.example.com/v1/records?token=x")

    with mock.patch.object(socket, "getaddrinfo", side_effect=_gaierror(socket.EAI_NONAME)):
        assert await proxy_errors.unresolvable_host_behind_proxy(error) == "gone.example.com"


@pytest.mark.asyncio
async def test_proxy_failure_with_no_discoverable_host_is_ignored():
    with mock.patch.object(socket, "getaddrinfo", side_effect=_gaierror(socket.EAI_NONAME)) as resolve:
        assert await proxy_errors.unresolvable_host_behind_proxy(ProxyError("Cannot connect to proxy.")) is None

    resolve.assert_not_called()
