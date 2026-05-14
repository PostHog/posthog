"""LLM-driven execution-flow analysis for a pull request.

Fetches the changed files (full content at base + head SHAs), asks an LLM to
reconstruct the BEFORE and AFTER execution flow, and caches the result keyed
by ``head_sha`` in :class:`GitHogPullRequestDataFlow`.

GitHub responses are also mirrored to a local on-disk cache so flimsy
connections don't punish iteration. Cache entries are keyed by SHA where
possible (immutable) and never expire — delete the cache dir to force a
re-fetch.
"""

from __future__ import annotations

import json
import time
import pathlib
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache

import structlog
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.models import Team, User
from posthog.models.integration import GitHubIntegration, Integration

from products.githog.backend.models import GitHogPullRequestDataFlow

from ee.hogai.llm import MaxChatAnthropic

logger = structlog.get_logger(__name__)


# Per-file content cap so any single huge file can't blow the prompt.
PER_FILE_CHAR_CAP = 12_000
# Total cap across all included file content (before+after combined).
TOTAL_CONTENT_CHAR_CAP = 150_000
# Don't try to fetch full file content beyond this many files — fall back to patch-only.
MAX_FILES_FOR_FULL_CONTENT = 40

CACHE_ROOT = pathlib.Path(settings.BASE_DIR) / ".posthog" / "githog_cache"


SYSTEM_PROMPT = """You are a senior software engineer analyzing a pull request.

You will receive, for each changed file: the file's content BEFORE the change, the file's content AFTER the change, and the unified patch. Some files may have content truncated; this is noted inline.

Your job: reconstruct the execution flow of the affected code BEFORE the change and the execution flow AFTER the change as TWO GRAPHS (nodes + directed edges). Then produce a short summary of how the flow changed.

Conventions:
- An "execution flow" is the runtime sequence of steps that happen when the affected feature is exercised: entry point, calls between functions/modules, side effects (network requests, DB writes, emails, file I/O), and where control returns.
- Always identify the user-visible or system-visible ENTRY POINT (HTTP route, CLI command, button click, scheduled task, etc.) and represent it as the FIRST node with `kind="entry"`.
- Other node `kind` values: `"step"` (default), `"side_effect"` (external call, email, DB write), `"return"` (terminal node returning to caller / user).
- Each node has: `id` (short, stable, deterministic — slugified, e.g. `validate_jwt`, `send_reset_email`), `label` (short human title, e.g. "Validate JWT"), `file` (relative path or empty string), `detail` (one sentence — what happens), `kind`.
- Each edge has: `source` (node id), `target` (node id), `label` (optional, e.g. "valid", "expired").

CRITICAL — for the diff view to work, REUSE THE SAME `id` STRING across the before and after graphs for any node that represents the SAME conceptual step. Only assign new ids to truly new behavior. Removed steps live only in the BEFORE graph; new steps live only in the AFTER graph.

Also produce the same flows as ordered `steps_before` / `steps_after` lists for an alternative step-list view; ids in the steps lists must match the graph node ids exactly.

If the change is purely cosmetic (formatting, comments, renames) and the runtime flow is unchanged, say so explicitly in the summary and emit identical or near-identical graphs.

Return strictly the JSON schema requested — no prose outside JSON.

{format_instructions}
"""


USER_PROMPT = """Pull request title: {pr_title}

Pull request body:
{pr_body}

Files ({file_count} total{truncation_note}):

{file_blocks}
"""


class FlowNode(BaseModel):
    id: str = Field(
        description="Stable, slugified id reused across before/after when the step is conceptually the same"
    )
    label: str = Field(description="Short human title for the step")
    file: str = Field(default="", description="Relative file path this step lives in, or empty if N/A")
    detail: str = Field(default="", description="One sentence describing what happens at this step")
    kind: str = Field(default="step", description="entry | step | side_effect | return")


