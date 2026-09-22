"""Source links: the repository file behind a resolved stack frame.

A frame's ``source`` is the path the bundler wrote into the source map. It is relative to the
map or to the bundler's context directory, so it rarely equals a repository path, and in a
monorepo the same relative path exists in several packages. Instead of searching code by
content, this module fetches the repository tree at the frame's commit once and places all
sources of a symbol set in that tree as one set: the directory that makes the most sources
exist is the anchor, and every source is placed relative to it.
"""

import re
import json
import time
import zlib
import struct
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Protocol

from django.conf import settings
from django.core.cache import cache

import requests
import structlog
import zstandard

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError, github_request
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError, GitLabIntegration, Integration
from posthog.storage import object_storage

from products.error_tracking.backend.models import ErrorTrackingRelease, ErrorTrackingStackFrame, ErrorTrackingSymbolSet

from . import batch_get_stack_frames

logger = structlog.get_logger(__name__)

GitProvider = Literal["github", "gitlab"]

MAX_RAW_IDS_PER_REQUEST = 500

# The stored container is compressed, so both the stored size and what it expands to are capped.
# Source maps are read for their ``sources`` alone, and a real bundler writes a short ``sourceRoot``,
# so the caps on the source list only stop a crafted map from expanding into gigabytes of paths.
MAX_SYMBOL_SET_BYTES = 50 * 1024 * 1024
MAX_SYMBOL_SET_DECOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_SOURCE_ROOT_LENGTH = 4096
MAX_SOURCES = 100_000
MAX_SOURCES_BYTES = 32 * 1024 * 1024
MAX_SOURCE_MAP_SECTION_DEPTH = 4

# A tree at a commit never changes, so it is kept for a week. Data read at a branch is trusted for
# an hour. After that a branch tree is revalidated with its ETag, which costs no rate limit budget
# when the branch did not move. A negative result is kept briefly so repeated page loads of an
# unreachable repository do not each cost a GitHub request.
PINNED_TTL_SECONDS = 7 * 24 * 60 * 60
BRANCH_TTL_SECONDS = 60 * 60
DEFAULT_BRANCH_TTL_SECONDS = 24 * 60 * 60
NEGATIVE_TTL_SECONDS = 5 * 60

GITHUB_API_TIMEOUT_SECONDS = 20

MAX_TREE_REQUESTS = 100
MAX_TREE_SPLIT_DEPTH = 4

_PROVIDER_HOSTS: dict[str, GitProvider] = {"github.com": "github", "gitlab.com": "gitlab"}
_REPO_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")

_VIRTUAL_FIRST_SEGMENTS = frozenset({"webpack", "(webpack)", "webpack-internal:", "node_modules"})
_VIRTUAL_PREFIXES = ("external ", "ignored|", "multi ", "<")


