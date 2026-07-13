"""LLM summarization of merged PRs for the daily digest.

Boring by design: ask a cheap model to drop trivial PRs (version bumps, typo fixes) and give the
rest a one-line plain-language summary plus a short intro. Any failure falls back to a deterministic
list of every PR with its title as the summary, so a flaky model never loses a digest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from posthog.llm.gateway_client import get_llm_client

if TYPE_CHECKING:
    from ..models import PullRequest

logger = structlog.get_logger(__name__)

# Cheap, fast model — the digest is a summarization job, not deep reasoning.
_DIGEST_MODEL = "claude-haiku-4-5"
_SOURCE_PRODUCT = "stamphog_digest"


@dataclass
class DigestPRSummary:
    pr_number: int
    title: str
    url: str
    author_login: str
    summary: str


@dataclass
class DigestSummary:
    intro: str
    prs: list[DigestPRSummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fallback_summary(prs: list[PullRequest]) -> DigestSummary:
    """Deterministic no-LLM summary: keep every PR, use its title as the one-liner."""
    count = len(prs)
    intro = f"{count} pull request{'s' if count != 1 else ''} merged in the last day."
    return DigestSummary(
        intro=intro,
        prs=[
            DigestPRSummary(
                pr_number=pr.pr_number,
                title=pr.title,
                url=pr.pr_url,
                author_login=pr.author_login,
                summary=pr.title,
            )
            for pr in prs
        ],
    )


def _build_prompt(prs: list[PullRequest]) -> str:
    lines = [
        "You are summarizing merged pull requests for a daily engineering digest posted to Slack.",
        "Drop trivial PRs (dependency bumps, typo fixes, formatting-only changes).",
        "For each worthwhile PR, write a one-line plain-language summary of what it changes and why.",
        "Also write a 1-2 sentence overall intro for the digest.",
        "",
        "Return STRICT JSON only, no prose, in this shape:",
        '{"intro": "...", "prs": [{"pr_number": 123, "summary": "..."}]}',
        "",
        "Pull requests:",
    ]
    for pr in prs:
        repository = pr.repo_config.repository
        lines.append(
            f"- #{pr.pr_number} [{repository}] {pr.title} by {pr.author_login} "
            f"(+{pr.additions}/-{pr.deletions}, {pr.changed_files} files) {pr.pr_url}"
        )
        if pr.body_excerpt:
            lines.append(f"  description: {pr.body_excerpt}")
    return "\n".join(lines)


def _parse_llm_response(content: str, prs_by_number: dict[int, PullRequest]) -> DigestSummary:
    """Map the model's JSON back onto captured PRs. Unknown PR numbers are ignored."""
    data = json.loads(content)
    intro = str(data.get("intro") or "").strip()
    picked: list[DigestPRSummary] = []
    for item in data.get("prs") or []:
        if not isinstance(item, dict):
            continue
        number = item.get("pr_number")
        pr = prs_by_number.get(number) if isinstance(number, int) else None
        if pr is None:
            continue
        picked.append(
            DigestPRSummary(
                pr_number=pr.pr_number,
                title=pr.title,
                url=pr.pr_url,
                author_login=pr.author_login,
                summary=str(item.get("summary") or pr.title).strip() or pr.title,
            )
        )
    if not picked:
        # The model returned nothing usable — don't post an empty digest, fall back to all PRs.
        raise ValueError("LLM returned no recognizable PRs")
    return DigestSummary(intro=intro or _fallback_summary(list(prs_by_number.values())).intro, prs=picked)


def summarize_merged_prs(prs: list[PullRequest]) -> DigestSummary:
    """Summarize merged PRs into a digest, falling back to a plain list on any failure."""
    if not prs:
        return DigestSummary(intro="No pull requests merged.", prs=[])

    team_id = prs[0].team_id
    try:
        client = get_llm_client(product="stamphog", team_id=team_id)
        response = client.chat.completions.create(
            model=_DIGEST_MODEL,
            messages=[{"role": "user", "content": _build_prompt(prs)}],
            user=f"team-{team_id}",
            extra_headers={"x-posthog-property-source_product": _SOURCE_PRODUCT},
        )
        content = response.choices[0].message.content or ""
        return _parse_llm_response(content, {pr.pr_number: pr for pr in prs})
    except Exception as e:
        logger.warning("stamphog_digest_summarize_fallback", team_id=team_id, error=str(e))
        return _fallback_summary(prs)
