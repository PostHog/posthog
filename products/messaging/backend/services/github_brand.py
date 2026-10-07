import json
import math
import time
import dataclasses
from urllib.parse import quote

from django.core.cache import cache

import requests

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.models import Team, User
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration, Integration

from products.messaging.backend.services.email_logo import email_logo_content_type, store_email_logo
from products.messaging.backend.services.repository_brand import TreeEntry, detect_brand
from products.messaging.backend.services.repository_brand.files import MAX_FILE_BYTES
from products.messaging.backend.services.repository_brand.logos import MAX_LOGO_BYTES

_TIME_BUDGET_SECONDS = 15
_MAX_REQUEST_SECONDS = 5
_FRESH_SECONDS = 10 * 60
_CHUNK_BYTES = 8 * 1024
_MAX_JSON_BYTES = 32 * 1024 * 1024
_GITHUB_REFUSALS = (
    GitHubIntegrationError,
    GitHubRateLimitError,
    GitHubEgressBudgetExhausted,
    requests.RequestException,
)


class GitHubBusy(Exception):
    pass


class RepositoryUnreadable(Exception):
    pass


class _OutOfTime(Exception):
    pass


@frozen
class GitHubBrand:
    repository: str
    name: str | None
    primary_color: str | None
    logo_url: str | None


def detect_repository_brand(team: Team, user: User, integration: Integration, repository: str) -> GitHubBrand:
    cache_key = f"messaging:github_brand:{team.pk}:{integration.pk}:{repository.lower()}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and cached.get("fresh_until", 0) > time.time():
        return GitHubBrand(**{**cached["brand"], "repository": repository})
    reader = _RepositoryReader(integration, repository)
    brand = reader.detect(team, user)
    if not reader.ran_out_of_time:
        cache.set(
            cache_key, {"brand": dataclasses.asdict(brand), "fresh_until": time.time() + _FRESH_SECONDS}, _FRESH_SECONDS
        )
    return brand


class _RepositoryReader:
    def __init__(self, integration: Integration, repository: str) -> None:
        self._github = GitHubIntegration(integration, source="email_brand", priority=Priority.NORMAL)
        self._repository = repository
        self._deadline = time.monotonic() + _TIME_BUDGET_SECONDS
        self._blob_shas: dict[str, str] = {}
        self.ran_out_of_time = False

    def detect(self, team: Team, user: User) -> GitHubBrand:
        try:
            tree = self._tree()
        except _OutOfTime:
            tree = []
        brand = detect_brand(repository_name=self._repository, tree=tree, read_text=self._read_text)
        return GitHubBrand(
            repository=self._repository,
            name=brand.name,
            primary_color=brand.primary_color,
            logo_url=self._stored_logo_url(brand.logo_paths, team, user),
        )

    def _tree(self) -> list[TreeEntry]:
        repository = self._get_json(f"/repos/{self._repository}", endpoint="/repos/{owner}/{repo}")
        branch = repository.get("default_branch")
        if not isinstance(branch, str):
            raise GitHubBusy()
        tree = self._get_json(
            f"/repos/{self._repository}/git/trees/{quote(branch, safe='')}?recursive=1",
            endpoint="/repos/{owner}/{repo}/git/trees/{tree_sha}",
            empty_repository_ok=True,
        ).get("tree")
        blobs = [entry for entry in tree if _is_blob(entry)] if isinstance(tree, list) else []
        self._blob_shas = {entry["path"]: entry["sha"] for entry in blobs}
        return [TreeEntry(path=entry["path"], size=entry["size"]) for entry in blobs]

    def _stored_logo_url(self, logo_paths: tuple[str, ...], team: Team, user: User) -> str | None:
        for path in logo_paths:
            body = self._read_blob(path, MAX_LOGO_BYTES)
            if body is not None and (content_type := email_logo_content_type(body)) is not None:
                return store_email_logo(body, content_type, team, user)
        return None

    def _read_text(self, path: str) -> str | None:
        body = self._read_blob(path, MAX_FILE_BYTES)
        return body.decode("utf-8", errors="replace") if body is not None else None

    def _read_blob(self, path: str, limit: int) -> bytes | None:
        try:
            with self._get(
                f"/repos/{self._repository}/git/blobs/{quote(self._blob_shas[path], safe='')}",
                endpoint="/repos/{owner}/{repo}/git/blobs/{file_sha}",
                accept="application/vnd.github.raw+json",
            ) as response:
                return self._body_within(response, limit)
        except _OutOfTime:
            return None

    def _get_json(self, path: str, *, endpoint: str, empty_repository_ok: bool = False) -> dict[str, object]:
        with self._get(path, endpoint=endpoint, empty_repository_ok=empty_repository_ok) as response:
            if response.status_code == 409:
                return {}
            body = self._body_within(response, _MAX_JSON_BYTES)
        try:
            parsed = json.loads(body) if body is not None else None
        except ValueError as error:
            raise GitHubBusy() from error
        if not isinstance(parsed, dict):
            raise GitHubBusy()
        return parsed

    def _body_within(self, response: requests.Response, limit: int) -> bytes | None:
        body = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=_CHUNK_BYTES):
                self._request_timeout()
                body.extend(chunk)
                if len(body) > limit:
                    return None
        except requests.RequestException as error:
            raise GitHubBusy() from error
        return bytes(body)

    def _get(
        self, path: str, *, endpoint: str, accept: str | None = None, empty_repository_ok: bool = False
    ) -> requests.Response:
        try:
            response = self._github.api_request(
                "GET",
                path,
                endpoint=endpoint,
                timeout=self._request_timeout(),
                retry_transient=False,
                stream=True,
                headers={"Accept": accept} if accept else None,
            )
        except _GITHUB_REFUSALS as error:
            raise GitHubBusy() from error
        if response.status_code == 200 or (empty_repository_ok and response.status_code == 409):
            return response
        response.close()
        if response.status_code in (403, 404):
            raise RepositoryUnreadable()
        raise GitHubBusy()

    def _request_timeout(self) -> int:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            self.ran_out_of_time = True
            raise _OutOfTime()
        return min(_MAX_REQUEST_SECONDS, math.ceil(remaining))


def _is_blob(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and entry.get("type") == "blob"
        and isinstance(entry.get("path"), str)
        and isinstance(entry.get("sha"), str)
        and isinstance(entry.get("size"), int)
    )
