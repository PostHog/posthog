from __future__ import annotations

import re
import json
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import click
from hogli.manifest import REPO_ROOT

CACHE_WRITE_5M_WEIGHT: Final = 1.25
CACHE_WRITE_1H_WEIGHT: Final = 2.0
CACHE_READ_WEIGHT: Final = 0.1
OUTPUT_WEIGHT: Final = 5.0

WORKTREES_DIR_SUFFIX: Final = "--claude-worktrees-"


@dataclass(frozen=True, kw_only=True, slots=True)
class Request:
    message_id: str
    session_id: str
    branch: str
    timestamp: datetime
    input_tokens: int
    cache_write_5m_tokens: int
    cache_write_1h_tokens: int
    cache_read_tokens: int
    output_tokens: int

    @property
    def context_tokens(self) -> int:
        return self.input_tokens + self.cache_write_5m_tokens + self.cache_write_1h_tokens + self.cache_read_tokens

    @property
    def weighted_tokens(self) -> float:
        return (
            self.input_tokens
            + CACHE_WRITE_5M_WEIGHT * self.cache_write_5m_tokens
            + CACHE_WRITE_1H_WEIGHT * self.cache_write_1h_tokens
            + CACHE_READ_WEIGHT * self.cache_read_tokens
            + OUTPUT_WEIGHT * self.output_tokens
        )


@dataclass(frozen=True, kw_only=True, slots=True)
class Transcripts:
    requests: list[Request]
    pr_links_by_session: dict[str, set[int]]


@dataclass(frozen=True, kw_only=True, slots=True)
class PullRequest:
    number: int
    title: str
    branch: str


@dataclass(frozen=False, kw_only=True, slots=True)
class UsageGroup:
    label: str
    pr_number: int | None
    sessions: set[str] = field(default_factory=set)
    requests: int = 0
    input_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    weighted_tokens: float = 0.0
    peak_context_tokens: int = 0

    def add(self, request: Request) -> None:
        self.sessions.add(request.session_id)
        self.requests += 1
        self.input_tokens += request.input_tokens
        self.cache_write_tokens += request.cache_write_5m_tokens + request.cache_write_1h_tokens
        self.cache_read_tokens += request.cache_read_tokens
        self.output_tokens += request.output_tokens
        self.weighted_tokens += request.weighted_tokens
        self.peak_context_tokens = max(self.peak_context_tokens, request.context_tokens)


def encode_project_dir(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def project_dirs(projects_root: Path, checkouts: Iterable[Path]) -> list[Path]:
    names = {encode_project_dir(checkout) for checkout in checkouts}
    if not projects_root.is_dir():
        return []
    return sorted(
        directory
        for directory in projects_root.iterdir()
        if directory.is_dir()
        and (directory.name in names or any(directory.name.startswith(name + WORKTREES_DIR_SUFFIX) for name in names))
    )


def transcript_files(directory: Path) -> Iterator[Path]:
    yield from directory.glob("*.jsonl")
    yield from directory.glob("*/subagents/*.jsonl")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _request_from_record(record: dict[str, Any]) -> Request | None:
    message = record.get("message") or {}
    usage = message.get("usage")
    message_id = message.get("id") or record.get("requestId")
    if not usage or not message_id or message.get("model") == "<synthetic>" or "timestamp" not in record:
        return None
    cache_creation = usage.get("cache_creation") or {}
    cache_write_total = usage.get("cache_creation_input_tokens") or 0
    cache_write_1h = cache_creation.get("ephemeral_1h_input_tokens") or 0
    return Request(
        message_id=message_id,
        session_id=record.get("sessionId") or "",
        branch=record.get("gitBranch") or "",
        timestamp=_parse_timestamp(record["timestamp"]),
        input_tokens=usage.get("input_tokens") or 0,
        cache_write_5m_tokens=cache_write_total - cache_write_1h,
        cache_write_1h_tokens=cache_write_1h,
        cache_read_tokens=usage.get("cache_read_input_tokens") or 0,
        output_tokens=usage.get("output_tokens") or 0,
    )


def read_transcripts(files: Iterable[Path], since: datetime) -> Transcripts:
    requests_by_message_id: dict[str, Request] = {}
    pr_links_by_session: dict[str, set[int]] = {}
    for path in files:
        with path.open(encoding="utf-8", errors="replace") as lines:
            for line in lines:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "pr-link" and isinstance(record.get("prNumber"), int):
                    pr_links_by_session.setdefault(record.get("sessionId") or "", set()).add(record["prNumber"])
                    continue
                if record.get("type") != "assistant":
                    continue
                request = _request_from_record(record)
                if request is not None and request.timestamp >= since:
                    requests_by_message_id[request.message_id] = request
    return Transcripts(requests=list(requests_by_message_id.values()), pr_links_by_session=pr_links_by_session)


def group_by_pull_request(transcripts: Transcripts, pull_requests: Iterable[PullRequest]) -> list[UsageGroup]:
    by_branch = {pr.branch: pr for pr in pull_requests}
    by_number = {pr.number: pr for pr in by_branch.values()}
    prs_by_session = {session: set(numbers) for session, numbers in transcripts.pr_links_by_session.items()}
    for request in transcripts.requests:
        if request.branch in by_branch:
            prs_by_session.setdefault(request.session_id, set()).add(by_branch[request.branch].number)
    groups: dict[str, UsageGroup] = {}
    for request in transcripts.requests:
        pr = by_branch.get(request.branch)
        if pr is None:
            session_prs = prs_by_session.get(request.session_id, set())
            if len(session_prs) == 1:
                number = next(iter(session_prs))
                pr = by_number.get(number) or PullRequest(number=number, title="", branch="")
        if pr is not None:
            key = f"#{pr.number}"
            label = f"#{pr.number} {pr.title}".strip()
        else:
            key = request.branch or "(no branch)"
            label = key
        group = groups.get(key)
        if group is None:
            group = groups[key] = UsageGroup(label=label, pr_number=pr.number if pr else None)
        group.add(request)
    return sorted(groups.values(), key=lambda group: group.weighted_tokens, reverse=True)


def _checkouts() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    paths = [
        Path(line.removeprefix("worktree ")) for line in result.stdout.splitlines() if line.startswith("worktree ")
    ]
    return paths or [REPO_ROOT]


def _fetch_pull_requests(limit: int) -> list[PullRequest]:
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--author",
                "@me",
                "--state",
                "all",
                "--limit",
                str(limit),
                "--json",
                "number,title,headRefName",
            ],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        click.secho(
            f"Could not list pull requests with gh, so usage is grouped by branch only: {error}", fg="yellow", err=True
        )
        return []
    return [
        PullRequest(number=item["number"], title=item["title"], branch=item["headRefName"])
        for item in json.loads(result.stdout)
    ]