@frozen
class Repository:
    provider: GitProvider
    host: str
    owner: str
    name: str

    @property
    def path(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def url(self) -> str:
        return f"https://{self.host}/{self.owner}/{self.name}"


def parse_repository(value: str | None) -> Repository | None:
    """Parses a git remote or a bare ``owner/name`` into a repository on a supported host.

    Accepts ``https://github.com/o/r.git``, ``ssh://git@github.com/o/r``, ``git@github.com:o/r.git``
    and ``o/r``. A bare path means GitHub. GitLab groups keep their subgroups in ``owner``.
    """
    if not value:
        return None
    value = value.strip()
    if "://" in value:
        parsed = urllib.parse.urlparse(value)
        host = (parsed.hostname or "").lower()
        path = parsed.path
    elif "@" in value and ":" in value:
        host_part, _, path = value.partition(":")
        host = host_part.rpartition("@")[2].lower()
    else:
        host = "github.com"
        path = value

    provider = _PROVIDER_HOSTS.get(host)
    segments = [segment for segment in path.strip("/").split("/") if segment]
    if provider is None or len(segments) < 2:
        return None
    if provider == "github" and len(segments) != 2:
        return None
    segments[-1] = segments[-1].removesuffix(".git")
    if not all(_REPO_SEGMENT_RE.fullmatch(segment) and segment not in (".", "..") for segment in segments):
        return None
    return Repository(provider=provider, host=host, owner="/".join(segments[:-1]), name=segments[-1])


@frozen
class SourcePath:
    """A source map entry split into the ``..`` hops above its anchor and the path below it."""

    hops: int
    segments: tuple[str, ...]

    @property
    def relative(self) -> str:
        return "/".join(self.segments)


def parse_source(raw: str | None) -> SourcePath | None:
    """Reduces a bundler's source name to a repository-relative path shape.

    Strips ``webpack://<namespace>/`` and ``file://`` prefixes and a query string, then resolves
    ``.`` and ``..`` segments. Leading ``..`` segments cannot be resolved without knowing where the
    map lives, so they are counted as hops. Returns None for sources that are not repository files.
    """
    if not raw:
        return None
    value = raw.strip().replace("\\", "/")
    if value.startswith(_VIRTUAL_PREFIXES):
        return None

    scheme, separator, rest = value.partition("://")
    if separator:
        if scheme == "webpack":
            # "webpack:///./src/a.ts" has no namespace, "webpack://app/./src/a.ts" has one.
            value = rest[1:] if rest.startswith("/") else rest.partition("/")[2]
        else:
            value = rest.partition("/")[2]

    value = value.partition("?")[0]

    hops = 0
    segments: list[str] = []
    for segment in value.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if segments:
                segments.pop()
            else:
                hops += 1
            continue
        segments.append(segment)

    if not segments or any(segment in _VIRTUAL_FIRST_SEGMENTS for segment in segments):
        return None
    return SourcePath(hops=hops, segments=tuple(segments))


class RepositoryTree:
    """The blob paths of a repository at one ref, indexed by file name for suffix lookups."""

    def __init__(self, paths: Iterable[str]) -> None:
        self.paths: frozenset[str] = frozenset(paths)
        by_name: dict[str, list[str]] = defaultdict(list)
        for path in self.paths:
            by_name[path.rsplit("/", 1)[-1]].append(path)
        self._by_name = by_name

    def __contains__(self, path: object) -> bool:
        return path in self.paths

    def paths_ending_with(self, relative: str) -> list[str]:
        name = relative.rsplit("/", 1)[-1]
        suffix = "/" + relative
        return sorted(path for path in self._by_name.get(name, ()) if path == relative or path.endswith(suffix))


def match_sources(tree: RepositoryTree, sources: Iterable[str]) -> dict[str, str]:
    """Maps raw sources to repository paths.

    The sources of one symbol set share an anchor directory (the map's directory or the bundler's
    context), so they are placed as a set: every directory that holds one of the sources with the
    most common hop count is a candidate anchor, and the candidate under which the most sources
    exist wins. A source that does not fit under the winner falls back to a unique suffix match.
    """
    parsed = {raw: source for raw in dict.fromkeys(sources) if (source := parse_source(raw)) is not None}
    if not parsed or not tree.paths:
        return {}

    hop_counts: dict[int, int] = defaultdict(int)
    for source in parsed.values():
        hop_counts[source.hops] += 1
    anchor_hops = min(hop_counts, key=lambda hops: (-hop_counts[hops], hops))
    candidates: set[str] = set()
    for source in parsed.values():
        if source.hops != anchor_hops:
            continue
        for path in tree.paths_ending_with(source.relative):
            candidates.add(path[: -len(source.relative)].rstrip("/"))

    best_anchor: str | None = None
    best_score = 0
    # Shallower anchors first, so a tie between identical package layouts resolves the same way every time.
    for anchor in sorted(candidates, key=lambda candidate: (candidate.count("/") if candidate else -1, candidate)):
        score = sum(1 for source in parsed.values() if _place(anchor, anchor_hops, source) in tree)
        if score > best_score:
            best_anchor, best_score = anchor, score

    matched: dict[str, str] = {}
    for raw, source in parsed.items():
        placed = _place(best_anchor, anchor_hops, source) if best_anchor is not None else None
        if placed is not None and placed in tree:
            matched[raw] = placed
        elif (fallback := _unique_suffix_match(tree, source)) is not None:
            matched[raw] = fallback
    return matched


def _place(anchor: str, anchor_hops: int, source: SourcePath) -> str | None:
    """The path of ``source`` when sources with ``anchor_hops`` hops start at ``anchor``.

    A source with fewer hops than the anchor group starts somewhere below the anchor, in a
    directory the map does not name, so it cannot be placed here.
    """
    extra_hops = source.hops - anchor_hops
    anchor_segments = anchor.split("/") if anchor else []
    if extra_hops < 0 or extra_hops > len(anchor_segments):
        return None
    base = anchor_segments[: len(anchor_segments) - extra_hops]
    return "/".join([*base, *source.segments])


def _unique_suffix_match(tree: RepositoryTree, source: SourcePath) -> str | None:
    """The one path that ends with the source, dropping leading segments a build machine added.

    A match needs at least two segments unless the source itself has one. An ambiguous suffix
    stops the search: every shorter suffix matches a superset of the same paths.
    """
    segments = source.segments
    shortest = min(len(segments), 2)
    for start in range(0, len(segments) - shortest + 1):
        matches = tree.paths_ending_with("/".join(segments[start:]))
        if len(matches) == 1:
            return matches[0]
        if matches:
            return None
    return None


_CONTAINER_MAGIC = b"posthog_error_tracking"
_SOURCE_AND_MAP_TYPE = 2
_COMPRESSION_NONE = 0
_COMPRESSION_ZSTD = 1


def read_source_map(data: bytes) -> str:
    """The source map JSON inside a stored symbol set.

    Mirrors ``rust/common/symbol_data``: a magic string, a little-endian u32 version and data type,
    a compression byte from version 2 on, then a length-prefixed minified source followed by a
    length-prefixed source map.
    """
    if not data.startswith(_CONTAINER_MAGIC):
        raise ValueError("Not a symbol set container")
    offset = len(_CONTAINER_MAGIC)
    version, data_type = struct.unpack_from("<II", data, offset)
    offset += 8
    if data_type != _SOURCE_AND_MAP_TYPE:
        raise ValueError(f"Symbol set holds data type {data_type}, not a source map")
    if version == 1:
        payload = bytes(data[offset:])
    elif version == 2:
        compression = data[offset]
        payload = bytes(data[offset + 1 :])
        if compression == _COMPRESSION_ZSTD:
            payload = _decompress(payload)
        elif compression != _COMPRESSION_NONE:
            raise ValueError(f"Unknown symbol set compression {compression}")
    else:
        raise ValueError(f"Unknown symbol set container version {version}")

    (source_length,) = struct.unpack_from("<Q", payload, 0)
    (map_length,) = struct.unpack_from("<Q", payload, 8 + source_length)
    start = 16 + source_length
    return payload[start : start + map_length].decode("utf-8")


def _decompress(payload: bytes) -> bytes:
    # A zstd frame may declare its content size, and the decompressor then allocates that much
    # regardless of ``max_output_size``, so the declared size is checked first. A streamed frame
    # declares none, and the output cap stops it instead.
    if zstandard.frame_content_size(payload) > MAX_SYMBOL_SET_DECOMPRESSED_BYTES:
        raise ValueError("Symbol set expands past the permitted size")
    return zstandard.ZstdDecompressor().decompress(payload, max_output_size=MAX_SYMBOL_SET_DECOMPRESSED_BYTES)


def source_map_sources(source_map: str) -> list[str]:
    """The ``sources`` of a source map with ``sourceRoot`` applied the way the resolver applies it.

    An indexed map keeps its sources in ``sections[].map``, each with its own root. Returns an
    empty list when the map is not a source map or when a cap is passed, since the frames' own
    sources still give the matcher something to work with.
    """
    sources: list[str] = []
    total_length = 0
    maps = [json.loads(source_map)]
    for _ in range(MAX_SOURCE_MAP_SECTION_DEPTH + 1):
        sections: list[object] = []
        for parsed in maps:
            if not isinstance(parsed, dict):
                continue
            root = parsed.get("sourceRoot")
            root = root.rstrip("/") if isinstance(root, str) else ""
            if len(root) > MAX_SOURCE_ROOT_LENGTH:
                return []
            for source in parsed.get("sources") or []:
                if not isinstance(source, str) or not source:
                    continue
                keep_as_is = not root or source.startswith("/") or "://" in source
                total_length += len(source) if keep_as_is else len(root) + 1 + len(source)
                if len(sources) >= MAX_SOURCES or total_length > MAX_SOURCES_BYTES:
                    return []
                sources.append(source if keep_as_is else f"{root}/{source}")
            sections.extend(section.get("map") for section in parsed.get("sections") or [] if isinstance(section, dict))
        if not sections:
            break
        maps = sections
    return sources


def symbol_set_sources(symbol_set: ErrorTrackingSymbolSet) -> list[str] | None:
    """The sources of the stored map, or None when storage could not be read.

    A map that is missing, too large or malformed gives an empty list, because reading it again
    gives the same answer. A storage error gives None so the caller does not keep the result.
    """
    if not symbol_set.storage_ptr:
        return []
    try:
        head = object_storage.head_object(symbol_set.storage_ptr)
        if head and head.get("ContentLength", 0) > MAX_SYMBOL_SET_BYTES:
            logger.info("source_links_symbol_set_too_large", symbol_set_id=str(symbol_set.id))
            return []
        data = object_storage.read_bytes(symbol_set.storage_ptr)
    except Exception:
        logger.warning("source_links_symbol_set_unreadable", symbol_set_id=str(symbol_set.id), exc_info=True)
        return None
    if not data:
        return []
    try:
        return source_map_sources(read_source_map(data))
    except Exception:
        logger.info("source_links_symbol_set_rejected", symbol_set_id=str(symbol_set.id), exc_info=True)
        return []


# Circuit breaker for the shared public GitHub token. Django-cache-backed so it is shared across
# worker processes, and best-effort so a cache outage never blocks the request path.
_PUBLIC_TOKEN_CIRCUIT_OPEN_KEY = "error_tracking:github_public_token:circuit_open"
_PUBLIC_TOKEN_UNAUTHORIZED_COUNT_KEY = "error_tracking:github_public_token:unauthorized_count"
_UNAUTHORIZED_WINDOW_SECONDS = 600
_CIRCUIT_OPEN_SECONDS = 900
_UNAUTHORIZED_THRESHOLD = 3


class PublicGitHubTokenCircuit:
    """Trips off the shared public GitHub token after repeated 401s so a dead token stops spamming
    GitHub with unauthorized requests. While open, the public path behaves as if the token were unset."""

    def is_open(self) -> bool:
        try:
            return bool(cache.get(_PUBLIC_TOKEN_CIRCUIT_OPEN_KEY))
        except Exception:
            return False

    def record_success(self) -> None:
        try:
            cache.delete(_PUBLIC_TOKEN_UNAUTHORIZED_COUNT_KEY)
            cache.delete(_PUBLIC_TOKEN_CIRCUIT_OPEN_KEY)
        except Exception:
            pass

    def record_unauthorized(self) -> None:
        try:
            cache.add(_PUBLIC_TOKEN_UNAUTHORIZED_COUNT_KEY, 0, _UNAUTHORIZED_WINDOW_SECONDS)
            count = cache.incr(_PUBLIC_TOKEN_UNAUTHORIZED_COUNT_KEY)
            if count >= _UNAUTHORIZED_THRESHOLD:
                cache.set(_PUBLIC_TOKEN_CIRCUIT_OPEN_KEY, True, _CIRCUIT_OPEN_SECONDS)
                logger.error("github_public_token_circuit_opened", unauthorized_count=count)
        except Exception:
            pass


class GitHubApi(Protocol):
    def get(self, path: str, *, endpoint: str, etag: str | None = None) -> requests.Response | None:
        """A GET on the GitHub API, or None when no response arrived. ``etag`` makes it conditional."""
        ...


def _conditional_headers(etag: str | None) -> dict[str, str]:
    return {"If-None-Match": etag} if etag else {}


class InstallationGitHubApi:
    """Reads through the team's GitHub App installation, on the sheddable NORMAL lane."""

    def __init__(self, github: GitHubIntegration) -> None:
        self._github = github

    def get(self, path: str, *, endpoint: str, etag: str | None = None) -> requests.Response | None:
        try:
            return self._github.api_request(
                "GET",
                path,
                endpoint=endpoint,
                headers=_conditional_headers(etag),
                timeout=GITHUB_API_TIMEOUT_SECONDS,
            )
        except (GitHubIntegrationError, GitHubEgressBudgetExhausted, GitHubRateLimitError, requests.RequestException):
            logger.warning("source_links_github_request_failed", endpoint=endpoint, exc_info=True)
            return None


class PublicTokenGitHubApi:
    """Reads public repositories with PostHog's shared token, feeding the circuit breaker."""

    def __init__(self, token: str, circuit: PublicGitHubTokenCircuit) -> None:
        self._token = token
        self._circuit = circuit

    def get(self, path: str, *, endpoint: str, etag: str | None = None) -> requests.Response | None:
        try:
            response = github_request(
                "GET",
                f"https://api.github.com{path}",
                source="error_tracking",
                headers={**_conditional_headers(etag), "Authorization": f"token {self._token}"},
                endpoint=endpoint,
                timeout=GITHUB_API_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.warning("source_links_github_request_failed", endpoint=endpoint, exc_info=True)
            return None
        if response.status_code == 401:
            self._circuit.record_unauthorized()
            logger.error("github_public_token_unauthorized", status_code=401)
            return None
        self._circuit.record_success()
        return response


def github_api_for(team_id: int, repository: Repository) -> GitHubApi | None:
    """An installation with access to the repository first, then the public token for public repositories."""
    github = _github_integration_with_access(team_id, repository)
    if github is not None:
        return InstallationGitHubApi(github)
    circuit = PublicGitHubTokenCircuit()
    if settings.GITHUB_TOKEN and not circuit.is_open():
        return PublicTokenGitHubApi(settings.GITHUB_TOKEN, circuit)
    return None


def _github_integration_with_access(team_id: int, repository: Repository) -> GitHubIntegration | None:
    key = f"error_tracking:source_links:github_integration:{team_id}:{repository.path}"
    cached = cache.get(key)
    if cached == "":
        return None
    if cached is not None:
        integration = Integration.objects.filter(team_id=team_id, kind="github", id=cached).first()
        if integration is not None:
            return GitHubIntegration(integration, source="error_tracking", priority=Priority.NORMAL)
    try:
        github = GitHubIntegration.first_for_team_repository(
            team_id, repository.path, source="error_tracking", priority=Priority.NORMAL
        )
    except (GitHubEgressBudgetExhausted, GitHubRateLimitError, requests.RequestException):
        logger.warning("source_links_github_access_check_failed", repository=repository.path, exc_info=True)
        return None
    cache.set(key, github.integration.id if github else "", BRANCH_TTL_SECONDS)
    return github


@frozen
class SourceTarget:
    """Where a symbol set's files live: a repository at a commit, or at its default branch when
    the release did not record a commit."""

    repository: Repository
    ref: str
    pinned: bool


def github_target(api: GitHubApi, repository: Repository, commit: str | None) -> SourceTarget | None:
    if commit and _COMMIT_SHA_RE.fullmatch(commit):
        return SourceTarget(repository=repository, ref=commit, pinned=True)
    branch = _github_default_branch(api, repository)
    if branch is None:
        return None
    return SourceTarget(repository=repository, ref=branch, pinned=False)


def _github_default_branch(api: GitHubApi, repository: Repository) -> str | None:
    key = f"error_tracking:source_links:default_branch:{repository.path}"
    cached = cache.get(key)
    if isinstance(cached, str):
        return cached or None
    response = api.get(f"/repos/{repository.path}", endpoint="/repos/{owner}/{repo}")
    branch: str | None = None
    if response is not None and response.status_code == 200:
        try:
            value = response.json().get("default_branch")
        except ValueError:
            value = None
        if isinstance(value, str) and _BRANCH_RE.fullmatch(value) and ".." not in value:
            branch = value
    cache.set(key, branch or "", DEFAULT_BRANCH_TTL_SECONDS if branch else NEGATIVE_TTL_SECONDS)
    return branch


_TREE_ENDPOINT = "/repos/{owner}/{repo}/git/trees/{sha}"
_TREE_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")


@frozen
class TreeListing:
    """Every blob path under a ref. ``not_modified`` means GitHub confirmed the caller's ETag, and
    ``paths`` is then empty because the caller already holds them."""

    paths: tuple[str, ...]
    etag: str | None
    not_modified: bool = False


class _TreeRequests:
    """Issues the tree requests of one listing and counts them against the cap."""

    def __init__(self, api: GitHubApi, repository: Repository) -> None:
        self._api = api
        self._repository = repository
        self.remaining = MAX_TREE_REQUESTS

    def get(self, tree_ref: str, *, recursive: bool, etag: str | None = None) -> requests.Response | None:
        self.remaining -= 1
        ref = urllib.parse.quote(tree_ref, safe="")
        suffix = "?recursive=1" if recursive else ""
        return self._api.get(
            f"/repos/{self._repository.path}/git/trees/{ref}{suffix}", endpoint=_TREE_ENDPOINT, etag=etag
        )

    def body(self, response: requests.Response | None) -> dict | None:
        if response is None:
            return None
        if response.status_code != 200:
            logger.info(
                "source_links_tree_unavailable", repository=self._repository.path, status_code=response.status_code
            )
            return None
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("tree"), list):
            logger.warning("source_links_tree_unreadable", repository=self._repository.path)
            return None
        return body

    def log_incomplete(self, tree_ref: str) -> None:
        logger.warning("source_links_tree_incomplete", repository=self._repository.path, tree=tree_ref)


def list_github_tree(
    api: GitHubApi, repository: Repository, ref: str, *, etag: str | None = None
) -> TreeListing | None:
    """Lists every file under a ref with as few requests as GitHub allows.

    One recursive request covers most repositories. GitHub cuts a large response short, and
    ``_collect_tree`` then reads the rest. Returns None when any request fails, so a partial
    listing is never stored as the repository.
    """
    tree_requests = _TreeRequests(api, repository)
    response = tree_requests.get(ref, recursive=True, etag=etag)
    if etag and response is not None and response.status_code == 304:
        return TreeListing(paths=(), etag=etag, not_modified=True)
    body = tree_requests.body(response)
    if body is None or response is None:
        return None
    paths: set[str] = set()
    if not _collect_tree(tree_requests, ref, body, prefix="", paths=paths, depth=0):
        return None
    return TreeListing(paths=tuple(sorted(paths)), etag=response.headers.get("ETag"))


def _collect_tree(
    tree_requests: _TreeRequests, tree_ref: str, body: dict, *, prefix: str, paths: set[str], depth: int
) -> bool:
    """Adds the files of one recursive response to ``paths`` and reads what GitHub left out.

    GitHub returns entries in path order and then stops, so every top-level directory before the
    one that holds the last entry is complete. Only that directory and its later siblings are read
    again, each with its own recursive request and its own limit. Returns False on a failed request.
    """
    entries = [entry for entry in body["tree"] if isinstance(entry, dict) and isinstance(entry.get("path"), str)]
    paths.update(prefix + entry["path"] for entry in entries if entry.get("type") == "blob")
    if not body.get("truncated") or not entries:
        return True
    if depth >= MAX_TREE_SPLIT_DEPTH or tree_requests.remaining <= 0:
        tree_requests.log_incomplete(tree_ref)
        return True

    cut = entries[-1]["path"].split("/", 1)[0]
    listing = tree_requests.body(tree_requests.get(tree_ref, recursive=False))
    if listing is None:
        return False
    children = [child for child in listing["tree"] if isinstance(child, dict) and isinstance(child.get("path"), str)]
    paths.update(prefix + child["path"] for child in children if child.get("type") == "blob")

    # The listing arrives in the same order as the recursive response, so its position gives the
    # later siblings without a reimplementation of git's tree ordering.
    names = [child["path"] for child in children]
    for child in children[names.index(cut) if cut in names else 0 :]:
        sha = child.get("sha")
        if child.get("type") != "tree" or not isinstance(sha, str) or not _TREE_SHA_RE.fullmatch(sha):
            continue
        if tree_requests.remaining <= 0:
            tree_requests.log_incomplete(tree_ref)
            return True
        subtree = tree_requests.body(tree_requests.get(sha, recursive=True))
        if subtree is None:
            return False
        if not _collect_tree(
            tree_requests, sha, subtree, prefix=f"{prefix}{child['path']}/", paths=paths, depth=depth + 1
        ):
            return False
    return True


def _tree_from_cache(entry: dict) -> RepositoryTree:
    text = zlib.decompress(entry["paths"]).decode("utf-8")
    return RepositoryTree(path for path in text.split("\n") if path)


def github_tree(api: GitHubApi, target: SourceTarget) -> RepositoryTree | None:
    key = f"error_tracking:source_links:tree:{target.repository.path}@{target.ref}"
    cached = cache.get(key)
    now = time.time()
    stale: dict | None = None
    if isinstance(cached, dict):
        if cached.get("paths") is None:
            return None
        if target.pinned or now - cached.get("checked_at", 0) < BRANCH_TTL_SECONDS:
            return _tree_from_cache(cached)
        stale = cached

    listing = list_github_tree(api, target.repository, target.ref, etag=stale.get("etag") if stale else None)
    if listing is None:
        if stale is None:
            cache.set(key, {"paths": None}, NEGATIVE_TTL_SECONDS)
            return None
        # The branch tree could not be refreshed. The stale tree is still a good guide, and the
        # next attempt waits for the negative lifetime instead of running on every page load.
        stale["checked_at"] = now - BRANCH_TTL_SECONDS + NEGATIVE_TTL_SECONDS
        cache.set(key, stale, PINNED_TTL_SECONDS)
        return _tree_from_cache(stale)
    if listing.not_modified and stale is not None:
        stale["checked_at"] = now
        cache.set(key, stale, PINNED_TTL_SECONDS)
        return _tree_from_cache(stale)

    entry = {
        "paths": zlib.compress("\n".join(listing.paths).encode("utf-8")),
        "etag": listing.etag,
        "checked_at": now,
    }
    cache.set(key, entry, PINNED_TTL_SECONDS)
    return RepositoryTree(listing.paths)


def github_paths_for_symbol_set(
    api: GitHubApi, symbol_set: ErrorTrackingSymbolSet, target: SourceTarget, frame_sources: Iterable[str]
) -> Mapping[str, str | None]:
    """Raw source to repository path for every source of the symbol set, None where nothing matched.

    Kept per symbol set content and target, so a page load after the first costs no GitHub or
    object storage request. The frames' own sources are part of the set, which keeps matching
    alive when the stored map cannot be read.
    """
    frame_sources = list(dict.fromkeys(frame_sources))
    key = (
        "error_tracking:source_links:paths:"
        f"{symbol_set.id}:{symbol_set.content_hash}:{target.repository.path}@{target.ref}"
    )
    cached = cache.get(key)
    if isinstance(cached, dict) and all(source in cached for source in frame_sources):
        return cached

    tree = github_tree(api, target)
    if tree is None:
        return {}
    stored_sources = symbol_set_sources(symbol_set)
    sources = list(dict.fromkeys([*(stored_sources or []), *frame_sources]))
    matched = match_sources(tree, sources)
    mapping: dict[str, str | None] = {source: matched.get(source) for source in sources}
    if stored_sources is None:
        ttl = NEGATIVE_TTL_SECONDS
    else:
        ttl = PINNED_TTL_SECONDS if target.pinned else BRANCH_TTL_SECONDS
    cache.set(key, mapping, ttl)
    return mapping


# GitLab keeps the search-based resolution: its tree endpoint pages a hundred entries at a time,
# which does not scale to a whole repository on page load.


def prepare_gitlab_search_query(query: str | None) -> str:
    if not query:
        return ""
    cleaned = ["" if char in ".,:;/\\=*!?#$&+^|~<>(){}[]\"'`" else char for char in query]
    return " ".join("".join(cleaned).split())


@frozen
class GitLabHit:
    """A blob the GitLab search API found: its path in the repository and the ref it was found at."""

    host_url: str
    ref: str
    path: str


def gitlab_search(
    code_sample: str, token: str, repository: Repository, file_name: str, gitlab_url: str
) -> GitLabHit | None:
    """The first search hit whose path holds the file name."""
    project = urllib.parse.quote(repository.path, safe="")
    headers = {"PRIVATE-TOKEN": token, "Content-Type": "application/json"}

    # Search behavior varies with repository visibility and plan, so both the raw line and the
    # sanitized query are tried.
    for query in dict.fromkeys([code_sample.strip(), prepare_gitlab_search_query(code_sample)]):
        if not query:
            continue
        search = urllib.parse.quote(query)
        url = f"{gitlab_url}/api/v4/projects/{project}/search?scope=blobs&search={search}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                continue
            for item in response.json() or []:
                item_path = item.get("path", "")
                ref = item.get("ref", "")
                if file_name in item_path and ref and item_path:
                    return GitLabHit(host_url=gitlab_url, ref=ref, path=item_path)
        except Exception as error:
            logger.exception("gitlab_code_search_request_failed", error=str(error))
    return None


def _gitlab_hit_for_frame(team_id: int, repository: Repository, frame: ErrorTrackingStackFrame) -> GitLabHit | None:
    context = frame.context or {}
    code_sample = (context.get("line") or {}).get("line") if isinstance(context, dict) else None
    source = frame.contents.get("source") or ""
    file_name = source.rsplit("/", 1)[-1]
    if not code_sample or not file_name:
        return None

    key = (
        f"error_tracking:source_links:gitlab:{team_id}:{repository.path}:{file_name}:{zlib.crc32(code_sample.encode())}"
    )
    cached = cache.get(key)
    if cached == "":
        return None
    if isinstance(cached, GitLabHit):
        return cached

    hit: GitLabHit | None = None
    if settings.GITLAB_TOKEN:
        hit = gitlab_search(code_sample, settings.GITLAB_TOKEN, repository, file_name, "https://gitlab.com")
    if hit is None:
        for integration in Integration.objects.filter(team_id=team_id, kind="gitlab"):
            try:
                gitlab = GitLabIntegration(integration)
                token = gitlab.integration.sensitive_config.get("access_token")
                if token:
                    hit = gitlab_search(code_sample, token, repository, file_name, gitlab.hostname)
            except Exception:
                logger.warning("source_links_gitlab_integration_failed", integration_id=integration.id, exc_info=True)
            if hit is not None:
                break
    cache.set(key, hit if hit is not None else "", BRANCH_TTL_SECONDS if hit else NEGATIVE_TTL_SECONDS)
    return hit


@frozen
class SourceLink:
    raw_id: str
    provider: GitProvider
    url: str
    path: str


def _release_git(metadata: object) -> dict:
    git = metadata.get("git") if isinstance(metadata, dict) else None
    return git if isinstance(git, dict) else {}


def _frame_raw_id(frame: ErrorTrackingStackFrame) -> str:
    return f"{frame.raw_id}/{frame.part}"


def frame_line_number(frame: ErrorTrackingStackFrame) -> int | None:
    """The one-based line a link anchors at.

    The context carries the line as the UI shows it. A frame resolved through a source map stores
    the token's line in ``contents``, which counts from zero, so a frame without context adds one.
    """
    context = frame.context if isinstance(frame.context, dict) else {}
    context_line = context.get("line")
    number = context_line.get("number") if isinstance(context_line, dict) else None
    if isinstance(number, int) and number > 0:
        return number
    line = frame.contents.get("line")
    if not isinstance(line, int) or line < 0:
        return None
    return (line + 1 if frame.contents.get("lang") == "javascript" else line) or None


def _blob_url(target: SourceTarget, path: str, line: int | None) -> str:
    url = f"{target.repository.url}/blob/{urllib.parse.quote(target.ref, safe='')}/{urllib.parse.quote(path)}"
    return f"{url}#L{line}" if line else url


def resolve_source_links(team_id: int, release_id: str, raw_ids: list[str]) -> list[SourceLink]:
    """One link per frame that maps to a file in the release's repository.

    The release is the exception event's own, the one cymbal records as ``$exception_release``.
    A symbol set's release is not consulted: in event release mode it has none, and the event's
    release is the one that was deployed. An event without a release gets no links.
    """
    release = ErrorTrackingRelease.objects.filter(team_id=team_id, id=release_id).first()
    git = _release_git(release.metadata) if release else {}
    repository = parse_repository(git.get("remote_url"))
    if repository is None:
        return []

    frames = [
        frame
        for frame in batch_get_stack_frames(team_id, raw_ids[:MAX_RAW_IDS_PER_REQUEST])
        if frame.symbol_set is not None and isinstance(frame.contents, dict) and frame.contents.get("source")
    ]
    if not frames:
        return []
    if repository.provider == "gitlab":
        return _gitlab_links(team_id, repository, frames)

    api = github_api_for(team_id, repository)
    if api is None:
        return []
    target = github_target(api, repository, git.get("commit_id"))
    if target is None:
        return []

    by_symbol_set: dict[object, list[ErrorTrackingStackFrame]] = defaultdict(list)
    for frame in frames:
        by_symbol_set[frame.symbol_set_id].append(frame)

    links: list[SourceLink] = []
    for symbol_set_frames in by_symbol_set.values():
        symbol_set = symbol_set_frames[0].symbol_set
        if symbol_set is None:
            continue
        mapping = github_paths_for_symbol_set(
            api, symbol_set, target, [frame.contents["source"] for frame in symbol_set_frames]
        )
        for frame in symbol_set_frames:
            path = mapping.get(frame.contents["source"])
            if not path:
                continue
            links.append(
                SourceLink(
                    raw_id=_frame_raw_id(frame),
                    provider="github",
                    url=_blob_url(target, path, frame_line_number(frame)),
                    path=path,
                )
            )
    return links


def _gitlab_links(team_id: int, repository: Repository, frames: list[ErrorTrackingStackFrame]) -> list[SourceLink]:
    links: list[SourceLink] = []
    with ThreadPoolExecutor(max_workers=min(len(frames), 5)) as executor:
        hits = executor.map(lambda frame: _gitlab_hit_for_frame(team_id, repository, frame), frames)
        for frame, hit in zip(frames, hits):
            if hit is None:
                continue
            url = f"{hit.host_url}/{repository.path}/-/blob/{hit.ref}/{hit.path}"
            line = frame_line_number(frame)
            if line:
                url = f"{url}#L{line}"
            links.append(SourceLink(raw_id=_frame_raw_id(frame), provider="gitlab", url=url, path=hit.path))
    return links
