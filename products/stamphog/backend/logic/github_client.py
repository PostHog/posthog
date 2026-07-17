"""Dedicated GitHub App client for Stamphog.

Stamphog runs as its own GitHub App (separate identity from PostHog's product-integration App), so it
mints its own installation tokens from ``STAMPHOG_GITHUB_APP_CLIENT_ID`` (or ``STAMPHOG_GITHUB_APP_ID``
as a fallback) / ``STAMPHOG_GITHUB_APP_PRIVATE_KEY``.
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
from urllib.parse import quote

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


def expected_app_bot_login() -> str | None:
    """The GitHub login this App acts under (``<slug>[bot]``), or None if the slug is unconfigured.

    GitHub App reviews and comments are authored by ``<app-slug>[bot]`` with ``user.type == "Bot"``.
    When we know the slug we can require that exact identity; when it isn't configured, callers decide
    whether "any Bot" is an acceptable floor (see ``_is_own_bot_actor``'s ``allow_any_bot``). Public
    (not underscore-prefixed) because the in-flight reviewer-bot wait in ``temporal/activities.py``
    needs it too, to exclude stamphog's own 👀 reaction from the trusted-bot reactor set it reads.
    """
    slug = settings.STAMPHOG_GITHUB_APP_SLUG
    return f"{slug}[bot]" if slug else None


def _is_own_bot_actor(user: dict, expected_login: str | None, *, allow_any_bot: bool) -> bool:
    """Whether ``user`` (a review's or comment's author object) is this App's own bot identity.

    The identity floor: a Bot author, and — when the App slug is configured — the exact ``<slug>[bot]``
    login. ``allow_any_bot`` decides the unconfigured-slug case. Sticky-comment upserts tolerate the
    "any Bot" fallback (a mis-targeted PATCH is cosmetic). Write-adjacent approval decisions
    (adopt-before-post, the GitHub-side orphan sweep) must NOT: dismissing or adopting another bot's
    review off a fuzzy match is worse than doing nothing, so they pass ``allow_any_bot=False`` and get
    nothing without a slug. Reviews and comments carry the same ``user`` shape, so this serves both.
    """
    if user.get("type") != "Bot":
        return False
    if expected_login is not None:
        return (user.get("login") or "") == expected_login
    return allow_any_bot


def _is_own_sticky_comment(comment: dict, expected_login: str | None) -> bool:
    """Whether ``comment`` was posted by this App, not just any account carrying the marker.

    The marker is visible in the rendered comment source, so a user could plant it to trick a naive
    upsert into PATCHing (hijacking) their comment. The "any Bot" fallback is acceptable here — a
    mis-targeted sticky PATCH is cosmetic, never a standing approval (contrast the approval paths).
    """
    return _is_own_bot_actor(comment.get("user") or {}, expected_login, allow_any_bot=True)


# Cap on how many comment/file pages we page through, so a pathological PR can't spin forever.
_MAX_PAGES = 20
_PER_PAGE = 100

# Trim each inline review-thread comment body to bound the payload that rides in run.output. The
# reviewer only needs the gist of a maintainer's "do not merge", not a novel.
_REVIEW_THREAD_BODY_MAX = 4000

# reviewThreads(first: 100) × comments(first: 50) is 5,000 worst-case nodes — far under GitHub's
# 500,000 pre-execution node cap. Only the fields the hosted reviewer needs: resolution state,
# path/line, and per comment the author identity triple (login, association, Bot-ness) the engine's
# author-trust gate requires plus the body. The comments pageInfo detects per-thread overflow —
# a >50-comment thread must fail closed, not silently drop comment 51 (a maintainer's hold).
_REVIEW_THREADS_QUERY = """
query($owner: String!, $name: String!, $pr: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved
          isOutdated
          path
          line
          comments(first: 50) {
            pageInfo { hasNextPage }
            nodes {
              author { login __typename }
              authorAssociation
              body
            }
          }
        }
      }
    }
  }
}
"""

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
    10-minute maximum. The client id is the issuer — the same form the core GitHub integration
    signs with (see ``posthog.models.github_integration_base``).
    """
    # Client id is the preferred issuer (matches the core GitHub integration); the app id fallback
    # covers workers whose chart predates the client id env. Drop the fallback once every worker
    # deploy ships STAMPHOG_GITHUB_APP_CLIENT_ID.
    issuer = settings.STAMPHOG_GITHUB_APP_CLIENT_ID or settings.STAMPHOG_GITHUB_APP_ID
    if not issuer:
        raise StamphogGitHubError("Neither STAMPHOG_GITHUB_APP_CLIENT_ID nor STAMPHOG_GITHUB_APP_ID is configured")
    now = int(time.time())
    try:
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": str(issuer)},
            _app_private_key(),
            algorithm="RS256",
        )
    except Exception as exc:
        raise StamphogGitHubError("Failed to encode Stamphog App JWT; check STAMPHOG_GITHUB_APP_PRIVATE_KEY") from exc


