"""Dedicated GitHub App client for Stamphog.

Stamphog runs as its own GitHub App (separate identity from PostHog's product-integration App), so it
mints its own installation tokens from ``STAMPHOG_GITHUB_APP_ID`` / ``STAMPHOG_GITHUB_APP_PRIVATE_KEY``.
Every outbound call goes through the shared egress transport (:func:`posthog.egress.github.transport.github_request`),
which gates on the installation's shared budget and records telemetry by construction. That transport is
token-agnostic and stateless, so a second App identity needs no change to the egress layer — this client
just supplies its own ``Authorization`` header and the installation id as the budget scope.
"""

import time
import base64
import binascii
from datetime import datetime
from typing import Any

from django.conf import settings
from django.core.cache import cache

import jwt
import requests
import structlog

from posthog.egress.github.limiter import remember_observed_core_limit
from posthog.egress.github.transport import github_request, raise_if_github_rate_limited
from posthog.egress.limiter.policies import Priority

logger = structlog.get_logger(__name__)

# Per-subsystem attribution on the shared GitHub egress metrics.
_SOURCE = "stamphog"

# Hidden marker that identifies Stamphog's single sticky status comment on a PR, so a re-review updates
# the same comment in place instead of stacking a new one every run. Invisible in the rendered comment.
STICKY_COMMENT_MARKER = "<!-- stamphog:review-status -->"

# Cap on how many comment/file pages we page through, so a pathological PR can't spin forever.
_MAX_PAGES = 20
_PER_PAGE = 100

# Refresh the installation token this many seconds before GitHub's stated expiry, to cover clock skew
# and in-flight requests. GitHub installation tokens live one hour, so a 5-minute margin is ample.
_TOKEN_EXPIRY_MARGIN_SECONDS = 300


