"""Read the file of a stack frame at its release commit, for the source view on the issue page.

The client names only an event and a frame. The file path and the line come from that stored frame,
and the repository and the commit come from the event's release, so a request cannot choose which
repository, commit or file to read.
"""

import json
import uuid
import hashlib
from datetime import datetime
from typing import Any, Literal

from django.core.cache import cache

import zstd

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.models import Team
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration

from products.error_tracking.backend.logic.repo_paths.metrics import record_source_file_read
from products.error_tracking.backend.logic.repo_paths.release_repo import ReleaseRepo, parse_release_repo
from products.error_tracking.backend.models import ErrorTrackingRelease

SourceFileUnavailable = Literal[
    "event_not_found",
    "frame_not_found",
    "no_repo_path",
    "no_release",
    "unsupported_host",
    "no_integration",
    "file_not_found",
    "too_large",
    "rate_limited",
    "fetch_failed",
]

# The contents API returns a file inline up to 1 MB. A larger file is not source a person scrolls.
MAX_SOURCE_FILE_BYTES = 1024 * 1024
# A file at a commit never changes, so the TTL only bounds how long the cache holds it.
_CACHE_TTL_SECONDS = 24 * 3600
_GITHUB_HOST = "github.com"
_SOURCE = "error_tracking_source_file"


@frozen
class FrameSourceFile:
    repo_path: str
    commit: str
    line: int | None
    lines: tuple[str, ...]


@frozen
class _Unavailable:
    reason: SourceFileUnavailable


@frozen
class _EventFrame:
    repo_path: str | None
    line: int | None
    release_id: str | None


def get_frame_source_file(
    team: Team, *, event_uuid: str, event_timestamp: datetime, frame_raw_id: str
) -> FrameSourceFile | SourceFileUnavailable:
    result = _get_frame_source_file(team, event_uuid, event_timestamp, frame_raw_id)
    record_source_file_read("read" if isinstance(result, FrameSourceFile) else result)
    return result


def _get_frame_source_file(
    team: Team, event_uuid: str, event_timestamp: datetime, frame_raw_id: str
) -> FrameSourceFile | SourceFileUnavailable:
    frame = _read_event_frame(team, event_uuid, event_timestamp, frame_raw_id)
    if not isinstance(frame, _EventFrame):
        return frame
    if not frame.repo_path:
        return "no_repo_path"

    release_id = _as_uuid(frame.release_id)
    release = (
        ErrorTrackingRelease.objects.filter(team_id=team.id, id=release_id).first() if release_id is not None else None
    )
    repo = parse_release_repo(release.metadata) if release is not None else None
    if not isinstance(repo, ReleaseRepo):
        return "no_release"
    if repo.slug.host != _GITHUB_HOST:
        return "unsupported_host"

    text = _read_file(team.id, repo, frame.repo_path)
    if isinstance(text, _Unavailable):
        return text.reason
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return FrameSourceFile(
        repo_path=frame.repo_path,
        commit=repo.commit,
        line=frame.line,
        lines=tuple(line.removesuffix("\r") for line in lines),
    )


def _read_event_frame(
    team: Team, event_uuid: str, event_timestamp: datetime, frame_raw_id: str
) -> _EventFrame | SourceFileUnavailable:
    query = parse_select(
        """
        SELECT properties.$exception_list, properties.$exception_release
        FROM events
        WHERE event = '$exception'
          AND uuid = {event_uuid}
          AND timestamp >= {event_timestamp} - INTERVAL 1 MINUTE
          AND timestamp <= {event_timestamp} + INTERVAL 1 MINUTE
        LIMIT 1
        """,
        placeholders={
            "event_uuid": ast.Constant(value=event_uuid),
            "event_timestamp": ast.Constant(value=event_timestamp),
        },
    )
    with tags_context(product=Product.ERROR_TRACKING, feature=Feature.QUERY):
        response = execute_hogql_query(query=query, team=team, query_type="ErrorTrackingFrameSourceFile")
    if not response.results:
        return "event_not_found"
    exception_list, release = (_json(value) for value in response.results[0])

    for exception in exception_list if isinstance(exception_list, list) else []:
        stacktrace = exception.get("stacktrace") if isinstance(exception, dict) else None
        frames = stacktrace.get("frames") if isinstance(stacktrace, dict) else None
        for frame in frames if isinstance(frames, list) else []:
            if isinstance(frame, dict) and frame.get("raw_id") == frame_raw_id:
                repo_path = frame.get("repo_path")
                line = frame.get("line")
                return _EventFrame(
                    repo_path=repo_path if isinstance(repo_path, str) else None,
                    line=line if isinstance(line, int) else None,
                    release_id=release.get("id") if isinstance(release, dict) else None,
                )
    return "frame_not_found"


def _read_file(team_id: int, repo: ReleaseRepo, repo_path: str) -> str | _Unavailable:
    key = _cache_key(team_id, repo, repo_path)
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if isinstance(cached, bytes):
        return zstd.decompress(cached).decode()

    text = _fetch_file(team_id, repo, repo_path)
    if isinstance(text, str):
        try:
            cache.set(key, zstd.compress(text.encode()), _CACHE_TTL_SECONDS)
        except Exception:
            pass
    return text


def _fetch_file(team_id: int, repo: ReleaseRepo, repo_path: str) -> str | _Unavailable:
    try:
        github = GitHubIntegration.first_for_team_repository(
            team_id, repo.slug.path, source=_SOURCE, priority=Priority.NORMAL
        )
        if github is None:
            return _Unavailable(reason="no_integration")
        entry = github.get_file_entry(repo.slug.path, repo_path, ref=repo.commit)
    except (EgressBudgetExhausted, GitHubRateLimitError):
        return _Unavailable(reason="rate_limited")
    except GitHubIntegrationError:
        return _Unavailable(reason="fetch_failed")
    if entry is None:
        return _Unavailable(reason="file_not_found")
    content = entry.get("content")
    if not isinstance(content, str) or entry.get("size", 0) > MAX_SOURCE_FILE_BYTES:
        return _Unavailable(reason="too_large")
    return content


def _cache_key(team_id: int, repo: ReleaseRepo, repo_path: str) -> str:
    digest = hashlib.sha256(f"{repo.slug}\0{repo.commit}\0{repo_path}".encode()).hexdigest()
    return f"error_tracking:source_file:v1:{team_id}:{digest}"


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _as_uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value or "")
    except ValueError:
        return None