# --- User-to-server OAuth: installation ownership verification ---
#
# Binding an installation's repos to a team is only safe if the caller can prove they own that GitHub
# App installation. A bare installation_id is caller-supplied and forgeable, so we mirror the shared
# PostHog App's flow: exchange the post-install OAuth `code` for the *user's* own access token, then
# confirm the installation is one that user can actually reach.


def exchange_oauth_code_for_user_token(code: str) -> str | None:
    """Exchange a Stamphog user-to-server OAuth ``code`` for the authorizing user's access token.

    Talks to ``github.com/login/oauth/access_token`` (the App's OAuth endpoint, not the REST API) with
    Stamphog's *own* client id/secret. Returns the user access token, or ``None`` when the creds are
    unset or GitHub rejects the code — callers must treat ``None`` as "unverified" and fail closed.
    """
    client_id = settings.STAMPHOG_GITHUB_APP_CLIENT_ID
    client_secret = settings.STAMPHOG_GITHUB_APP_CLIENT_SECRET
    if not client_id or not client_secret:
        # No creds means we can't verify ownership, so we must not bind anything.
        logger.warning("stamphog github: STAMPHOG_GITHUB_APP_CLIENT_ID/SECRET unset, cannot verify installation")
        return None

    # github.com/login is the App's OAuth host, not api.github.com, so it goes over plain requests
    # (identical to how the shared PostHog App exchanges its code) rather than the REST egress transport.
    response = requests.post(
        "https://github.com/login/oauth/access_token",
        json={"client_id": client_id, "client_secret": client_secret, "code": code},
        headers={"Accept": "application/json"},
        timeout=10,
    )
    try:
        data = response.json()
    except ValueError:
        logger.warning("stamphog github: non-JSON response exchanging OAuth code", status_code=response.status_code)
        return None
    access_token = data.get("access_token")
    if not access_token:
        # Never log token/error bodies verbatim — just the coarse GitHub error slug.
        logger.warning("stamphog github: OAuth code exchange returned no access_token", error=data.get("error"))
        return None
    return str(access_token)


