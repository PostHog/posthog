#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["anthropic", "PyGithub"]
# ///
# ruff: noqa: T201
"""Stamp a "PR freshness" check on open PRs, with a per-PR staleness budget.

A green CI on a PR that is hundreds of commits behind a fast-moving master is a
lie — it ran against a merge-base that no longer resembles master. This check
turns red once a PR has gone untouched for longer than its budget, nudging the
author to push/rebase (which re-runs CI against current code and clears it).

The budget is *per PR*, not a flat threshold: a cheap LLM reads the file list,
title, and description and estimates how coupled the PR is to fast-moving shared
surface (a repo-wide linter touches cold files but couples to everything, so it
rots fast; a docs tweak couples to nothing). That judgment is content-driven, so
it only needs to run when the content changes — i.e. on a new head commit. We
cache the result in the check's own summary marker, keyed to the head SHA, so a
six-hourly cron just does clock arithmetic against the stored deadline and never
re-invokes the model on an unchanged PR. A new push is a new SHA, which has no
marker, so the budget (and the clock) are recomputed once and renewed.

Fail open everywhere: no model, an outage, or a bad response falls back to a
default budget rather than blocking a merge. Staleness is a soft safeguard.

`classify_freshness`, `tier_to_hours`, the marker codec, and `build_prompt` are
pure and unit-tested; everything touching GitHub or Anthropic is isolated below.
"""

import os
import re
import sys
from datetime import UTC, datetime, timedelta

CHECK_NAME = "PR freshness"
DEFAULT_MODEL = "claude-haiku-4-5"

# Tier → hours of budget. The LLM picks a tier; the hours live here so the
# thresholds can be tuned without re-prompting. `default` is the fail-open
# budget used whenever the model is unavailable or unsure.
TIER_HOURS = {
    "hot": 2,
    "normal": 12,
    "isolated": 48,
    "default": 48,
}

# Bound the prompt: paths and body are the signal, but a 500-file PR or a giant
# description shouldn't blow up the token count.
MAX_FILES_IN_PROMPT = 100
MAX_BODY_CHARS = 2000

_MARKER_RE = re.compile(
    r"<!--\s*pr-freshness:v1\s+tier=(?P<tier>\S+)\s+budget_hours=(?P<hours>\d+)\s+deadline=(?P<deadline>\S+)\s*-->"
)


def tier_to_hours(tier: str) -> int:
    return TIER_HOURS.get(tier, TIER_HOURS["default"])


def parse_tier(text: str) -> str:
    """Map a model reply to a known tier, defaulting if it doesn't name one."""
    lowered = text.lower()
    for tier in ("hot", "isolated", "normal"):
        if tier in lowered:
            return tier
    return "default"


def format_marker(tier: str, budget_hours: int, deadline_iso: str) -> str:
    return f"<!-- pr-freshness:v1 tier={tier} budget_hours={budget_hours} deadline={deadline_iso} -->"


def parse_marker(summary: str | None) -> dict | None:
    """Read a previously-stamped budget back out of a check summary, if present."""
    match = _MARKER_RE.search(summary or "")
    if match is None:
        return None
    return {
        "tier": match.group("tier"),
        "budget_hours": int(match.group("hours")),
        "deadline": match.group("deadline"),
    }


