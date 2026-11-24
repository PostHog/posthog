import json
import base64
import binascii
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import responses

TRACK_HOSTS = ("track.customer.io", "track-eu.customer.io")
ENTITY_PATH = "/api/v2/entity"


@dataclass(frozen=True)
class TrackRequest:
    host: str
    path: str
    body: dict[str, Any]


class FakeCustomerIOTrackAPI:
    def __init__(self, site_id: str, api_key: str) -> None:
        self.site_id = site_id
        self.api_key = api_key
        self.received: list[TrackRequest] = []

    @contextmanager
    def installed(self) -> Iterator["FakeCustomerIOTrackAPI"]:
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            for host in TRACK_HOSTS:
                http.add_callback(responses.POST, f"https://{host}{ENTITY_PATH}", callback=self._entity)
            yield self

    def attributes_for(self, email: str) -> dict[str, Any]:
        attributes: dict[str, Any] = {}
        for request in self.received:
            body = request.body
            if body["type"] == "person" and body["action"] == "identify" and body["identifiers"] == {"email": email}:
                attributes.update(body["attributes"])
        return attributes

    def _entity(self, request: Any) -> tuple[int, dict[str, str], str]:
        if _basic_credentials(request.headers.get("Authorization", "")) != (self.site_id, self.api_key):
            return 401, {}, json.dumps({"meta": {"error": "Unauthorized request"}})
        url = urlsplit(request.url)
        self.received.append(TrackRequest(host=url.hostname or "", path=url.path, body=json.loads(request.body)))
        return 200, {}, "{}"


def _basic_credentials(authorization: str) -> tuple[str, str] | None:
    scheme, _, token = authorization.partition(" ")
    if scheme != "Basic":
        return None
    try:
        site_id, _, api_key = base64.b64decode(token, validate=True).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return None
    return site_id, api_key
