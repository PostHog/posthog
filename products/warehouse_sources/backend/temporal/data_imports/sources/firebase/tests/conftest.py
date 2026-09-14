import json
from collections.abc import Iterator
from typing import Any, Optional, cast

import pytest

import requests
import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.firebase import (
    FirebaseCredentials,
    FirebaseResumeConfig,
)

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

PRIVATE_KEY_PEM: str = _KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()

PUBLIC_KEY_PEM: str = (
    _KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)

TOKEN_PAYLOAD: dict[str, Any] = {"access_token": "tok-1", "expires_in": 3600, "token_type": "Bearer"}


class FakeRaw:
    """Minimal stand-in for urllib3's response body: a capped, position-tracking read().

    `bytes_read` lets a test assert how much of an oversized body actually got pulled into memory,
    which is the whole point of the caps — a body that is merely *rejected* after being fully
    buffered would still have caused the memory spike.
    """

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.bytes_read = 0

    def read(self, amt: Optional[int] = None, decode_content: bool = False) -> bytes:
        end = len(self._body) if amt is None else min(self.bytes_read + amt, len(self._body))
        chunk = self._body[self.bytes_read : end]
        self.bytes_read = end
        return chunk


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: Any = None,
        url: str = "https://firestore.googleapis.com/v1",
        body: Optional[bytes] = None,
    ) -> None:
        self.status_code = status_code
        self.url = url
        # The transport reads bodies via `raw.read(...)` under a byte cap and never calls `.json()`,
        # so the fake carries the payload as serialized bytes exactly like a real response would —
        # and deliberately offers no `.json()`, so a regression back to it fails loudly. `body` lets
        # a test supply bytes directly, for the oversized and malformed cases `payload` can't express.
        if body is None:
            body = b"" if payload is None else json.dumps(payload).encode()
        self.raw = FakeRaw(body)
        self.closed = False

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def close(self) -> None:
        self.closed = True

    def raise_for_status(self) -> None:
        if self.ok:
            return
        label = "Client Error" if self.status_code < 500 else "Server Error"
        response = requests.Response()
        response.status_code = self.status_code
        response.url = self.url
        raise requests.HTTPError(f"{self.status_code} {label}: for url: {self.url}", response=response)


class FakeSession:
    """Stand-in for the tracked session: pops queued responses and records every call."""

    def __init__(
        self,
        request_responses: Optional[list[FakeResponse]] = None,
        post_responses: Optional[list[FakeResponse]] = None,
    ) -> None:
        self.request_queue: list[FakeResponse] = list(request_responses or [])
        self.post_queue: list[FakeResponse] = list(post_responses or [])
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        if not self.request_queue:
            raise AssertionError(f"unexpected {method} {url}")
        return self.request_queue.pop(0)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.posts.append((url, kwargs))
        if not self.post_queue:
            raise AssertionError(f"unexpected POST {url}")
        return self.post_queue.pop(0)

    def as_session(self) -> requests.Session:
        """Hand this fake to helpers that take a real `requests.Session`."""
        return cast("requests.Session", self)


class FakeResumeManager(ResumableSourceManager[FirebaseResumeConfig]):
    """In-memory resume manager so transport tests don't need Redis."""

    def __init__(self, state: Optional[FirebaseResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[FirebaseResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[FirebaseResumeConfig]:
        return self.state

    def save_state(self, data: FirebaseResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def credentials(**overrides: Any) -> FirebaseCredentials:
    defaults: dict[str, Any] = {
        "project_id": "demo-project",
        "client_email": "importer@demo-project.iam.gserviceaccount.com",
        "private_key": PRIVATE_KEY_PEM,
        "private_key_id": "key-id",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    defaults.update(overrides)
    return FirebaseCredentials(**defaults)


@pytest.fixture
def logger() -> Iterator[FilteringBoundLogger]:
    yield structlog.get_logger("firebase-test")
