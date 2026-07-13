"""Sandbox reviewer invocation + output parsing.

The whole review engine — hard gates, tier classification, git-blame
familiarity, and the LLM reviewer — now runs inside the sandbox via the Action's
own modules (``tools/pr-approval-agent/review_local.py``). This module no longer
embeds a reviewer script; it only:

- ``build_reviewer_invocation``: assembles the ``--context`` JSON payload the
  sandbox entrypoint consumes (PR metadata, changed files, the author's merged-PR
  numbers, base/head shas) and the ``uv run`` command to execute it.
- ``parse_reviewer_output``: turns the entrypoint's last stdout JSON line — the
  Action's full ``to_dict()`` contract — into a verdict, defensively. A run we
  can't read is never an approval: malformed output escalates.

The trusted review-norms prose and gate policy are NOT passed here — the server
overwrites ``.stamphog/policy.yml`` and ``.stamphog/review-guidance.md`` in the
checkout with the default-branch versions, and the engine reads them from there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

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


@dataclass
class ReviewerInvocation:
    """Everything needed to run the reviewer inside the sandbox.

    ``context_json`` is written to ``context_path`` in the checkout; ``command``
    (``uv run <engine>/review_local.py --context <context_path>``) runs it. The
    engine source files and the trusted policy files are placed separately by the
    activity. ANTHROPIC_API_KEY is expected in the sandbox environment.
    """

    command: list[str]
    context_path: str
    context_json: str


@dataclass
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
    # The engine version the output reports, for analytics segmentation.
    stamphog_version: str = ""


def build_reviewer_invocation(
    *,
    pr: dict,
    files: list[dict],
    author_pr_numbers: list[int],
    base_sha: str,
    head_sha: str,
    repo: str,
    engine_dir: str,
    context_path: str,
) -> ReviewerInvocation:
    """Assemble the context payload + command that reviews this PR in the sandbox.

    ``pr`` is the raw GitHub PR object (get_pr), ``files`` the raw changed-files
    payload (get_pr_files) — both passed through unchanged so the engine can build
    its own PRData. ``author_pr_numbers`` are the author's merged-PR numbers the
    server fetched (the engine needs them for the git-blame familiarity signal,
    which it otherwise gets from a `gh` call it can't make in the sandbox).
    """
    context = {
        "repo": repo,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "pr": pr,
        "files": files,
        "author_pr_numbers": list(author_pr_numbers),
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