def classify_freshness(now: datetime, deadline: datetime, tier: str, budget_hours: int) -> tuple[str, str, str]:
    """Pure verdict from the clock: red once now is past the stored deadline."""
    if now > deadline:
        overdue = int((now - deadline).total_seconds() // 3600)
        return (
            "failure",
            f"❌ Stale — {overdue}h past its {budget_hours}h freshness budget (tier: {tier})",
            "This PR hasn't moved in a while, so its green CI may have run against a merge-base now far "
            "behind `master`. Push or rebase onto the latest `master` to re-run CI against current code "
            "and clear this check.",
        )
    remaining = int((deadline - now).total_seconds() // 3600)
    return (
        "success",
        f"✅ Fresh — ~{remaining}h of its {budget_hours}h freshness budget remain (tier: {tier})",
        f"This PR is within its {budget_hours}h freshness budget. The budget reflects how coupled the PR "
        "looks to fast-moving `master` surface; pushing or rebasing renews it.",
    )


def build_prompt(title: str, body: str, files: list[str]) -> tuple[str, str]:
    """System + user messages for the one-shot tier classification."""
    system = (
        "You estimate how soon a GitHub pull request's passing CI becomes untrustworthy as its target "
        "branch (`master`) keeps moving. The risk is coupling to fast-moving shared surface, NOT how "
        "often the PR's own files change. Classify into exactly one tier:\n"
        "- hot: couples to fast-moving shared surface — widely-imported modules, base classes, core "
        "types, schemas, migrations, CI/build config, or repo-wide tooling like linters or codemods. "
        "master is likely to change something it depends on soon.\n"
        "- normal: a typical feature or bug fix scoped to one product area.\n"
        "- isolated: docs, tests-only, generated files, or a self-contained corner unlikely to be "
        "affected by master churn.\n"
        "Reply with exactly one word: hot, normal, or isolated."
    )
    shown_files = files[:MAX_FILES_IN_PROMPT]
    extra = len(files) - len(shown_files)
    file_block = "\n".join(shown_files)
    if extra > 0:
        file_block += f"\n…and {extra} more files"
    user = (
        f"Title: {title}\n\n"
        f"Description:\n{(body or '').strip()[:MAX_BODY_CHARS] or '(none)'}\n\n"
        f"Changed files:\n{file_block or '(none)'}"
    )
    return system, user


def classify_tier(title: str, body: str, files: list[str], *, model: str, api_key: str | None) -> str:
    """One-shot LLM tier classification. Fails open to `default` on any problem."""
    if not api_key:
        return "default"
    try:
        import anthropic  # noqa: PLC0415 — heavy optional dep, only loaded when a budget must be computed

        client = anthropic.Anthropic(api_key=api_key)
        system, user = build_prompt(title, body, files)
        response = client.messages.create(
            model=model,
            max_tokens=16,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return parse_tier(text)
    except Exception as exc:
        print(f"[freshness] LLM classification failed, using default budget: {exc}", file=sys.stderr)
        return "default"


def _find_existing_check(repo, sha: str):
    """The most recent freshness check on this head SHA, or None."""
    check_runs = repo.get_commit(sha).get_check_runs(check_name=CHECK_NAME)
    return next(iter(check_runs), None)


def _upsert_check(repo, sha: str, existing, conclusion: str, title: str, summary: str) -> None:
    output = {"title": title, "summary": summary}
    completed_at = datetime.now(UTC)
    if existing is not None:
        existing.edit(status="completed", conclusion=conclusion, completed_at=completed_at, output=output)
        return
    repo.create_check_run(
        name=CHECK_NAME,
        head_sha=sha,
        status="completed",
        conclusion=conclusion,
        completed_at=completed_at,
        output=output,
    )


def _evaluate_pr(repo, pr, now: datetime, *, model: str, api_key: str | None) -> str:
    sha = pr.head.sha
    existing = _find_existing_check(repo, sha)

    marker = parse_marker(existing.output.summary if existing and existing.output else None)
    if marker is not None:
        # Budget already computed for this head SHA — reuse it, no LLM call.
        tier = marker["tier"]
        budget_hours = marker["budget_hours"]
        deadline = datetime.fromisoformat(marker["deadline"])
    else:
        files = [f.filename for f in pr.get_files()]
        tier = classify_tier(pr.title or "", pr.body or "", files, model=model, api_key=api_key)
        budget_hours = tier_to_hours(tier)
        deadline = now + timedelta(hours=budget_hours)

    conclusion, title, body = classify_freshness(now, deadline, tier, budget_hours)
    summary = f"{format_marker(tier, budget_hours, deadline.isoformat())}\n\n{body}"
    _upsert_check(repo, sha, existing, conclusion, title, summary)
    return conclusion


def main() -> None:
    repo_name = os.environ["REPO"]
    token = os.environ["GITHUB_TOKEN"]
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("PR_FRESHNESS_MODEL", DEFAULT_MODEL)
    pr_number = os.environ.get("PR_NUMBER")

    from github import Auth, Github  # noqa: PLC0415 — heavy optional dep, kept off the import path for unit tests

    github = Github(auth=Auth.Token(token))
    repo = github.get_repo(repo_name)

    if pr_number:
        prs = [repo.get_pull(int(pr_number))]
    else:
        prs = list(repo.get_pulls(state="open"))

    now = datetime.now(UTC)
    stale = 0
    for pr in prs:
        if pr.draft:
            print(f"#{pr.number}: draft — skipping")
            continue
        try:
            conclusion = _evaluate_pr(repo, pr, now, model=model, api_key=api_key)
        except Exception as exc:
            # One bad PR must not abort the sweep of the rest.
            print(f"#{pr.number}: error — {exc}", file=sys.stderr)
            continue
        if conclusion == "failure":
            stale += 1
        print(f"#{pr.number}: {conclusion}")

    print(f"Done — {stale} stale PR(s) of {len(prs)} evaluated")


if __name__ == "__main__":
    main()
