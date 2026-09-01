"""Sandbox reviewer invocation + output parsing.

The whole review engine (hard gates, tier classification, git-blame
familiarity, and the LLM reviewer) runs inside the sandbox via the engine's own
modules (``products/stamphog/packages/pr-approval-agent/review_local.py``). This
module no longer embeds a reviewer script. It only does two things:

- ``build_reviewer_invocation``: assembles the ``--context`` JSON payload the
  sandbox entrypoint consumes (PR metadata, changed files, the author's merged-PR
  numbers, base/head shas) and the ``uv run`` command to execute it.
- ``parse_reviewer_output``: turns the entrypoint's last stdout JSON line, which
  is the engine's full ``to_dict()`` contract, into a verdict. It parses
  defensively, because a run that the server cannot read is never an approval.
  Malformed output escalates.

The trusted review-norms prose and gate policy are NOT passed here — the server
overwrites ``.stamphog/policy.yml`` and ``.stamphog/review-guidance.md`` in the
checkout with the default-branch versions, and the engine reads them from there.
"""

from __future__ import annotations

import json
from dataclasses import field

from posthog.dataclasses import frozen

# Final-verdict strings the engine emits (review_pr.Pipeline.final_verdict) mapped
# onto the contract's ReviewVerdict values. Anything unrecognized escalates —
# never silently approve on a verdict we can't trust.
_FINAL_VERDICT_MAP = {
    "APPROVED": "approved",
    "REFUSED": "refused",
    "ESCALATE": "escalate",
    "WAIT": "wait",
    "ERROR": "error",
    "DRY-RUN": "escalate",
}

# Legacy single-object verdict shape (verdict/reasoning/issues), tolerated so an
# older engine output still parses to a defined verdict rather than escalating.
_LEGACY_VERDICT_MAP = {
    "APPROVE": "approved",
    "REFUSE": "refused",
    "ESCALATE": "escalate",
    "approved": "approved",
    "refused": "refused",
    "escalate": "escalate",
    "wait": "wait",
    "error": "error",
}


# Mirrors the engine's VERDICT_SCHEMA cap (products/stamphog/packages/pr-approval-agent/reviewer.py) and the
# stamphog_reviewrun column width.
CHANGE_SUMMARY_MAX_CHARS = 200


@frozen
class ReviewerInvocation:
    """Everything needed to run the reviewer inside the sandbox.

    ``context_json`` is written to ``context_path`` in the checkout; ``command``
    (``uv run <engine>/review_local.py --context <context_path>``) runs it. The
    engine source files and the trusted policy files are placed separately by the
    activity. The LLM credentials (AI_GATEWAY_URL plus a per-run minted
    AI_GATEWAY_API_KEY) are expected in the sandbox environment.
    """

    command: list[str]
    context_path: str
    context_json: str


@frozen
class ReviewerVerdict:
    """Parsed result of one reviewer run."""

    verdict: str
    reasoning: str
    showstoppers: list[str] = field(default_factory=list)
    # A deny by the deterministic gates (size, deny-list, tier, prerequisites),
    # derived from the output's gate section — a first-class outcome, not an error.
    gate_blocked: bool = False
    # The output's gate/classification/policy sections, stashed on the run for audit.
    gate_result: dict = field(default_factory=dict)
    # The engine-rendered comment body (reasoning + judgment bullets + gate
    # mechanics), posted verbatim when present.
    review_body: str = ""
    # One-sentence plain-language description of what the change does, written
    # in the sandbox where the diff is available. Feeds the daily digest. Blank
    # when the engine predates the field, which the digest tolerates.
    change_summary: str = ""
    # The engine version the output reports, for analytics segmentation.
    stamphog_version: str = ""


