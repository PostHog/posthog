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
import base64
import struct
import functools
import urllib.parse
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import field
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
from posthog.security.url_validation import is_url_allowed
from posthog.storage import object_storage

from products.error_tracking.backend.models import ErrorTrackingRelease, ErrorTrackingStackFrame, ErrorTrackingSymbolSet

from . import batch_get_stack_frames
from .source_link_metrics import (
    SOURCE_LINK_CACHE,
    SOURCE_LINK_FRAMES,
    SOURCE_LINK_GITLAB_REQUESTS,
    SOURCE_LINK_PUBLIC_TOKEN,
    SOURCE_LINK_REQUESTS,
    SOURCE_LINK_RESOLVE_SECONDS,
    SOURCE_LINK_SYMBOL_SET_READS,
    SOURCE_LINK_TREE_LISTING_REQUESTS,
    SOURCE_LINK_TREE_LISTINGS,
)

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

# Choosing an anchor places every source under every candidate directory, so its cost is the
# product of two numbers the map controls. A map that stays under the caps above can still make
# that product large enough to hold a web worker for minutes, so the placements of one match are
# capped as well. A real bundle stays far below the cap, because it names each source once and
# its relative paths exist in few directories.
MAX_ANCHOR_PLACEMENTS = 5_000_000

# A tree at a commit never changes, so it is kept for a week. Data read at a branch is trusted for
# an hour. After that a branch tree is revalidated with its ETag, which costs no rate limit budget
# when the branch did not move. A negative result is kept briefly so repeated page loads of an
# unreachable repository do not each cost a GitHub request.
PINNED_TTL_SECONDS = 7 * 24 * 60 * 60
BRANCH_TTL_SECONDS = 60 * 60
DEFAULT_BRANCH_TTL_SECONDS = 24 * 60 * 60
NEGATIVE_TTL_SECONDS = 5 * 60

GITHUB_API_TIMEOUT_SECONDS = 20

# A listing of one tree is capped in requests, in depth and in wall-clock time, since it runs
# inside a page load. One process at a time lists a given tree, and the lock outlives the deadline.
MAX_TREE_REQUESTS = 100
MAX_TREE_SPLIT_DEPTH = 4
TREE_LISTING_DEADLINE_SECONDS = 30
TREE_LOCK_SECONDS = TREE_LISTING_DEADLINE_SECONDS + GITHUB_API_TIMEOUT_SECONDS

