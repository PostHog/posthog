from __future__ import annotations

import json
import socket
import http.client
from collections.abc import Callable, Iterator
from contextlib import closing
from typing import Any
from urllib.parse import SplitResult, quote, urljoin, urlsplit

from .deadline import remaining
from .translate_out import translate_error
from .types import Credentials, EngineError


def _invalid() -> EngineError:
    return EngineError([{"code": "lookup_failed", "message": "Check the project URL and run the command again."}])


def api_url(credentials: Credentials, route: str) -> SplitResult:
    try:
        host = urlsplit(credentials["host"])
        project = str(credentials["project_id"])
        if not credentials["api_key"]:
            raise EngineError(translate_error("Missing API key"))
        if (
            host.scheme not in {"http", "https"}
            or not host.hostname
            or host.username is not None
            or host.password is not None
            or host.query
            or host.fragment
            or not project.isascii()
            or not project.isdigit()
        ):
            raise _invalid()
        return host._replace(path=f"{host.path.rstrip('/')}/api/{route}/")
    except (TypeError, ValueError, KeyError) as exc:
        if isinstance(exc, EngineError):
            raise
        raise _invalid() from None


def collection_url(credentials: Credentials, collection: str, scope: str = "projects") -> SplitResult:
    return api_url(credentials, f"{scope}/{credentials.get('project_id')}/{collection}")


def detail_url(collection: SplitResult, identifier: str) -> SplitResult:
    if (
        not identifier
        or identifier in (".", "..")
        or any(c in identifier for c in "/\\%")
        or any(ord(c) < 32 or ord(c) == 127 for c in identifier)
    ):
        raise _invalid()
    return collection._replace(path=collection.path + quote(identifier, safe="") + "/", query="")


def _body(response: http.client.HTTPResponse, sock: socket.socket | None, deadline: float | None) -> object:
    if deadline is None:
        return json.load(response)
    body = bytearray()
    while not response.isclosed():
        timeout = min(30.0, remaining(deadline))
        if sock is not None:
            sock.settimeout(timeout)
        chunk = response.read1(65536)
        if not chunk:
            break
        body.extend(chunk)
    remaining(deadline)
    return json.loads(body)


def get(
    credentials: Credentials,
    url: SplitResult,
    deadline: float | None,
    *,
    on_error: Callable[[int, Any], Any] | None = None,
) -> Any:
    connection = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    try:
        timeout = min(30.0, remaining(deadline)) if deadline is not None else 30
        with closing(connection(url.hostname or "", port=url.port, timeout=timeout)) as client:
            client.request(
                "GET",
                url.path + ("?" + url.query if url.query else ""),
                headers={"Authorization": "Bearer " + credentials["api_key"], "Accept": "application/json"},
            )
            sock = client.sock if deadline is not None else None
            if sock is not None and deadline is not None:
                sock.settimeout(min(30.0, remaining(deadline)))
            response = client.getresponse()
            if response.status != 200:
                if on_error is not None:
                    try:
                        problem = _body(response, sock, deadline)
                    except ValueError as exc:
                        if isinstance(exc, EngineError):
                            raise
                        problem = None
                    return on_error(response.status, problem)
                raise EngineError(translate_error(f"HTTP {response.status}"))
            return _body(response, sock, deadline)
    except (TypeError, ValueError, http.client.HTTPException) as exc:
        if isinstance(exc, EngineError):
            raise
        raise _invalid() from None
    except OSError:
        if deadline is not None:
            remaining(deadline)
        raise EngineError(translate_error("network timeout")) from None


def rows(credentials: Credentials, start: SplitResult, deadline: float | None) -> Iterator[dict[str, Any]]:
    page = start
    visited: set[str] = set()
    while True:
        if (
            (page.scheme, page.netloc, page.path) != (start.scheme, start.netloc, start.path)
            or page.fragment
            or page.query in visited
        ):
            raise _invalid()
        visited.add(page.query)
        data = get(credentials, page, deadline)
        if isinstance(data, list):
            result, following = data, None
        elif isinstance(data, dict) and isinstance(data.get("results"), list):
            result, following = data["results"], data.get("next")
        else:
            raise _invalid()
        for row in result:
            if not isinstance(row, dict):
                raise _invalid()
            yield row
        if following is None:
            return
        if not isinstance(following, str):
            raise _invalid()
        try:
            page = urlsplit(urljoin(page.geturl(), following))
        except ValueError:
            raise _invalid() from None
