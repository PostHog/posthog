from collections.abc import Iterator
from typing import Any, Optional, cast

import pytest

import requests
import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.docusign import DocusignResumeConfig

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

PRIVATE_KEY_PEM: str = _KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
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


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: Any = None, url: str = "https://na3.docusign.net") -> None:
        self.status_code = status_code
        self._payload = payload
        self.url = url

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def text(self) -> str:
        return str(self._payload)

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload

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
        get_responses: Optional[list[FakeResponse]] = None,
        post_responses: Optional[list[FakeResponse]] = None,
    ) -> None:
        self.get_queue: list[FakeResponse] = list(get_responses or [])
        self.post_queue: list[FakeResponse] = list(post_responses or [])
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append((url, kwargs))
        if not self.get_queue:
            raise AssertionError(f"unexpected GET {url}")
        return self.get_queue.pop(0)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append((url, kwargs))
        if not self.post_queue:
            raise AssertionError(f"unexpected POST {url}")
        return self.post_queue.pop(0)

    def as_session(self) -> requests.Session:
        """Hand this fake to helpers that take a real `requests.Session`."""
        return cast("requests.Session", self)


class FakeResumeManager(ResumableSourceManager[DocusignResumeConfig]):
    """In-memory resume manager so transport tests don't need Redis."""

    def __init__(self, state: Optional[DocusignResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[DocusignResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[DocusignResumeConfig]:
        return self.state

    def save_state(self, data: DocusignResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


@pytest.fixture
def logger() -> Iterator[FilteringBoundLogger]:
    yield structlog.get_logger("docusign-test")