# Reading the stored maps of one request is capped in wall-clock time as well. A build that writes
# one map per file gives the event a symbol set per frame, and each set that is not mapped yet
# costs an object storage round trip. The frames of a set the deadline stops get no link on this
# load, and nothing is stored for that set, so the next load reads it.
SYMBOL_SET_BATCH_DEADLINE_SECONDS = 15

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

    Raw sources that reduce to the same path are scored together, and scoring stops after
    ``MAX_ANCHOR_PLACEMENTS`` placements, so a map with many sources cannot hold the worker.
    """
    by_path: dict[SourcePath, list[str]] = defaultdict(list)
    for raw in dict.fromkeys(sources):
        if (source := parse_source(raw)) is not None:
            by_path[source].append(raw)
    if not by_path or not tree.paths:
        return {}

    hop_counts: dict[int, int] = defaultdict(int)
    for source, raws in by_path.items():
        hop_counts[source.hops] += len(raws)
    anchor_hops = min(hop_counts, key=lambda hops: (-hop_counts[hops], hops))
    candidates: set[str] = set()
    for source in by_path:
        if source.hops != anchor_hops:
            continue
        for path in tree.paths_ending_with(source.relative):
            candidates.add(path[: -len(source.relative)].rstrip("/"))

    # Shallower anchors first, so a tie between identical package layouts resolves the same way every time.
    ordered = sorted(candidates, key=lambda candidate: (candidate.count("/") if candidate else -1, candidate))
    scored = max(1, MAX_ANCHOR_PLACEMENTS // len(by_path))
    if len(ordered) > scored:
        logger.warning("source_links_anchor_scoring_capped", candidates=len(ordered), sources=len(by_path))
    best_anchor: list[str] | None = None
    best_score = 0
    for anchor in ordered[:scored]:
        segments = anchor.split("/") if anchor else []
        score = sum(len(raws) for source, raws in by_path.items() if _place(segments, anchor_hops, source) in tree)
        if score > best_score:
            best_anchor, best_score = segments, score

    matched: dict[str, str] = {}
    for source, raws in by_path.items():
        placed = _place(best_anchor, anchor_hops, source) if best_anchor is not None else None
        if placed is None or placed not in tree:
            placed = _unique_suffix_match(tree, source)
        if placed is None:
            continue
        for raw in raws:
            matched[raw] = placed
    return matched


def _place(anchor_segments: list[str], anchor_hops: int, source: SourcePath) -> str | None:
    """The path of ``source`` when sources with ``anchor_hops`` hops start at the anchor directory.

    A source with fewer hops than the anchor group starts somewhere below the anchor, in a
    directory the map does not name, so it cannot be placed here.
    """
    extra_hops = source.hops - anchor_hops
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
        SOURCE_LINK_SYMBOL_SET_READS.labels("empty").inc()
        return []
    try:
        head = object_storage.head_object(symbol_set.storage_ptr)
        if head and head.get("ContentLength", 0) > MAX_SYMBOL_SET_BYTES:
            logger.info("source_links_symbol_set_too_large", symbol_set_id=str(symbol_set.id))
            SOURCE_LINK_SYMBOL_SET_READS.labels("too_large").inc()
            return []
        data = object_storage.read_bytes(symbol_set.storage_ptr)
    except Exception:
        logger.warning("source_links_symbol_set_unreadable", symbol_set_id=str(symbol_set.id), exc_info=True)
        SOURCE_LINK_SYMBOL_SET_READS.labels("unreadable").inc()
        return None
    if not data:
        SOURCE_LINK_SYMBOL_SET_READS.labels("empty").inc()
        return []
    try:
        sources = source_map_sources(read_source_map(data))
    except Exception:
        logger.info("source_links_symbol_set_rejected", symbol_set_id=str(symbol_set.id), exc_info=True)
        SOURCE_LINK_SYMBOL_SET_READS.labels("rejected").inc()
        return []
    SOURCE_LINK_SYMBOL_SET_READS.labels("read").inc()
    return sources


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
                SOURCE_LINK_PUBLIC_TOKEN.labels("circuit_opened").inc()
        except Exception:
            pass


class GitHubApi(Protocol):
    @property
    def identity(self) -> str:
        """Names the credential, so data read with it is only served to callers of the same credential."""
        ...

    def get(self, path: str, *, endpoint: str, etag: str | None = None) -> requests.Response | None:
        """A GET on the GitHub API, or None when no response arrived. ``etag`` makes it conditional."""
        ...


def _conditional_headers(etag: str | None) -> dict[str, str]:
    return {"If-None-Match": etag} if etag else {}


class InstallationGitHubApi:
    """Reads through the team's GitHub App installation, on the sheddable NORMAL lane."""

    def __init__(self, github: GitHubIntegration) -> None:
        self._github = github

    @property
    def identity(self) -> str:
        return f"installation:{self._github.integration.id}"

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

    @property
    def identity(self) -> str:
        return "public"

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
            SOURCE_LINK_PUBLIC_TOKEN.labels("unauthorized").inc()
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
        SOURCE_LINK_CACHE.labels("integration_access", "negative").inc()
        return None
    if cached is not None:
        integration = Integration.objects.filter(team_id=team_id, kind="github", id=cached).first()
        if integration is not None:
            SOURCE_LINK_CACHE.labels("integration_access", "hit").inc()
            return GitHubIntegration(integration, source="error_tracking", priority=Priority.NORMAL)
    SOURCE_LINK_CACHE.labels("integration_access", "miss").inc()
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
    key = f"error_tracking:source_links:default_branch:{api.identity}:{repository.path}"
    cached = cache.get(key)
    if isinstance(cached, str):
        SOURCE_LINK_CACHE.labels("default_branch", "hit" if cached else "negative").inc()
        return cached or None
    SOURCE_LINK_CACHE.labels("default_branch", "miss").inc()
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
    """Issues the tree requests of one listing and counts them against the cap and the deadline."""

    def __init__(self, api: GitHubApi, repository: Repository) -> None:
        self._api = api
        self._repository = repository
        self._deadline = time.time() + TREE_LISTING_DEADLINE_SECONDS
        self.remaining = MAX_TREE_REQUESTS
        self.incomplete = False

    def get(self, tree_ref: str, *, recursive: bool, etag: str | None = None) -> requests.Response | None:
        if time.time() > self._deadline:
            logger.warning("source_links_tree_listing_timed_out", repository=self._repository.path, tree=tree_ref)
            return None
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
        self.incomplete = True
        logger.warning("source_links_tree_incomplete", repository=self._repository.path, tree=tree_ref)

    def record(self, result: str) -> None:
        SOURCE_LINK_TREE_LISTINGS.labels(result).inc()
        SOURCE_LINK_TREE_LISTING_REQUESTS.observe(MAX_TREE_REQUESTS - self.remaining)


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
        tree_requests.record("not_modified")
        return TreeListing(paths=(), etag=etag, not_modified=True)
    body = tree_requests.body(response)
    if body is None or response is None:
        tree_requests.record("failed")
        return None
    paths: set[str] = set()
    if not _collect_tree(tree_requests, ref, body, prefix="", paths=paths, depth=0):
        tree_requests.record("failed")
        return None
    tree_requests.record("incomplete" if tree_requests.incomplete else "complete")
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
    text = zlib.decompress(base64.b64decode(entry["paths"])).decode("utf-8")
    return RepositoryTree(path for path in text.split("\n") if path)