class StamphogGitHubError(Exception):
    """A Stamphog GitHub API call failed for a non-rate-limit reason (auth failure, unexpected status,
    malformed response). Rate limits raise ``GitHubRateLimitError`` from the egress layer instead."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _app_private_key() -> str:
    """The Stamphog App private key, with escaped newlines restored (env vars often carry ``\\n``)."""
    key = settings.STAMPHOG_GITHUB_APP_PRIVATE_KEY
    if not key:
        raise StamphogGitHubError("STAMPHOG_GITHUB_APP_PRIVATE_KEY is not configured")
    return key.replace("\\n", "\n").strip()


def _build_app_jwt() -> str:
    """Build a short-lived App JWT (RS256) for minting installation tokens.

    ``iat`` is backdated 60s to tolerate clock skew against GitHub; ``exp`` stays inside GitHub's
    10-minute maximum. The App id is the issuer.
    """
    app_id = settings.STAMPHOG_GITHUB_APP_ID
    if not app_id:
        raise StamphogGitHubError("STAMPHOG_GITHUB_APP_ID is not configured")
    now = int(time.time())
    try:
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": str(app_id)},
            _app_private_key(),
            algorithm="RS256",
        )
    except Exception as exc:
        raise StamphogGitHubError("Failed to encode Stamphog App JWT; check STAMPHOG_GITHUB_APP_PRIVATE_KEY") from exc


class StamphogGitHubClient:
    """Installation-scoped GitHub client for one Stamphog App installation.

    Holds an installation id, mints and caches its installation token, and exposes the narrow set of
    read/write operations the reviewer needs. Stateless beyond the cached token, so callers construct
    one per review run.
    """

    def __init__(self, installation_id: str) -> None:
        self.installation_id = installation_id

    # --- Installation token lifecycle ---

    def _token_cache_key(self) -> str:
        return f"stamphog:github:installation_token:{self.installation_id}"

    def _mint_installation_token(self) -> tuple[str, int]:
        """Mint a fresh installation token via the App JWT. Returns ``(token, expires_at_epoch)``."""
        response = github_request(
            "POST",
            f"https://api.github.com/app/installations/{self.installation_id}/access_tokens",
            source=_SOURCE,
            headers={"Authorization": f"Bearer {_build_app_jwt()}"},
            endpoint="/app/installations/{installation_id}/access_tokens",
            timeout=10,
        )
        if response.status_code != 201:
            raise StamphogGitHubError(
                f"Failed to mint Stamphog installation token: {response.text[:300]}",
                status_code=response.status_code,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise StamphogGitHubError("Non-JSON response minting installation token") from exc

        token = data.get("token")
        expires_at = data.get("expires_at")
        if not token or not expires_at:
            raise StamphogGitHubError("Installation token response missing token/expires_at")
        try:
            expires_epoch = int(datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp())
        except ValueError as exc:
            raise StamphogGitHubError(f"Invalid expires_at from GitHub: {expires_at}") from exc
        return token, expires_epoch

    def _get_installation_token(self, *, force_refresh: bool = False) -> str:
        """Return a valid installation token, minting (and caching) a new one when needed.

        The token is cached in the shared Django cache keyed by installation id so every worker draws
        from one token rather than each minting its own. ``force_refresh`` bypasses the cache after a
        401 (the token was revoked or the installation's permissions changed under us).
        """
        cache_key = self._token_cache_key()
        if not force_refresh:
            cached = cache.get(cache_key)
            if isinstance(cached, dict) and cached.get("token") and cached.get("expires_at"):
                if int(cached["expires_at"]) - _TOKEN_EXPIRY_MARGIN_SECONDS > int(time.time()):
                    return str(cached["token"])

        token, expires_epoch = self._mint_installation_token()
        # Expire the cache entry a margin before GitHub does, so a served token always has headroom.
        ttl = max(1, expires_epoch - _TOKEN_EXPIRY_MARGIN_SECONDS - int(time.time()))
        cache.set(cache_key, {"token": token, "expires_at": expires_epoch}, timeout=ttl)
        return token

    # --- Core request helper ---

    def _request(
        self,
        method: str,
        path: str,
        *,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 15,
    ) -> requests.Response:
        """Installation-authenticated request through the gated egress transport.

        Refreshes the token once on a 401 (revoked/rotated token). Raises ``GitHubRateLimitError`` on a
        rate limit so the caller can back off; every other response is returned for status-driven
        handling. ``path`` is an absolute ``/...`` API path; ``endpoint`` is the normalized telemetry label.
        """
        if not path.startswith("/"):
            raise ValueError(f"path must start with '/', got {path!r}")
        url = f"https://api.github.com{path}"

        for attempt in range(2):
            token = self._get_installation_token(force_refresh=attempt == 1)
            response = github_request(
                method,
                url,
                source=_SOURCE,
                headers={**(headers or {}), "Authorization": f"Bearer {token}"},
                installation_id=self.installation_id,
                priority=Priority.CRITICAL,
                endpoint=endpoint,
                params=params,
                json=json_body,
                timeout=timeout,
            )
            # Only trusted installation-token responses feed the limiter's per-installation tier tracking.
            remember_observed_core_limit(self.installation_id, response)
            if response.status_code == 401 and attempt == 0:
                logger.info("stamphog github: 401, refreshing installation token", installation_id=self.installation_id)
                continue
            raise_if_github_rate_limited(response)
            return response
        raise StamphogGitHubError(f"Stamphog GitHub request exhausted retries on {path}")

    def _json(self, response: requests.Response, path: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise StamphogGitHubError(f"Non-JSON response on {path}", status_code=response.status_code) from exc

    # --- Read operations ---

    def get_pr(self, repo: str, number: int) -> dict:
        """Fetch the pull request object (``GET /repos/{repo}/pulls/{number}``)."""
        path = f"/repos/{repo}/pulls/{number}"
        response = self._request("GET", path, endpoint="/repos/{owner}/{repo}/pulls/{pull_number}")
        if response.status_code != 200:
            raise StamphogGitHubError(
                f"Failed to fetch PR {repo}#{number}: {response.text[:300]}", status_code=response.status_code
            )
        return self._json(response, path)

    def get_pr_files(self, repo: str, number: int) -> list[dict]:
        """Fetch the PR's changed files, paginating through GitHub's list endpoint.

        Returns the raw GitHub file objects (``filename``, ``status``, ``additions``, ``deletions``,
        ``patch``, ...). Stops at ``_MAX_PAGES`` so an enormous PR can't page unbounded.
        """
        files: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            response = self._request(
                "GET",
                f"/repos/{repo}/pulls/{number}/files",
                endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/files",
                params={"per_page": _PER_PAGE, "page": page},
            )
            if response.status_code != 200:
                raise StamphogGitHubError(
                    f"Failed to fetch PR files {repo}#{number}: {response.text[:300]}",
                    status_code=response.status_code,
                )
            page_files = self._json(response, f"/repos/{repo}/pulls/{number}/files")
            if not isinstance(page_files, list):
                raise StamphogGitHubError(f"Unexpected PR files payload for {repo}#{number}")
            files.extend(file for file in page_files if isinstance(file, dict))
            if len(page_files) < _PER_PAGE:
                break
        return files

    def get_default_branch_file(self, repo: str, path: str) -> str | None:
        """Fetch a file's text from the repo's DEFAULT branch, or ``None`` if it doesn't exist.

        Policy files are always read from the default branch (never PR head), so a PR can't rewrite the
        policy that gates it. Omitting ``ref`` makes GitHub serve the default branch. The ``raw`` media
        type returns the file body directly (no base64 wrapper); a 404 means the file is absent.
        """
        response = self._request(
            "GET",
            f"/repos/{repo}/contents/{path}",
            endpoint="/repos/{owner}/{repo}/contents/{path}",
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise StamphogGitHubError(
                f"Failed to fetch {repo}:{path}: {response.text[:200]}", status_code=response.status_code
            )
        # The raw media type yields the body directly. Some proxies/older responses may still send the
        # JSON contents object (base64) — decode that as a fallback so callers always get text.
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            data = self._json(response, f"/repos/{repo}/contents/{path}")
            if isinstance(data, dict) and data.get("encoding") == "base64" and isinstance(data.get("content"), str):
                try:
                    return base64.b64decode(data["content"]).decode("utf-8")
                except (binascii.Error, UnicodeDecodeError) as exc:
                    raise StamphogGitHubError(f"Failed to decode base64 contents for {repo}:{path}") from exc
        return response.text

    # --- Write operations ---

    def post_approve_review(self, repo: str, number: int, body: str, commit_id: str) -> dict:
        """Submit an APPROVE review pinned to ``commit_id`` (``POST .../pulls/{number}/reviews``).

        Pinning to the reviewed head SHA means an approval never silently carries over to commits pushed
        after the review. Raises on any non-success so a failed approval is never mistaken for a success.
        """
        path = f"/repos/{repo}/pulls/{number}/reviews"
        response = self._request(
            "POST",
            path,
            endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            json_body={"event": "APPROVE", "body": body, "commit_id": commit_id},
        )
        if response.status_code not in (200, 201):
            raise StamphogGitHubError(
                f"Failed to approve PR {repo}#{number}: {response.text[:300]}", status_code=response.status_code
            )
        return self._json(response, path)

    def upsert_sticky_comment(self, repo: str, number: int, body: str) -> dict:
        """Create or update Stamphog's single status comment on a PR, identified by a hidden marker.

        Finds an existing comment carrying :data:`STICKY_COMMENT_MARKER` and edits it in place; otherwise
        posts a new one. The marker is prepended so it survives round-trips but stays invisible in the
        rendered comment. Returns the created/updated comment object.
        """
        marked_body = f"{STICKY_COMMENT_MARKER}\n{body}"
        existing_id = self._find_sticky_comment_id(repo, number)
        if existing_id is not None:
            path = f"/repos/{repo}/issues/comments/{existing_id}"
            response = self._request(
                "PATCH",
                path,
                endpoint="/repos/{owner}/{repo}/issues/comments/{comment_id}",
                json_body={"body": marked_body},
            )
            if response.status_code != 200:
                raise StamphogGitHubError(
                    f"Failed to update sticky comment on {repo}#{number}: {response.text[:200]}",
                    status_code=response.status_code,
                )
            return self._json(response, path)

        path = f"/repos/{repo}/issues/{number}/comments"
        response = self._request(
            "POST",
            path,
            endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json_body={"body": marked_body},
        )
        if response.status_code != 201:
            raise StamphogGitHubError(
                f"Failed to create sticky comment on {repo}#{number}: {response.text[:200]}",
                status_code=response.status_code,
            )
        return self._json(response, path)

    def get_user_team_slugs(self, org: str, login: str) -> list[str]:
        """Return the sorted GitHub team slugs ``login`` belongs to within ``org`` (GraphQL).

        Best-effort: this feeds digest audience routing, never a hard requirement, so every failure
        mode (HTTP error, GraphQL ``errors`` — typically the App installation missing the org's
        "Members: read" permission — or a null organization) logs a warning and returns ``[]`` instead
        of raising.
        """
        query = (
            "query($org: String!, $login: String!) { "
            "organization(login: $org) { teams(first: 100, userLogins: [$login]) { nodes { slug } } } }"
        )
        try:
            response = self._request(
                "POST",
                "/graphql",
                endpoint="/graphql",
                json_body={"query": query, "variables": {"org": org, "login": login}},
            )
        except Exception:
            logger.warning("stamphog_github_team_lookup_request_failed", org=org, login=login, exc_info=True)
            return []

        if response.status_code != 200:
            logger.warning(
                "stamphog_github_team_lookup_http_error",
                org=org,
                login=login,
                status_code=response.status_code,
                body=response.text[:200],
            )
            return []

        try:
            data = self._json(response, "/graphql")
        except StamphogGitHubError:
            logger.warning("stamphog_github_team_lookup_non_json_response", org=org, login=login)
            return []

        if not isinstance(data, dict) or data.get("errors"):
            logger.warning(
                "stamphog_github_team_lookup_graphql_errors",
                org=org,
                login=login,
                errors=(data or {}).get("errors") if isinstance(data, dict) else None,
            )
            return []

        organization = (data.get("data") or {}).get("organization")
        if not organization:
            logger.warning("stamphog_github_team_lookup_null_organization", org=org, login=login)
            return []

        nodes = (organization.get("teams") or {}).get("nodes") or []
        return sorted({node["slug"] for node in nodes if isinstance(node, dict) and node.get("slug")})

    def _find_sticky_comment_id(self, repo: str, number: int) -> int | None:
        """Return the id of the existing sticky comment on the PR, or ``None`` if there isn't one."""
        for page in range(1, _MAX_PAGES + 1):
            response = self._request(
                "GET",
                f"/repos/{repo}/issues/{number}/comments",
                endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
                params={"per_page": _PER_PAGE, "page": page},
            )
            if response.status_code != 200:
                raise StamphogGitHubError(
                    f"Failed to list comments on {repo}#{number}: {response.text[:200]}",
                    status_code=response.status_code,
                )
            comments = self._json(response, f"/repos/{repo}/issues/{number}/comments")
            if not isinstance(comments, list):
                raise StamphogGitHubError(f"Unexpected comments payload for {repo}#{number}")
            for comment in comments:
                if isinstance(comment, dict) and STICKY_COMMENT_MARKER in (comment.get("body") or ""):
                    comment_id = comment.get("id")
                    if isinstance(comment_id, int):
                        return comment_id
            if len(comments) < _PER_PAGE:
                break
        return None