def _format_tokens(value: float) -> str:
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if value >= size:
            return f"{value / size:.1f}{unit}"
    return f"{value:.0f}"


def _print_table(groups: list[UsageGroup]) -> None:
    headers = ("weighted", "sessions", "requests", "input", "cache write", "cache read", "output", "peak ctx", "")
    rows = [
        (
            _format_tokens(group.weighted_tokens),
            str(len(group.sessions)),
            str(group.requests),
            _format_tokens(group.input_tokens),
            _format_tokens(group.cache_write_tokens),
            _format_tokens(group.cache_read_tokens),
            _format_tokens(group.output_tokens),
            _format_tokens(group.peak_context_tokens),
            group.label[:70],
        )
        for group in groups
    ]
    widths = [max(len(header), *(len(row[index]) for row in rows)) for index, header in enumerate(headers[:-1])]
    click.echo("  ".join(header.rjust(width) for header, width in zip(headers, widths)) + "  pull request or branch")
    for row in rows:
        click.echo("  ".join(cell.rjust(width) for cell, width in zip(row, widths)) + "  " + row[-1])


@click.command(name="agent:usage")
@click.option("--days", type=click.IntRange(min=1), default=30, show_default=True, help="Look back this many days.")
@click.option("--limit", type=click.IntRange(min=1), default=25, show_default=True, help="Rows to print.")
@click.option(
    "--claude-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path.home() / ".claude",
    show_default=True,
    help="Claude Code config directory.",
)
@click.option("--json", "as_json", is_flag=True, help="Print every group as JSON.")
def cmd_agent_usage(days: int, limit: int, claude_dir: Path, as_json: bool) -> None:
    """Show Claude Code token usage in this repo, grouped by pull request.

    "weighted" counts every token at its price relative to an uncached input token
    (cache write 1.25x for 5 minutes or 2x for 1 hour, cache read 0.1x, output 5x),
    so it ranks cost without a price table. "peak ctx" is the largest context any
    single request sent.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    directories = project_dirs(claude_dir / "projects", _checkouts())
    transcripts = read_transcripts((path for directory in directories for path in transcript_files(directory)), since)
    if not transcripts.requests:
        click.echo(f"No Claude Code usage for this repo in the last {days} days under {claude_dir / 'projects'}.")
        return

    groups = group_by_pull_request(transcripts, _fetch_pull_requests(limit=1000))
    if as_json:
        click.echo(json.dumps([{**asdict(group), "sessions": len(group.sessions)} for group in groups], indent=2))
        return

    _print_table(groups[:limit])
    total = sum(group.weighted_tokens for group in groups)
    attributed = sum(group.weighted_tokens for group in groups if group.pr_number is not None)
    click.echo(
        f"\n{len(transcripts.requests)} requests in {len(groups)} groups over {days} days. "
        f"{attributed / total:.0%} of weighted tokens map to a pull request."
    )