def github_tree(api: GitHubApi, target: SourceTarget) -> RepositoryTree | None:
    key = f"error_tracking:source_links:tree:{api.identity}:{target.repository.path}@{target.ref}"
    cached = cache.get(key)
    now = time.time()
    stale: dict | None = None
    if isinstance(cached, dict):
        if cached.get("paths") is None:
            SOURCE_LINK_CACHE.labels("tree", "negative").inc()
            return None
        if target.pinned or now - cached.get("checked_at", 0) < BRANCH_TTL_SECONDS:
            SOURCE_LINK_CACHE.labels("tree", "hit").inc()
            return _tree_from_cache(cached)
        stale = cached
    SOURCE_LINK_CACHE.labels("tree", "revalidate" if stale else "miss").inc()

    # Concurrent page loads of one release would each list the tree. The one that takes the lock
    # lists it, and the others use what they have, which is nothing for a first load.
    lock_key = f"{key}:lock"
    if not cache.add(lock_key, True, TREE_LOCK_SECONDS):
        SOURCE_LINK_CACHE.labels("tree", "locked").inc()
        return _tree_from_cache(stale) if stale else None
    try:
        listing = list_github_tree(api, target.repository, target.ref, etag=stale.get("etag") if stale else None)
    finally:
        cache.delete(lock_key)
    if listing is None:
        if stale is None:
            # Added rather than set, so a failure that lands after another process filled the
            # tree does not replace it with a negative entry.
            cache.add(key, {"paths": None}, NEGATIVE_TTL_SECONDS)
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

    # The cache pickles what it is given, so the entry holds JSON shapes only. The paths are
    # compressed because a large repository lists tens of thousands of them, and base64 is what
    # carries those bytes as text.
    entry = {
        "paths": base64.b64encode(zlib.compress("\n".join(listing.paths).encode("utf-8"))).decode("ascii"),
        "etag": listing.etag,
        "checked_at": now,
    }
    cache.set(key, entry, PINNED_TTL_SECONDS)
    return RepositoryTree(listing.paths)