class FlowEdge(BaseModel):
    source: str = Field(description="Source FlowNode.id")
    target: str = Field(description="Target FlowNode.id")
    label: str = Field(default="", description="Optional edge label")


class FlowGraph(BaseModel):
    nodes: list[FlowNode] = Field(default_factory=list)
    edges: list[FlowEdge] = Field(default_factory=list)


class DataFlowStep(BaseModel):
    id: str = Field(
        default="", description="Matches the corresponding FlowNode id in the graph (or empty for legacy outputs)"
    )
    title: str = Field(description="Short imperative phrase, e.g. 'Validate JWT'")
    file: str = Field(default="", description="Relative file path this step lives in")
    detail: str = Field(default="", description="One sentence describing what happens in this step")


class DataFlowOutput(BaseModel):
    flow_before: FlowGraph = Field(default_factory=FlowGraph)
    flow_after: FlowGraph = Field(default_factory=FlowGraph)
    steps_before: list[DataFlowStep] = Field(default_factory=list)
    steps_after: list[DataFlowStep] = Field(default_factory=list)
    summary: str = Field(description="2-4 sentence summary of how the flow changed")


# ─── Local file-based GitHub cache ──────────────────────────────────────────


def _cache_path(*parts: str) -> pathlib.Path:
    safe = [quote(p, safe="") for p in parts if p]
    return CACHE_ROOT.joinpath(*safe)


def _read_cache(path: pathlib.Path) -> str | None:
    try:
        return path.read_text("utf-8")
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("githog.data_flow: cache read failed", path=str(path), error=str(exc))
        return None


def _write_cache(path: pathlib.Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, "utf-8")
    except Exception as exc:
        logger.warning("githog.data_flow: cache write failed", path=str(path), error=str(exc))


def _cached_pr_meta(github: GitHubIntegration, repository: str, repo_name: str, pr_number: int) -> dict[str, Any]:
    """PR metadata can shift over time; we cache it as a mock so we don't refetch on every load.
    Delete the cache file (or whole cache dir) to refresh.
    """
    path = _cache_path(repository, f"pr-{pr_number}-meta.json")
    cached = _read_cache(path)
    if cached is not None:
        try:
            data = json.loads(cached)
            if data.get("success"):
                logger.info("githog.data_flow: pr meta cache hit", pr=pr_number)
                return data
        except json.JSONDecodeError:
            pass
    data = github.get_pull_request(repo_name, pr_number)
    if data.get("success"):
        _write_cache(path, json.dumps(data))
    return data


def _cached_pr_files(
    github: GitHubIntegration, repository: str, repo_name: str, pr_number: int, head_sha: str
) -> dict[str, Any]:
    """Files list is SHA-keyed so it's safe to cache forever per head_sha."""
    path = _cache_path(repository, f"pr-{pr_number}-files-{head_sha}.json")
    cached = _read_cache(path)
    if cached is not None:
        try:
            data = json.loads(cached)
            if data.get("success"):
                logger.info("githog.data_flow: pr files cache hit", pr=pr_number, sha=head_sha[:8])
                return data
        except json.JSONDecodeError:
            pass
    data = github.list_pull_request_files(repo_name, pr_number)
    if data.get("success"):
        _write_cache(path, json.dumps(data))
    return data


def _cached_file_content(github: GitHubIntegration, repository: str, repo_name: str, path: str, sha: str) -> str | None:
    """SHA + path is immutable, so cache forever once fetched.
    Returns None for missing files (added/removed) or transient failures."""
    cache_file = _cache_path(repository, "blob", sha, path)
    cached = _read_cache(cache_file)
    if cached is not None:
        logger.info("githog.data_flow: blob cache hit", path=path, sha=sha[:8])
        return cached
    try:
        resp = github.get_file_content(repo_name, path, sha)
    except Exception as exc:
        logger.warning("githog.data_flow: file content fetch failed", path=path, sha=sha[:8], error=str(exc))
        return None
    if not resp.get("success"):
        logger.info(
            "githog.data_flow: file content unavailable", path=path, sha=sha[:8], status=resp.get("status_code")
        )
        return None
    content = resp.get("content") or ""
    _write_cache(cache_file, content)
    return content


