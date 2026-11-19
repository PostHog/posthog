import math
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import cast

import httpx
import requests

from posthog.egress.limiter.policies import Priority

from .sources import GitHubReader

CHECK_DEADLINE = timedelta(minutes=4)


class CheckDeadlineExceeded(Exception):
    pass


@dataclass(frozen=True)
class CheckDeadline:
    expires_at: float

    @classmethod
    def starting_now(cls, length: timedelta = CHECK_DEADLINE) -> "CheckDeadline":
        return cls(expires_at=time.monotonic() + length.total_seconds())

    def seconds_left(self, cap_seconds: float) -> float:
        remaining_seconds = self.expires_at - time.monotonic()
        if remaining_seconds <= 0:
            raise CheckDeadlineExceeded()
        return min(cap_seconds, remaining_seconds)

    def raise_if_expired(self) -> None:
        self.seconds_left(cap_seconds=0)


class DeadlineGitHub:
    def __init__(self, github: GitHubReader, deadline: CheckDeadline) -> None:
        self.github = github
        self.deadline = deadline

    def api_request(
        self,
        method: str,
        path: str,
        *,
        endpoint: str | None = None,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
        priority: Priority | None = None,
    ) -> requests.Response:
        self.deadline.raise_if_expired()
        return self.github.api_request(
            method, path, endpoint=endpoint, params=params, headers=headers, priority=priority
        )


class DeadlineStream(httpx.SyncByteStream):
    def __init__(self, stream: httpx.SyncByteStream, deadline: CheckDeadline) -> None:
        self.stream = stream
        self.deadline = deadline

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.stream:
            self.deadline.raise_if_expired()
            yield chunk

    def close(self) -> None:
        self.stream.close()


class DeadlineTransport(httpx.BaseTransport):
    def __init__(self, deadline: CheckDeadline) -> None:
        self.deadline = deadline
        self.transport = httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        timeout_by_phase = request.extensions.get("timeout", {})
        request.extensions["timeout"] = {
            phase: self.deadline.seconds_left(math.inf if seconds is None else seconds)
            for phase, seconds in timeout_by_phase.items()
        }
        response = self.transport.handle_request(request)
        response.stream = DeadlineStream(cast(httpx.SyncByteStream, response.stream), self.deadline)
        return response

    def close(self) -> None:
        self.transport.close()


def deadline_http(deadline: CheckDeadline, *, timeout_seconds: float) -> httpx.Client:
    return httpx.Client(timeout=timeout_seconds, transport=DeadlineTransport(deadline))