def github_paths_for_symbol_set(
    symbol_set: ErrorTrackingSymbolSet,
    target: SourceTarget,
    frame_sources: Iterable[str],
    load_tree: Callable[[], RepositoryTree | None],
) -> Mapping[str, str | None]:
    """Raw source to repository path for every source of the symbol set, None where nothing matched.

    Kept per symbol set content and target, so a page load after the first costs no GitHub or
    object storage request. The frames' own sources are part of the set, which keeps matching
    alive when the stored map cannot be read. ``load_tree`` is only called on a miss.
    """
    frame_sources = list(dict.fromkeys(frame_sources))
    key = (
        "error_tracking:source_links:paths:"
        f"{symbol_set.id}:{symbol_set.content_hash}:{target.repository.path}@{target.ref}"
    )
    cached = cache.get(key)
    if isinstance(cached, dict) and all(source in cached for source in frame_sources):
        SOURCE_LINK_CACHE.labels("mapping", "hit").inc()
        return cached
    SOURCE_LINK_CACHE.labels("mapping", "miss").inc()

    tree = load_tree()
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

GITLAB_SEARCH_TIMEOUT_SECONDS = 10
GITLAB_BATCH_DEADLINE_SECONDS = 15


def prepare_gitlab_search_query(query: str | None) -> str:
    if not query:
        return ""
    cleaned = ["" if char in ".,:;/\\=*!?#$&+^|~<>(){}[]\"'`" else char for char in query]
    return " ".join("".join(cleaned).split())


@frozen
class GitLabCredential:
    """A token and the GitLab host it is for, with no trailing slash on the host."""

    host_url: str
    token: str = field(repr=False)


@frozen
class GitLabHit:
    """A blob the GitLab search API found: its path in the repository and the ref it was found at."""

    host_url: str
    ref: str
    path: str


@frozen
class GitLabLookup:
    """What one search needs from a frame. Frames that share both fields share one search."""

    file_name: str
    code_sample: str


