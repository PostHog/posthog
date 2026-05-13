"""LLM-driven execution-flow analysis for a pull request.

Fetches the changed files (full content at base + head SHAs), asks an LLM to
reconstruct the BEFORE and AFTER execution flow, and caches the result keyed
by `head_sha` in `GitHogPullRequestDataFlow`.
"""

from __future__ import annotations

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


SYSTEM_PROMPT = """You are a senior software engineer analyzing a pull request.

You will receive, for each changed file: the file's content BEFORE the change, the file's content AFTER the change, and the unified patch. Some files may have content truncated; this is noted inline.

Your job: reconstruct the execution flow of the affected code BEFORE the change and the execution flow AFTER the change. Then produce a short summary of how the flow changed.

Conventions:
- An "execution flow" is the ordered series of steps that happen at runtime when the affected feature is exercised: entry point, calls between functions/modules, side effects (network requests, DB writes, emails, file I/O), and where control returns.
- Always identify the user-visible or system-visible ENTRY POINT (HTTP route, CLI command, button click, scheduled task, etc.).
- A "step" has a `title` (short imperative phrase), a `file` (relative path), and a `detail` (one sentence — what happens at this step).
- Mermaid output must be valid `sequenceDiagram` syntax. Use participant names that match files or logical components. Keep it readable — group related calls.
- If a file was newly added, its flow appears only on the AFTER side. If deleted, only on BEFORE.
- If the change is purely cosmetic (formatting, comments, renames) and the runtime flow is unchanged, say so explicitly in the summary and emit identical or near-identical flows.

Return strictly the JSON schema requested — no prose outside JSON.

{format_instructions}
"""


USER_PROMPT = """Pull request title: {pr_title}

Pull request body:
{pr_body}

Files ({file_count} total{truncation_note}):

{file_blocks}
"""


class DataFlowStep(BaseModel):
    title: str = Field(description="Short imperative phrase, e.g. 'Validate JWT'")
    file: str = Field(description="Relative file path this step lives in")
    detail: str = Field(description="One sentence describing what happens in this step")


class DataFlowOutput(BaseModel):
    mermaid_before: str = Field(description="Mermaid sequenceDiagram for the BEFORE flow")
    mermaid_after: str = Field(description="Mermaid sequenceDiagram for the AFTER flow")
    steps_before: list[DataFlowStep] = Field(default_factory=list)
    steps_after: list[DataFlowStep] = Field(default_factory=list)
    summary: str = Field(description="2-4 sentence summary of how the flow changed")


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


def _safe_get_file_content(github: GitHubIntegration, repository: str, path: str, ref: str) -> str | None:
    """Fetch file content, swallowing transient network errors so one bad file doesn't sink the whole request."""
    try:
        resp = github.get_file_content(repository, path, ref)
    except Exception as exc:
        logger.warning("githog.data_flow: file content fetch failed", path=path, ref=ref[:8], error=str(exc))
        return None
    if not resp.get("success"):
        logger.info(
            "githog.data_flow: file content unavailable",
            path=path,
            ref=ref[:8],
            status=resp.get("status_code"),
        )
        return None
    return resp.get("content")


def _collect_file_blocks(
    *,
    github: GitHubIntegration,
    repository: str,
    files: list[dict],
    base_sha: str,
    head_sha: str,
) -> tuple[list[str], bool]:
    blocks: list[str] = []
    total = 0
    truncated_any = False
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
                before = _safe_get_file_content(github, repository, prev_path, base_sha)
                if before is None and status != "removed":
                    truncated_any = True
            if status == "removed":
                after = None
            else:
                after = _safe_get_file_content(github, repository, filename, head_sha)
                if after is None and status != "added":
                    truncated_any = True
        block, used, was_truncated = _format_file_block(
            filename=filename, status=status, patch=patch, before=before, after=after
        )
        blocks.append(block)
        total += used
        truncated_any = truncated_any or was_truncated
    return blocks, truncated_any


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

    pr_meta = github.get_pull_request(repo_name, pr_number)
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

    files_result = github.list_pull_request_files(repo_name, pr_number)
    if not files_result.get("success"):
        raise ValueError(files_result.get("error") or "Failed to list PR files")

    files = files_result["files"]
    file_blocks, truncated = _collect_file_blocks(
        github=github,
        repository=repo_name,
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
        max_tokens=4096,
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

    row, _ = GitHogPullRequestDataFlow.objects.update_or_create(
        team=team,
        repository=repository,
        pr_number=pr_number,
        head_sha=head_sha,
        defaults={
            "base_sha": base_sha,
            "mermaid_before": output.mermaid_before,
            "mermaid_after": output.mermaid_after,
            "steps_before": [s.model_dump() for s in output.steps_before],
            "steps_after": [s.model_dump() for s in output.steps_after],
            "summary": output.summary,
            "truncated": truncated,
        },
    )
    return row, False
