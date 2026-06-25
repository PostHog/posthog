from base64 import b64encode
from typing import Literal, Optional

from requests import PreparedRequest
from requests.auth import AuthBase

TApiKeyLocation = Literal["header", "query", "param", "cookie"]


class AuthConfigBase(AuthBase):
    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        return request

    def __bool__(self) -> bool:
        return True

    def secret_values(self) -> tuple[str, ...]:
        """Credential strings this auth carries, for log redaction.

        The tracked HTTP transport masks these wherever they appear in logged
        URLs, headers, and sampled bodies — so a credential injected under a
        param/header name the denylist scrubber can't know in advance (e.g. an
        API key in a query param) is still redacted. Each subclass declares its
        own secret so the list can't drift from the field that holds it.
        """
        return ()


class BearerTokenAuth(AuthConfigBase):
    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.token,) if self.token else ()


class APIKeyAuth(AuthConfigBase):
    def __init__(
        self,
        api_key: Optional[str] = None,
        name: str = "Authorization",
        location: TApiKeyLocation = "header",
    ) -> None:
        self.api_key = api_key
        self.name = name
        self.location = location

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        if self.location == "header":
            request.headers[self.name] = self.api_key or ""
        elif self.location in ("query", "param"):
            request.prepare_url(request.url, {self.name: self.api_key})
        elif self.location == "cookie":
            request.prepare_cookies({self.name: self.api_key or ""})
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.api_key,) if self.api_key else ()


class HttpBasicAuth(AuthConfigBase):
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.username = username
        self.password = password

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        encoded = b64encode(f"{self.username}:{self.password}".encode()).decode()
        request.headers["Authorization"] = f"Basic {encoded}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.password,) if self.password else ()


def auth_secret_values(auth: Optional[AuthBase]) -> tuple[str, ...]:
    """Secret credential strings carried by an auth object, for log redaction.

    Delegates to :meth:`AuthConfigBase.secret_values` so the knowledge of which
    field is secret lives on each auth class. Returns ``()`` for ``None`` or any
    auth that isn't an :class:`AuthConfigBase`.
    """
    return auth.secret_values() if isinstance(auth, AuthConfigBase) else ()