def _host_of(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower()


def gitlab_credentials(team_id: int, repository: Repository) -> list[GitLabCredential]:
    """The shared token first, then the team's integrations on the repository's host.

    An integration on another host never receives the search, since the code sample is source
    code and the host cannot hold the repository.
    """
    credentials: list[GitLabCredential] = []
    if settings.GITLAB_TOKEN and repository.host == "gitlab.com":
        credentials.append(GitLabCredential(host_url="https://gitlab.com", token=settings.GITLAB_TOKEN))
    for integration in Integration.objects.filter(team_id=team_id, kind="gitlab"):
        try:
            gitlab = GitLabIntegration(integration)
            hostname = gitlab.hostname.rstrip("/")
            token = gitlab.integration.sensitive_config.get("access_token")
        except Exception:
            logger.warning("source_links_gitlab_integration_failed", integration_id=integration.id, exc_info=True)
            continue
        if token and _host_of(hostname) == repository.host:
            credentials.append(GitLabCredential(host_url=hostname, token=token))
    return credentials


def gitlab_search(
    lookup: GitLabLookup, credential: GitLabCredential, repository: Repository, ref: str | None
) -> GitLabHit | None:
    """The first search hit whose file name is the frame's, at ``ref`` when the release recorded one."""
    project = urllib.parse.quote(repository.path, safe="")
    url = f"{credential.host_url}/api/v4/projects/{project}/search"
    allowed, error = is_url_allowed(url)
    if not allowed:
        logger.warning("source_links_gitlab_host_rejected", host=credential.host_url, error=error)
        return None
    headers = {"PRIVATE-TOKEN": credential.token, "Content-Type": "application/json"}

    # Search behavior varies with repository visibility and plan, so both the raw line and the
    # sanitized query are tried.
    for query in dict.fromkeys([lookup.code_sample.strip(), prepare_gitlab_search_query(lookup.code_sample)]):
        if not query:
            continue
        params = {"scope": "blobs", "search": query, **({"ref": ref} if ref else {})}
        try:
            response = requests.get(
                url, params=params, headers=headers, timeout=GITLAB_SEARCH_TIMEOUT_SECONDS, allow_redirects=False
            )
            SOURCE_LINK_GITLAB_REQUESTS.labels(str(response.status_code)).inc()
            if response.status_code != 200:
                continue
            for item in response.json() or []:
                item_path = item.get("path") if isinstance(item, dict) else None
                item_ref = item.get("ref") if isinstance(item, dict) else None
                if not isinstance(item_path, str) or item_path.rsplit("/", 1)[-1] != lookup.file_name:
                    continue
                hit_ref = ref or (item_ref if isinstance(item_ref, str) else "")
                if hit_ref:
                    return GitLabHit(host_url=credential.host_url, ref=hit_ref, path=item_path)
        except Exception as error:
            SOURCE_LINK_GITLAB_REQUESTS.labels("error").inc()
            logger.exception("gitlab_code_search_request_failed", error=str(error))
    return None


def _gitlab_lookup(frame: ErrorTrackingStackFrame) -> GitLabLookup | None:
    context = frame.context if isinstance(frame.context, dict) else {}
    code_sample = (context.get("line") or {}).get("line")
    file_name = (frame.contents.get("source") or "").rsplit("/", 1)[-1]
    if not isinstance(code_sample, str) or not code_sample.strip() or not file_name:
        return None
    return GitLabLookup(file_name=file_name, code_sample=code_sample)


@frozen
class GitLabLookupResult:
    """The hit for one lookup, or why there is none: a miss, or a deadline that cut the lookup off."""

    hit: GitLabHit | None
    cut_off: bool = False


def _gitlab_hit_from_cache(entry: dict) -> GitLabHit | None:
    """The hit a cache entry holds, or None when it holds no usable one.

    The cache pickles what it is given, so a hit is stored as its three fields and read back
    through this check. A class in the entry would be rebuilt on read, and a rename of it would
    fail every read of an entry the deployment before wrote.
    """
    host_url, ref, path = entry.get("host_url"), entry.get("ref"), entry.get("path")
    if not (isinstance(host_url, str) and isinstance(ref, str) and isinstance(path, str)):
        return None
    return GitLabHit(host_url=host_url, ref=ref, path=path)


def _gitlab_hit(
    team_id: int,
    repository: Repository,
    ref: str | None,
    credentials: list[GitLabCredential],
    lookup: GitLabLookup,
    deadline: float,
) -> GitLabLookupResult:
    key = (
        f"error_tracking:source_links:gitlab:{team_id}:{repository.path}@{ref or ''}:"
        f"{lookup.file_name}:{zlib.crc32(lookup.code_sample.encode())}"
    )
    cached = cache.get(key)
    if cached == "":
        SOURCE_LINK_CACHE.labels("gitlab_search", "negative").inc()
        return GitLabLookupResult(hit=None)
    cached_hit = _gitlab_hit_from_cache(cached) if isinstance(cached, dict) else None
    if cached_hit is not None:
        SOURCE_LINK_CACHE.labels("gitlab_search", "hit").inc()
        return GitLabLookupResult(hit=cached_hit)
    SOURCE_LINK_CACHE.labels("gitlab_search", "miss").inc()

    hit: GitLabHit | None = None
    for credential in credentials:
        # Past the deadline the answer is unknown rather than negative, so nothing is cached.
        if time.time() > deadline:
            return GitLabLookupResult(hit=None, cut_off=True)
        hit = gitlab_search(lookup, credential, repository, ref)
        if hit is not None:
            break
    cache.set(
        key,
        {"host_url": hit.host_url, "ref": hit.ref, "path": hit.path} if hit else "",
        BRANCH_TTL_SECONDS if hit else NEGATIVE_TTL_SECONDS,
    )
    return GitLabLookupResult(hit=hit)


@frozen
class SourceLink:
    raw_id: str
    provider: GitProvider
    url: str
    path: str


@frozen
class ReleaseGit:
    """What a release recorded about its checkout. Metadata is free-form JSON, so either may be absent."""

    remote_url: str | None
    commit_id: str | None


def _release_git(metadata: object) -> ReleaseGit:
    git = metadata.get("git") if isinstance(metadata, dict) else None
    git = git if isinstance(git, dict) else {}
    remote_url = git.get("remote_url")
    commit_id = git.get("commit_id")
    return ReleaseGit(
        remote_url=remote_url if isinstance(remote_url, str) else None,
        commit_id=commit_id if isinstance(commit_id, str) else None,
    )


def _frame_raw_id(frame: ErrorTrackingStackFrame) -> str:
    return f"{frame.raw_id}/{frame.part}"


def frame_line_number(frame: ErrorTrackingStackFrame) -> int | None:
    """The one-based line a link anchors at.

    The context carries the line as the UI shows it. A frame resolved through a source map stores
    the token's line in ``contents``, which counts from zero, so a frame without context adds one.
    An unresolved frame keeps the one-based line the SDK sent.
    """
    context = frame.context if isinstance(frame.context, dict) else {}
    context_line = context.get("line")
    number = context_line.get("number") if isinstance(context_line, dict) else None
    if isinstance(number, int) and number > 0:
        return number
    line = frame.contents.get("line")
    if not isinstance(line, int) or line < 0:
        return None
    return (line + 1 if frame.contents.get("lang") == "javascript" and frame.resolved else line) or None


def _blob_url(target: SourceTarget, path: str, line: int | None) -> str:
    url = f"{target.repository.url}/blob/{urllib.parse.quote(target.ref, safe='')}/{urllib.parse.quote(path)}"
    return f"{url}#L{line}" if line else url


@frozen
class Resolution:
    """What a resolve request produced, and why it stopped where it did, for the request metric."""

    provider: str
    outcome: str
    links: list[SourceLink]


def resolve_source_links(team_id: int, release_id: str, raw_ids: list[str]) -> list[SourceLink]:
    """One link per frame that maps to a file in the release's repository.

    The release is the exception event's own, the one cymbal records as ``$exception_release``.
    A symbol set's release is not consulted: in event release mode it has none, and the event's
    release is the one that was deployed. An event without a release gets no links.
    """
    started = time.monotonic()
    resolution = _resolve(team_id, release_id, raw_ids)
    SOURCE_LINK_RESOLVE_SECONDS.labels(resolution.provider).observe(time.monotonic() - started)
    SOURCE_LINK_REQUESTS.labels(resolution.provider, resolution.outcome).inc()
    return resolution.links


def _resolve(team_id: int, release_id: str, raw_ids: list[str]) -> Resolution:
    release = ErrorTrackingRelease.objects.filter(team_id=team_id, id=release_id).first()
    if release is None:
        return Resolution(provider="none", outcome="no_release", links=[])
    git = _release_git(release.metadata)
    repository = parse_repository(git.remote_url)
    if repository is None:
        return Resolution(provider="none", outcome="no_repository", links=[])
    provider = repository.provider

    frames = [
        frame
        for frame in batch_get_stack_frames(team_id, raw_ids[:MAX_RAW_IDS_PER_REQUEST])
        if frame.symbol_set is not None and isinstance(frame.contents, dict) and frame.contents.get("source")
    ]
    if not frames:
        return Resolution(provider=provider, outcome="no_frames", links=[])
    if provider == "gitlab":
        gitlab_links = _gitlab_links(team_id, repository, git.commit_id, frames)
        return Resolution(provider=provider, outcome="linked" if gitlab_links else "no_links", links=gitlab_links)

    api = github_api_for(team_id, repository)
    if api is None:
        return Resolution(provider=provider, outcome="no_credential", links=[])
    target = github_target(api, repository, git.commit_id)
    if target is None:
        return Resolution(provider=provider, outcome="no_target", links=[])

    by_symbol_set: dict[object, list[ErrorTrackingStackFrame]] = defaultdict(list)
    for frame in frames:
        by_symbol_set[frame.symbol_set_id].append(frame)

    # Every symbol set of the event lives at the same target, so the tree is built at most once.
    load_tree = functools.cache(lambda: github_tree(api, target))
    deadline = time.time() + SYMBOL_SET_BATCH_DEADLINE_SECONDS
    links: list[SourceLink] = []
    for symbol_set_frames in by_symbol_set.values():
        symbol_set = symbol_set_frames[0].symbol_set
        if symbol_set is None:
            continue
        if time.time() > deadline:
            SOURCE_LINK_FRAMES.labels("github", "cut_off").inc(len(symbol_set_frames))
            continue
        mapping = github_paths_for_symbol_set(
            symbol_set, target, [frame.contents["source"] for frame in symbol_set_frames], load_tree
        )
        for frame in symbol_set_frames:
            path = mapping.get(frame.contents["source"])
            SOURCE_LINK_FRAMES.labels("github", "linked" if path else "unlinked").inc()
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
    return Resolution(provider="github", outcome="linked" if links else "no_links", links=links)


def _gitlab_links(
    team_id: int, repository: Repository, commit: str | None, frames: list[ErrorTrackingStackFrame]
) -> list[SourceLink]:
    """Searches GitLab once per distinct file name and code line, within one deadline for the batch.

    Vendor frames are skipped: each search is a live request, and their files are not in the
    repository. Lookups that the deadline cuts off get no link on this load.
    """
    ref = commit if commit and _COMMIT_SHA_RE.fullmatch(commit) else None
    lookups: dict[GitLabLookup, list[ErrorTrackingStackFrame]] = defaultdict(list)
    for frame in frames:
        if frame.contents.get("in_app") is False:
            SOURCE_LINK_FRAMES.labels("gitlab", "skipped_vendor").inc()
            continue
        lookup = _gitlab_lookup(frame)
        if lookup is None:
            SOURCE_LINK_FRAMES.labels("gitlab", "unlinked").inc()
        else:
            lookups[lookup].append(frame)
    if not lookups:
        return []
    credentials = gitlab_credentials(team_id, repository)
    deadline = time.time() + GITLAB_BATCH_DEADLINE_SECONDS

    links: list[SourceLink] = []
    with ThreadPoolExecutor(max_workers=min(len(lookups), 5)) as executor:
        results = executor.map(
            lambda lookup: _gitlab_hit(team_id, repository, ref, credentials, lookup, deadline), lookups
        )
        for lookup_frames, result in zip(lookups.values(), results):
            hit = result.hit
            if hit is None:
                SOURCE_LINK_FRAMES.labels("gitlab", "cut_off" if result.cut_off else "unlinked").inc(len(lookup_frames))
                continue
            SOURCE_LINK_FRAMES.labels("gitlab", "linked").inc(len(lookup_frames))
            url = f"{hit.host_url}/{repository.path}/-/blob/{urllib.parse.quote(hit.ref, safe='')}/{urllib.parse.quote(hit.path)}"
            for frame in lookup_frames:
                line = frame_line_number(frame)
                links.append(
                    SourceLink(
                        raw_id=_frame_raw_id(frame),
                        provider="gitlab",
                        url=f"{url}#L{line}" if line else url,
                        path=hit.path,
                    )
                )
    return links