def build_reviewer_invocation(
    *,
    pr: dict,
    files: list[dict],
    reviews: list[dict],
    discussion: list[dict],
    review_threads: list[dict],
    check_runs: list[dict],
    pr_reactions: list[dict],
    author_pr_numbers: list[int],
    author_team_slugs: list[str],
    base_sha: str,
    head_sha: str,
    repo: str,
    engine_dir: str,
    context_path: str,
    self_driving_review: bool = False,
    review_trigger: str = "",
) -> ReviewerInvocation:
    """Assemble the context payload + command that reviews this PR in the sandbox.

    ``pr`` is the raw GitHub PR object (get_pr), ``files`` the raw changed-files
    payload (get_pr_files) — both passed through unchanged so the engine can build
    its own PRData. ``review_threads`` are the PR's inline review threads (a
    GraphQL-only surface the tokenless sandbox can't fetch itself), so an
    unresolved inline "do not merge" reaches the reviewer prompt.
    ``author_pr_numbers`` are the author's merged-PR numbers the server fetched
    (the engine needs them for the git-blame familiarity signal, which it
    otherwise gets from a `gh` call it can't make in the sandbox).
    ``author_team_slugs`` are every GitHub team the author belongs to, which the
    engine intersects with the teams owning the changed paths to tell the reviewer
    whether the author owns the code (another `gh` call the sandbox can't make).
    ``self_driving_review`` lets the engine review a bot-authored draft, the one exception
    to its bot-author refusal. It defaults closed here and in the engine, the Action runtime
    never sets it, and only a run stamped with inbox provenance turns it on.
    ``review_trigger`` is a ReviewTrigger value naming why stamphog is looking at this PR, which
    the reviewer otherwise cannot tell: a requested review and an automatic one reach it identically.
    It stays separate from ``self_driving_review`` on purpose. That flag relaxes two security gates,
    this string only describes, and folding them together would put the carve-out back in play for
    a change to descriptive text. Empty for a local run, where there is no trigger to report.
    """
    context = {
        "repo": repo,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "pr": pr,
        "files": files,
        "reviews": reviews,
        "discussion": discussion,
        "review_threads": review_threads,
        "check_runs": check_runs,
        "pr_reactions": pr_reactions,
        "author_pr_numbers": list(author_pr_numbers),
        "author_team_slugs": list(author_team_slugs),
        "self_driving_review": self_driving_review,
        "review_trigger": review_trigger,
    }
    command = ["uv", "run", f"{engine_dir}/review_local.py", "--context", context_path]
    return ReviewerInvocation(
        command=command,
        context_path=context_path,
        context_json=json.dumps(context, ensure_ascii=False),
    )


def parse_reviewer_output(raw: str) -> ReviewerVerdict:
    """Extract the verdict from the engine's stdout, tolerant of surrounding noise.

    The engine prints its full ``to_dict()`` contract as a single compact JSON
    object on the last stdout line, but uv/SDK log lines can follow or interleave,
    so scan newest-first and take the first object that parses. The richer shape
    (``final_verdict`` + nested ``reviewer``/``gates``) is preferred; a legacy
    single ``verdict`` object is still understood. Anything unparseable falls back
    to escalate — a run we can't read is never an approval.
    """
    obj = _find_result_object(raw)
    if obj is None:
        return ReviewerVerdict(
            verdict="escalate",
            reasoning="Reviewer produced no parseable verdict — escalating for a human.",
            showstoppers=["No JSON verdict found in reviewer output"],
        )
    if "final_verdict" in obj:
        return _parse_rich(obj)
    return _parse_legacy(obj)


def _parse_rich(obj: dict) -> ReviewerVerdict:
    final = str(obj.get("final_verdict", "")).strip()
    verdict = _FINAL_VERDICT_MAP.get(final, "escalate")

    reviewer = obj.get("reviewer") or {}
    reasoning = str(reviewer.get("reasoning", "")).strip()
    # Clipped rather than rejected: the engine caps this at CHANGE_SUMMARY_MAX_CHARS, but the
    # value crosses a trust boundary, so the server does not rely on the sandbox honoring it.
    change_summary = str(reviewer.get("change_summary", "")).strip()[:CHANGE_SUMMARY_MAX_CHARS]
    issues = reviewer.get("issues") or []
    showstoppers = [str(i) for i in issues] if isinstance(issues, list) else [str(issues)]

    gates = obj.get("gates") or []
    gate_blocked = any(not g.get("passed", True) for g in gates if isinstance(g, dict))
    if verdict == "escalate" and final not in _FINAL_VERDICT_MAP:
        showstoppers.append(f"Unrecognized final verdict value: {final!r}")

    gate_result = {
        "gate_blocked": gate_blocked,
        "final_verdict": final,
        "gates": gates,
        "classification": obj.get("classification") or {},
        "policy": obj.get("policy") or {},
    }
    return ReviewerVerdict(
        verdict=verdict,
        reasoning=reasoning,
        showstoppers=showstoppers,
        gate_blocked=gate_blocked,
        gate_result=gate_result,
        review_body=str(obj.get("review_body") or ""),
        change_summary=change_summary,
        stamphog_version=str(obj.get("stamphog_version") or ""),
    )


def _parse_legacy(obj: dict) -> ReviewerVerdict:
    raw_verdict = str(obj.get("verdict", "")).strip()
    verdict = _LEGACY_VERDICT_MAP.get(raw_verdict, "escalate")
    reasoning = str(obj.get("reasoning", "")).strip()
    issues = obj.get("issues") or obj.get("showstoppers") or []
    showstoppers = [str(i) for i in issues] if isinstance(issues, list) else [str(issues)]
    if verdict == "escalate" and raw_verdict not in _LEGACY_VERDICT_MAP:
        showstoppers.append(f"Unrecognized verdict value: {raw_verdict!r}")
    return ReviewerVerdict(verdict=verdict, reasoning=reasoning, showstoppers=showstoppers)


def _find_result_object(raw: str) -> dict | None:
    for line in reversed((raw or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ("final_verdict" in parsed or "verdict" in parsed):
            return parsed
    return None