# ─── Prompt assembly ────────────────────────────────────────────────────────


def _truncate(text: str, cap: int) -> tuple[str, bool]:
    if len(text) <= cap:
        return text, False
    return text[:cap] + "\n…<truncated>…\n", True


def _format_file_block(
    *,
    filename: str,
    status: str,
    patch: str,
    before: str | None,
    after: str | None,
) -> tuple[str, int, bool]:
    parts = [f"### {filename} ({status})"]
    truncated = False
    used = 0
    if before is not None:
        body, did = _truncate(before, PER_FILE_CHAR_CAP)
        truncated = truncated or did
        used += len(body)
        parts.append(f"BEFORE:\n```\n{body}\n```")
    else:
        parts.append("BEFORE: <file did not exist>")
    if after is not None:
        body, did = _truncate(after, PER_FILE_CHAR_CAP)
        truncated = truncated or did
        used += len(body)
        parts.append(f"AFTER:\n```\n{body}\n```")
    else:
        parts.append("AFTER: <file deleted>")
    if patch:
        patch_body, did = _truncate(patch, PER_FILE_CHAR_CAP)
        truncated = truncated or did
        used += len(patch_body)
        parts.append(f"PATCH:\n```diff\n{patch_body}\n```")
    return "\n\n".join(parts), used, truncated


def _collect_file_blocks(
    *,
    github: GitHubIntegration,
    repository: str,
    repo_name: str,
    files: list[dict],
    base_sha: str,
    head_sha: str,
) -> tuple[list[str], bool, int]:
    """Returns (blocks, truncated_any, files_with_content)."""
    blocks: list[str] = []
    total = 0
    truncated_any = False
    files_with_content = 0
    patch_only_mode = len(files) > MAX_FILES_FOR_FULL_CONTENT
    for f in files:
        filename = f["filename"]
        status = f["status"]
        patch = f.get("patch") or ""
        before: str | None
        after: str | None
        if patch_only_mode or total > TOTAL_CONTENT_CHAR_CAP:
            before, after = None, None
            truncated_any = True
        else:
            if status == "added":
                before = None
            else:
                prev_path = f.get("previous_filename") or filename
                before = _cached_file_content(github, repository, repo_name, prev_path, base_sha)
                if before is None and status != "removed":
                    truncated_any = True
            if status == "removed":
                after = None
            else:
                after = _cached_file_content(github, repository, repo_name, filename, head_sha)
                if after is None and status != "added":
                    truncated_any = True
        if before is not None or after is not None:
            files_with_content += 1
        block, used, was_truncated = _format_file_block(
            filename=filename, status=status, patch=patch, before=before, after=after
        )
        blocks.append(block)
        total += used
        truncated_any = truncated_any or was_truncated
    return blocks, truncated_any, files_with_content


# ─── Entry point ────────────────────────────────────────────────────────────