def list_user_installations(user_access_token: str) -> list[dict[str, str]]:
    """This App's installations the OAuth'd user can reach, as ``[{"id", "account_login"}, ...]``.

    Pages ``GET /user/installations`` with the *user's* token, which GitHub scopes to installations of
    THIS App the user can access — the discovery primitive for the authorize-first connect flow, where
    no installation_id rides in the callback. Authenticated with the user token, so it is identity-blind
    on the egress budget (no ``installation_id`` passed to the gate) — GitHub meters it against the user,
    not the installation. Raises :class:`StamphogGitHubError` on an unexpected status so the caller fails
    closed rather than silently treating an API hiccup as "no installations".
    """
    installations: list[dict[str, str]] = []
    for page in range(1, _MAX_PAGES + 1):
        response = github_request(
            "GET",
            "https://api.github.com/user/installations",
            source=_SOURCE,
            headers={"Authorization": f"Bearer {user_access_token}"},
            endpoint="/user/installations",
            params={"per_page": _PER_PAGE, "page": page},
            timeout=10,
        )
        raise_if_github_rate_limited(response)
        if response.status_code != 200:
            raise StamphogGitHubError(
                f"Failed to list user installations: {response.text[:200]}", status_code=response.status_code
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise StamphogGitHubError("Non-JSON response listing user installations") from exc
        page_installations = data.get("installations") if isinstance(data, dict) else None
        if not isinstance(page_installations, list):
            raise StamphogGitHubError("Unexpected user installations payload")
        for installation in page_installations:
            if not isinstance(installation, dict) or installation.get("id") is None:
                continue
            installations.append(
                {
                    "id": str(installation.get("id")),
                    "account_login": ((installation.get("account") or {}).get("login") or ""),
                }
            )
        if len(page_installations) < _PER_PAGE:
            break
    return installations


def user_can_access_installation(installation_id: str, user_access_token: str) -> bool:
    """Whether the OAuth'd user can reach the given App installation.

    Built on :func:`list_user_installations`: the submitted id must be among the installations visible to
    the user's token. Raises :class:`StamphogGitHubError` on an unexpected status (via the underlying
    call) so the caller fails closed rather than silently treating an API hiccup as "no access".
    """
    return any(
        installation["id"] == str(installation_id) for installation in list_user_installations(user_access_token)
    )


def list_user_accessible_repositories(installation_id: str, user_access_token: str) -> list[str]:
    """Repos in the installation that the OAuth'd *user* can access, as sorted ``owner/name`` names.

    Reads ``GET /user/installations/{id}/repositories`` with the USER token — deliberately not the app
    installation token. The installation covers every repo the installer selected, but a given user may
    only be able to reach a subset; binding the full installation set would let a user who can see one
    repo attach repos they can't access. This endpoint returns only the user-visible subset. Raises
    :class:`StamphogGitHubError` on an unexpected status so the caller fails closed.
    """
    full_names: list[str] = []
    for page in range(1, _MAX_PAGES + 1):
        response = github_request(
            "GET",
            f"https://api.github.com/user/installations/{installation_id}/repositories",
            source=_SOURCE,
            headers={"Authorization": f"Bearer {user_access_token}"},
            endpoint="/user/installations/{installation_id}/repositories",
            params={"per_page": _PER_PAGE, "page": page},
            timeout=10,
        )
        raise_if_github_rate_limited(response)
        if response.status_code != 200:
            raise StamphogGitHubError(
                f"Failed to list user-accessible installation repositories: {response.text[:200]}",
                status_code=response.status_code,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise StamphogGitHubError("Non-JSON response listing user installation repositories") from exc
        repositories = data.get("repositories") if isinstance(data, dict) else None
        if not isinstance(repositories, list):
            raise StamphogGitHubError("Unexpected user installation repositories payload")
        for repo in repositories:
            full_name = repo.get("full_name") if isinstance(repo, dict) else None
            if isinstance(full_name, str) and full_name:
                full_names.append(full_name)
        if len(repositories) < _PER_PAGE:
            break
    return sorted(set(full_names))


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

    def get_pr_reactions(self, repo: str, number: int) -> list[dict]:
        """Reactions on the PR itself, as ``[{user, content, created_at}]``, fully paginated.

        Feeds the in-flight reviewer-bot wait (a trusted bot's fresh 👀 means its review is still
        running). Pagination matters for safety, not volume: anyone can react on a public PR, so an
        author could push the bot's 👀 past the first page with junk reactions and make the wait
        treat the bot as absent. If even the page cap is exceeded, fail closed (raise) rather than
        silently approve over a possibly in-flight review.
        """
        reactions: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            path = f"/repos/{repo}/issues/{number}/reactions"
            response = self._request(
                "GET",
                path,
                endpoint="/repos/{owner}/{repo}/issues/{issue_number}/reactions",
                params={"per_page": _PER_PAGE, "page": page},
            )
            if response.status_code != 200:
                raise StamphogGitHubError(
                    f"Failed to fetch reactions for {repo}#{number}: {response.text[:300]}",
                    status_code=response.status_code,
                )
            items = self._json(response, path)
            reactions.extend(
                {
                    "user": (item.get("user") or {}).get("login") or "",
                    "content": item.get("content") or "",
                    "created_at": item.get("created_at") or "",
                }
                for item in items
            )
            if len(items) < _PER_PAGE:
                return reactions
        raise StamphogGitHubError(
            f"Reactions on {repo}#{number} exceed {_MAX_PAGES * _PER_PAGE}; refusing to evaluate a truncated list"
        )

    def add_pr_reaction(self, repo: str, number: int, content: str = "eyes") -> int | None:
        """Add a reaction to the PR itself (``POST .../issues/{number}/reactions``), returning its id.

        Fail-open, UNLIKE every other method on this client: an 👀 reaction is the same cosmetic
        "review in flight" signal ``get_pr_reactions``/``STAMPHOG_TRUSTED_REACTOR_BOTS`` reads off
        other bots, never a gate on anything. A failed reaction post must never fail or retry the
        calling review activity, so every exception and non-2xx response is caught and logged here
        instead of raised — callers get ``None`` and carry on. GitHub itself returns 200 with the
        EXISTING reaction if this identity already reacted with ``content`` on this target (natural
        idempotency: a retried activity, or adopting a crashed predecessor's leftover reaction), or
        201 with a freshly created one — either way the id is what callers persist to remove later.
        """
        path = f"/repos/{repo}/issues/{number}/reactions"
        try:
            response = self._request(
                "POST",
                path,
                endpoint="/repos/{owner}/{repo}/issues/{issue_number}/reactions",
                json_body={"content": content},
            )
        except Exception:
            logger.warning("stamphog github: failed to add PR reaction", repo=repo, pr_number=number, exc_info=True)
            return None
        if response.status_code not in (200, 201):
            logger.warning(
                "stamphog github: unexpected status adding PR reaction",
                repo=repo,
                pr_number=number,
                status_code=response.status_code,
            )
            return None
        try:
            data = self._json(response, path)
        except StamphogGitHubError:
            logger.warning("stamphog github: non-JSON response adding PR reaction", repo=repo, pr_number=number)
            return None
        reaction_id = data.get("id") if isinstance(data, dict) else None
        return reaction_id if isinstance(reaction_id, int) else None

    def remove_pr_reaction(self, repo: str, number: int, reaction_id: int) -> None:
        """Remove a reaction from the PR itself (``DELETE .../issues/{number}/reactions/{reaction_id}``).

        Fail-open like ``add_pr_reaction``, for the same reason: this only cleans up the cosmetic
        "review in flight" 👀, so a failure here must never fail or retry the calling activity — a
        leftover reaction is harmless (the next run's ``add_pr_reaction`` adopts it via GitHub's own
        idempotency). Every exception and non-2xx response is caught and logged instead of raised.
        A 404 means the reaction is already gone (a prior attempt succeeded before crashing, or
        someone removed it by hand) and is treated the same as success.
        """
        path = f"/repos/{repo}/issues/{number}/reactions/{reaction_id}"
        try:
            response = self._request(
                "DELETE",
                path,
                endpoint="/repos/{owner}/{repo}/issues/{issue_number}/reactions/{reaction_id}",
            )
        except Exception:
            logger.warning("stamphog github: failed to remove PR reaction", repo=repo, pr_number=number, exc_info=True)
            return
        if response.status_code not in (200, 204, 404):
            logger.warning(
                "stamphog github: unexpected status removing PR reaction",
                repo=repo,
                pr_number=number,
                status_code=response.status_code,
            )

    def get_collaborator_permission(self, repo: str, username: str) -> str:
        """The user's effective permission on the repo: ``admin``, ``write``, ``read``, or ``none``.

        GitHub's legacy ``permission`` field collapses ``maintain`` into ``write`` and ``triage`` into
        ``read``, which is exactly the granularity the reviewer's author gate needs. A 404 means the
        user has no access at all and maps to ``none``.
        """
        path = f"/repos/{repo}/collaborators/{quote(username)}/permission"
        response = self._request("GET", path, endpoint="/repos/{owner}/{repo}/collaborators/{username}/permission")
        if response.status_code == 404:
            return "none"
        if response.status_code != 200:
            raise StamphogGitHubError(
                f"Failed to fetch collaborator permission for {username} on {repo}: {response.text[:300]}",
                status_code=response.status_code,
            )
        return self._json(response, path).get("permission") or "none"

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

    def get_pr_reviews(self, repo: str, number: int) -> list[dict]:
        """Fetch the PR's top-level reviews, paginating through GitHub's list endpoint.

        Returns the raw GitHub review objects (``user``, ``state``, ``commit_id``, ``body``,
        ``author_association``, ...). The reviewer engine needs these to honor an active
        ``CHANGES_REQUESTED`` review — without them the hosted path would run review-blind and could
        approve over a maintainer's block. Stops at ``_MAX_PAGES`` for the same bound as the other lists.
        """
        reviews: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            response = self._request(
                "GET",
                f"/repos/{repo}/pulls/{number}/reviews",
                endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
                params={"per_page": _PER_PAGE, "page": page},
            )
            if response.status_code != 200:
                raise StamphogGitHubError(
                    f"Failed to fetch PR reviews {repo}#{number}: {response.text[:300]}",
                    status_code=response.status_code,
                )
            page_reviews = self._json(response, f"/repos/{repo}/pulls/{number}/reviews")
            if not isinstance(page_reviews, list):
                raise StamphogGitHubError(f"Unexpected PR reviews payload for {repo}#{number}")
            reviews.extend(review for review in page_reviews if isinstance(review, dict))
            if len(page_reviews) < _PER_PAGE:
                break
        return reviews

    def list_own_active_approvals(self, repo: str, number: int) -> list[dict]:
        """Active APPROVE reviews on the PR authored by THIS App, as raw GitHub review dicts.

        Built on ``get_pr_reviews``' pagination. "Active APPROVED" means ``state == "APPROVED"`` — GitHub
        reports a dismissed review as state ``DISMISSED``, so those drop out on their own. Identity uses
        the same floor as the sticky-comment path but WITHOUT the "any Bot" fallback: this feeds
        write-adjacent decisions (adopt-before-post in ``post_verdict``, the GitHub-side orphan sweep in
        ``dismiss_stale_approvals``), where acting on another bot's review off a fuzzy match is worse than
        doing nothing — so an unconfigured ``STAMPHOG_GITHUB_APP_SLUG`` yields an empty list, never a guess.
        Callers filter further (e.g. adopt only at an exact ``commit_id``); the raw dicts carry ``id`` and
        ``commit_id`` for that.
        """
        expected_login = expected_app_bot_login()
        if expected_login is None:
            return []
        return [
            review
            for review in self.get_pr_reviews(repo, number)
            if review.get("state") == "APPROVED"
            and _is_own_bot_actor(review.get("user") or {}, expected_login, allow_any_bot=False)
        ]

    def get_pr_discussion(self, repo: str, number: int) -> list[dict]:
        """Fetch the PR's top-level discussion (issue) comments, paginating through GitHub's endpoint.

        Returns raw GitHub issue-comment objects (``user``, ``body``, ``author_association``, ...). The
        reviewer uses these as blocker context — a maintainer's top-level "please hold" comment should
        reach the agent, matching the Action path. Inline review-thread comments are a separate,
        GraphQL-only surface (thread resolution state) fetched by ``get_pr_review_threads``. Past the page cap the
        fetch fails closed (raises) like the reactions fetch: anyone can comment on a public PR, so an
        author could bury a maintainer's hold past the cap and a silently truncated list would read as
        "no blockers" to the reviewer.
        """
        comments: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            response = self._request(
                "GET",
                f"/repos/{repo}/issues/{number}/comments",
                endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
                params={"per_page": _PER_PAGE, "page": page},
            )
            if response.status_code != 200:
                raise StamphogGitHubError(
                    f"Failed to fetch PR discussion {repo}#{number}: {response.text[:300]}",
                    status_code=response.status_code,
                )
            page_comments = self._json(response, f"/repos/{repo}/issues/{number}/comments")
            if not isinstance(page_comments, list):
                raise StamphogGitHubError(f"Unexpected PR discussion payload for {repo}#{number}")
            comments.extend(comment for comment in page_comments if isinstance(comment, dict))
            if len(page_comments) < _PER_PAGE:
                return comments
        raise StamphogGitHubError(
            f"PR discussion on {repo}#{number} exceeds {_MAX_PAGES * _PER_PAGE} comments; "
            "refusing to review with a truncated discussion"
        )

    def get_pr_review_threads(self, repo: str, number: int) -> list[dict]:
        """Fetch the PR's inline review threads via GraphQL, as
        ``[{is_resolved, is_outdated, path, line,
        comments: [{author, author_association, author_is_bot, body}]}]``.

        Each comment carries the author identity triple (login, association, Bot-ness) because the
        engine gates inline comments through the same author-trust check as reviews and discussion —
        without it, an untrusted external commenter could plant a fake maintainer hold in the prompt.

        Inline review-thread comments are a GraphQL-only surface — REST exposes no thread-resolution
        state — so the hosted reviewer would otherwise be blind to a maintainer's unresolved inline
        "this is wrong, do not merge". Follows ``get_user_team_slugs``' ``/graphql`` request shape but NOT
        its best-effort error handling: FAILS CLOSED like ``get_pr_discussion`` — raises past the page cap
        or on any GraphQL/HTTP/parse failure — because a silently truncated thread list reads as "no
        blockers" to the reviewer, the one wrong answer here. Comment bodies are trimmed to bound the
        payload that rides in ``run.output``.
        """
        if "/" not in repo:
            raise StamphogGitHubError(f"Expected an owner/name repo, got {repo!r}")
        owner, name = repo.split("/", 1)
        threads: list[dict] = []
        cursor: str | None = None
        for _page in range(_MAX_PAGES):
            response = self._request(
                "POST",
                "/graphql",
                endpoint="/graphql",
                json_body={
                    "query": _REVIEW_THREADS_QUERY,
                    "variables": {"owner": owner, "name": name, "pr": number, "cursor": cursor},
                },
            )
            if response.status_code != 200:
                raise StamphogGitHubError(
                    f"Failed to fetch review threads for {repo}#{number}: {response.text[:300]}",
                    status_code=response.status_code,
                )
            data = self._json(response, "/graphql")
            if not isinstance(data, dict) or data.get("errors"):
                raise StamphogGitHubError(f"GraphQL errors fetching review threads for {repo}#{number}")
            pull_request = ((data.get("data") or {}).get("repository") or {}).get("pullRequest")
            if not isinstance(pull_request, dict):
                raise StamphogGitHubError(f"Unexpected review-threads payload for {repo}#{number}")
            review_threads = pull_request.get("reviewThreads") or {}
            for node in review_threads.get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                comment_page = node.get("comments") or {}
                # A thread past the comments fetch window would silently lose its tail — and a
                # maintainer's hold could be comment 51. Fail closed, matching the Action's behavior.
                if (comment_page.get("pageInfo") or {}).get("hasNextPage"):
                    raise StamphogGitHubError(
                        f"A review thread on {repo}#{number} ({node.get('path')}) has more comments than one "
                        "fetch window; refusing to review with a truncated thread"
                    )
                comments = [
                    {
                        "author": (comment.get("author") or {}).get("login") or "",
                        "author_association": comment.get("authorAssociation") or "",
                        "author_is_bot": (comment.get("author") or {}).get("__typename") == "Bot",
                        "body": (comment.get("body") or "")[:_REVIEW_THREAD_BODY_MAX],
                    }
                    for comment in comment_page.get("nodes") or []
                    if isinstance(comment, dict)
                ]
                threads.append(
                    {
                        "is_resolved": bool(node.get("isResolved")),
                        "is_outdated": bool(node.get("isOutdated")),
                        "path": node.get("path") or "",
                        "line": node.get("line"),
                        "comments": comments,
                    }
                )
            page_info = review_threads.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                return threads
            cursor = page_info.get("endCursor")
        raise StamphogGitHubError(
            f"Review threads on {repo}#{number} exceed {_MAX_PAGES} pages; refusing to review a truncated list"
        )

    def get_check_runs(self, repo: str, head_sha: str) -> list[dict]:
        """Fetch the check runs for a commit, paginating through GitHub's endpoint.

        Returns the raw GitHub check-run objects (``name``, ``conclusion``, ``status``, ...). The engine's
        migration gate uses them: a passing ``Migration risk`` check lets a migration-only PR bypass the
        deny-list. Without them the hosted path can't see that success and over-refuses safe migration PRs.
        Bounded by ``_MAX_PAGES``.
        """
        check_runs: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            response = self._request(
                "GET",
                f"/repos/{repo}/commits/{head_sha}/check-runs",
                endpoint="/repos/{owner}/{repo}/commits/{ref}/check-runs",
                params={"per_page": _PER_PAGE, "page": page},
            )
            if response.status_code != 200:
                raise StamphogGitHubError(
                    f"Failed to fetch check runs {repo}@{head_sha}: {response.text[:300]}",
                    status_code=response.status_code,
                )
            data = self._json(response, f"/repos/{repo}/commits/{head_sha}/check-runs")
            page_runs = data.get("check_runs") if isinstance(data, dict) else None
            if not isinstance(page_runs, list):
                raise StamphogGitHubError(f"Unexpected check runs payload for {repo}@{head_sha}")
            check_runs.extend(run for run in page_runs if isinstance(run, dict))
            if len(page_runs) < _PER_PAGE:
                break
        return check_runs

    def get_author_merged_pr_numbers(self, repo: str, author: str, *, max_results: int = 1000) -> list[int]:
        """Return the author's merged-PR numbers in this repo (best-effort).

        Feeds the sandbox's git-blame familiarity signal, which the Action normally
        derives from its own ``gh pr list`` call — impossible in the tokenless
        sandbox, so the server (which holds the token) fetches it and injects it
        into the review context. Best-effort like the Action's path: any failure
        returns what was collected so far, and an empty result simply leaves the
        familiarity signal absent (a one-way ratchet, never a stricter verdict).
        """
        query = f"repo:{repo} type:pr is:merged author:{author}"
        numbers: list[int] = []
        pages = max(1, max_results // _PER_PAGE)
        for page in range(1, pages + 1):
            try:
                response = self._request(
                    "GET",
                    "/search/issues",
                    endpoint="/search/issues",
                    params={"q": query, "per_page": _PER_PAGE, "page": page},
                )
            except Exception:
                logger.warning("stamphog_github_author_prs_request_failed", repo=repo, author=author, exc_info=True)
                break
            if response.status_code != 200:
                logger.warning(
                    "stamphog_github_author_prs_http_error",
                    repo=repo,
                    author=author,
                    status_code=response.status_code,
                )
                break
            data = self._json(response, "/search/issues")
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                break
            for item in items:
                number = item.get("number") if isinstance(item, dict) else None
                if isinstance(number, int) and not isinstance(number, bool):
                    numbers.append(number)
            if len(items) < _PER_PAGE:
                break
        return numbers

    def list_installation_repositories(self) -> list[str]:
        """Return the sorted ``owner/name`` full names this installation can access.

        Reads ``GET /installation/repositories`` with the installation token (the endpoint is scoped to
        the token's own installation, so no id goes in the path), paging until exhausted. Used by the
        install→team binding flow to discover which repos to register when a user installs the App.
        """
        full_names: list[str] = []
        for page in range(1, _MAX_PAGES + 1):
            response = self._request(
                "GET",
                "/installation/repositories",
                endpoint="/installation/repositories",
                params={"per_page": _PER_PAGE, "page": page},
            )
            if response.status_code != 200:
                raise StamphogGitHubError(
                    f"Failed to list installation repositories: {response.text[:300]}",
                    status_code=response.status_code,
                )
            data = self._json(response, "/installation/repositories")
            repositories = data.get("repositories") if isinstance(data, dict) else None
            if not isinstance(repositories, list):
                raise StamphogGitHubError("Unexpected installation repositories payload")
            for repo in repositories:
                full_name = repo.get("full_name") if isinstance(repo, dict) else None
                if isinstance(full_name, str) and full_name:
                    full_names.append(full_name)
            if len(repositories) < _PER_PAGE:
                break
        return sorted(set(full_names))

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

    def remove_pr_label(self, repo: str, number: int, label: str) -> None:
        """Remove a label from a PR (``DELETE .../issues/{number}/labels/{label}``).

        Strips the trigger label after a refused/escalated verdict in label-triggered review mode, so
        the author re-adds it to request another review — Action parity. A 404 means the label is
        already gone (benign, swallowed); any other non-success raises so the activity can retry.
        """
        path = f"/repos/{repo}/issues/{number}/labels/{quote(label, safe='')}"
        response = self._request(
            "DELETE",
            path,
            endpoint="/repos/{owner}/{repo}/issues/{issue_number}/labels/{name}",
        )
        if response.status_code == 404:
            logger.info("stamphog github: label already absent, skipping removal", repo=repo, pr_number=number)
            return
        if response.status_code != 200:
            raise StamphogGitHubError(
                f"Failed to remove label from {repo}#{number}: {response.text[:200]}",
                status_code=response.status_code,
            )

    def dismiss_pr_review(self, repo: str, pr_number: int, review_id: int, message: str) -> None:
        """Dismiss a previously submitted review (``PUT .../reviews/{review_id}/dismissals``).

        Used to retract a stale stamphog APPROVE once the PR head moves — GitHub keeps an approval
        satisfying required reviews until it is explicitly dismissed. A 422 means the review is no
        longer active (already dismissed, or the PR state changed underneath us), a benign no-op we
        swallow; any other non-success raises so a real failure isn't mistaken for a dismissal.
        """
        path = f"/repos/{repo}/pulls/{pr_number}/reviews/{review_id}/dismissals"
        response = self._request(
            "PUT",
            path,
            endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/reviews/{review_id}/dismissals",
            json_body={"message": message, "event": "DISMISS"},
        )
        if response.status_code == 422:
            logger.info(
                "stamphog github: review no longer active, skipping dismissal",
                repo=repo,
                pr_number=pr_number,
                review_id=review_id,
            )
            return
        if response.status_code != 200:
            raise StamphogGitHubError(
                f"Failed to dismiss review {review_id} on {repo}#{pr_number}: {response.text[:200]}",
                status_code=response.status_code,
            )

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
        """Return the id of the App's own sticky comment on the PR, or ``None`` if there isn't one.

        Matching on the marker alone would let a user plant the (source-visible) marker and have the App
        PATCH their comment; candidates are filtered to this App's bot identity (see
        _is_own_sticky_comment) so an impostor comment is ignored and a fresh one is posted instead.
        """
        expected_login = expected_app_bot_login()
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
                if not (isinstance(comment, dict) and STICKY_COMMENT_MARKER in (comment.get("body") or "")):
                    continue
                if not _is_own_sticky_comment(comment, expected_login):
                    continue
                comment_id = comment.get("id")
                if isinstance(comment_id, int):
                    return comment_id
            if len(comments) < _PER_PAGE:
                break
        return None