def compute_data_flow(
    *,
    team: Team,
    user: User,
    integration: Integration,
    repository: str,
    pr_number: int,
    refresh: bool = False,
) -> tuple[GitHogPullRequestDataFlow, bool]:
    """Returns (row, was_cached). When was_cached is True, no LLM call was made."""
    github = GitHubIntegration(integration)
    _, _, repo_name = repository.partition("/")

    pr_meta = _cached_pr_meta(github, repository, repo_name, pr_number)
    if not pr_meta.get("success"):
        raise ValueError(pr_meta.get("error") or "Failed to fetch PR metadata")

    head_sha: str = pr_meta["head_sha"]
    base_sha: str = pr_meta["base_sha"]

    if not refresh:
        cached = GitHogPullRequestDataFlow.objects.filter(
            team=team, repository=repository, pr_number=pr_number, head_sha=head_sha
        ).first()
        if cached is not None:
            return cached, True

    # Single-flight: prevent concurrent requests for the same (team, repo, pr, head_sha)
    # from all firing duplicate LLM calls (React StrictMode dev double-mount or two browser tabs).
    # First request acquires the lock; later requests poll the DB for the row.
    lock_key = f"githog:dataflow:lock:{team.id}:{repository}:{pr_number}:{head_sha}"
    lock_acquired = cache.add(lock_key, "1", timeout=600) if not refresh else True
    if not lock_acquired:
        logger.info("githog.data_flow: another worker computing this PR, polling", pr=pr_number, head=head_sha[:8])
        deadline = time.monotonic() + 300  # 5 min cap
        while time.monotonic() < deadline:
            time.sleep(2)
            existing = GitHogPullRequestDataFlow.objects.filter(
                team=team, repository=repository, pr_number=pr_number, head_sha=head_sha
            ).first()
            if existing is not None:
                return existing, True
        # Timed out — fall through and compute ourselves rather than fail.
        logger.warning("githog.data_flow: poll timeout, computing anyway", pr=pr_number, head=head_sha[:8])

    try:
        return _do_compute(
            team=team,
            user=user,
            github=github,
            repository=repository,
            repo_name=repo_name,
            pr_number=pr_number,
            pr_meta=pr_meta,
            head_sha=head_sha,
            base_sha=base_sha,
        )
    finally:
        cache.delete(lock_key)


def _do_compute(
    *,
    team: Team,
    user: User,
    github: GitHubIntegration,
    repository: str,
    repo_name: str,
    pr_number: int,
    pr_meta: dict[str, Any],
    head_sha: str,
    base_sha: str,
) -> tuple[GitHogPullRequestDataFlow, bool]:
    files_result = _cached_pr_files(github, repository, repo_name, pr_number, head_sha)
    if not files_result.get("success"):
        raise ValueError(files_result.get("error") or "Failed to list PR files")

    files = files_result["files"]
    file_blocks, truncated, files_with_content = _collect_file_blocks(
        github=github,
        repository=repository,
        repo_name=repo_name,
        files=files,
        base_sha=base_sha,
        head_sha=head_sha,
    )

    parser = PydanticOutputParser(pydantic_object=DataFlowOutput)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("user", USER_PROMPT),
        ]
    ).partial(format_instructions=parser.get_format_instructions())

    model = MaxChatAnthropic(
        model="claude-sonnet-4-5",
        temperature=0.2,
        max_tokens=16_384,
        user=user,
        team=team,
        billable=True,
        streaming=False,
        disable_streaming=True,
        inject_context=False,
    )

    chain = prompt | model | parser

    truncation_note = " — content truncated" if truncated else ""
    output: DataFlowOutput = chain.invoke(
        {
            "pr_title": pr_meta.get("title") or "",
            "pr_body": pr_meta.get("body") or "",
            "file_count": len(files),
            "truncation_note": truncation_note,
            "file_blocks": "\n\n---\n\n".join(file_blocks) or "<no files>",
        }
    )

    logger.info(
        "githog.data_flow: computed",
        pr=pr_number,
        head=head_sha[:8],
        files_total=len(files),
        files_with_content=files_with_content,
        truncated=truncated,
        nodes_before=len(output.flow_before.nodes),
        nodes_after=len(output.flow_after.nodes),
    )

    row, _ = GitHogPullRequestDataFlow.objects.update_or_create(
        team=team,
        repository=repository,
        pr_number=pr_number,
        head_sha=head_sha,
        defaults={
            "base_sha": base_sha,
            "flow_before": output.flow_before.model_dump(),
            "flow_after": output.flow_after.model_dump(),
            "steps_before": [s.model_dump() for s in output.steps_before],
            "steps_after": [s.model_dump() for s in output.steps_after],
            "summary": output.summary,
            "truncated": truncated,
            "files_total": len(files),
            "files_with_content": files_with_content,
        },
    )
    return row, False
