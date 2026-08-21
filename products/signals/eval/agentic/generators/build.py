"""Builders that turn the synthetic eval manifest + templates into case dicts.

Each builder returns a list of JSON-serializable dicts (the loader in ``generated.py`` turns
them into typed Case objects and attaches scorers). Generation is deterministic (index-based,
no RNG) so regenerating the same project yields a stable, diffable dataset.

All builders use committed synthetic/public inputs so regenerated tracked fixtures cannot
leak data from a developer's local project. Run via the ``generate_eval_cases`` command.
"""

from __future__ import annotations

import re
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_STOP = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "your",
    "our",
    "from",
    "into",
    "over",
    "issue",
    "error",
    "errors",
    "api",
    "app",
    "page",
    "data",
    "user",
    "users",
    "posthog",
    "project",
    "repo",
    "repository",
    "github",
    "platform",
    "open",
    "source",
    "alternative",
}

# Source archetypes for templated verdict-variety research cases.
_VERDICT_TEMPLATES: tuple[dict, ...] = (
    {
        "kind": "bug",
        "source_product": "zendesk",
        "source_type": "ticket",
        "text": "A customer reports a clear, reproducible bug: {detail}. Steps and expected vs actual are included.",
        "actionability": ["immediately_actionable", "requires_human_input"],
        "priority": ["P1", "P2", "P3"],
    },
    {
        "kind": "feature",
        "source_product": "linear",
        "source_type": "issue_created",
        "text": "Feature request: {detail}. Several customers have asked for this capability.",
        "actionability": ["requires_human_input", "immediately_actionable"],
        "priority": ["P2", "P3", "P4"],
    },
    {
        "kind": "vague",
        "source_product": "conversations",
        "source_type": "message",
        "text": "A user vaguely says: '{detail}'. No specifics, repro, or scope.",
        "actionability": ["requires_human_input", "not_actionable"],
        "priority": ["P3", "P4"],
    },
    {
        "kind": "perf",
        "source_product": "github",
        "source_type": "issue_created",
        "text": "Performance report: {detail}. Users notice slowness under load.",
        "actionability": ["immediately_actionable", "requires_human_input"],
        "priority": ["P1", "P2", "P3"],
    },
)

_VERDICT_DETAILS: tuple[tuple[str, str], ...] = (
    ("bug", "the file upload progress bar sticks at 99% and never completes"),
    ("bug", "shared links 404 for recipients who are not logged in"),
    ("bug", "the dashboard date filter resets to default on refresh"),
    ("bug", "CSV export drops the last row when the table is paginated"),
    ("bug", "the mobile nav menu cannot be closed once opened"),
    ("feature", "let users bulk-download a whole folder as a single zip"),
    ("feature", "add a dark mode toggle to the settings page"),
    ("feature", "support SSO login via Okta for enterprise accounts"),
    ("feature", "allow scheduling a report to be emailed weekly"),
    ("feature", "add keyboard shortcuts for the most common actions"),
    ("vague", "the product just feels kind of slow and clunky sometimes"),
    ("vague", "something seems off lately, not sure what"),
    ("vague", "the new design is weird"),
    ("perf", "the file list takes 8+ seconds to load for large accounts"),
    ("perf", "search latency spikes during business hours"),
    ("perf", "the app uses a lot of memory and tabs get killed"),
)


# Minimum length for a summary_must_mention keyword — shorter tokens match almost any summary.
_MIN_TOKEN_LEN = 5


def _case_token(name: str) -> str | None:
    """A discriminating keyword for ground truth, or None when the name has none.

    No fallback: a name made only of stop-words/short tokens (e.g. an issue literally named
    'Error') yields a keyword that any summary mentions, so such names produce no case.
    """
    toks = [t for t in re.findall(rf"[A-Za-z]{{{_MIN_TOKEN_LEN},}}", name.lower()) if t not in _STOP]
    return max(toks, key=lambda t: len(t)) if toks else None


def _dedupe(cases: list[dict], *, ignore_keys: tuple[str, ...] = ("case_id", "signal_id")) -> list[dict]:
    """Drop cases whose content (everything but ids) is byte-identical to an earlier one."""

    def _key(d: dict) -> str:
        def strip(v: object) -> object:
            if isinstance(v, dict):
                return {k: strip(x) for k, x in v.items() if k not in ignore_keys}
            return v

        return json.dumps(strip(d), sort_keys=True)

    seen: set[str] = set()
    out: list[dict] = []
    for c in cases:
        k = _key(c)
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    if len(out) < len(cases):
        logger.warning("dropped %d duplicate-content generated cases", len(cases) - len(out))
    return out


_REPO_SCENARIOS: tuple[str, ...] = (
    "A customer reports that a core workflow in this product is failing: {domain}",
    "Support needs the owner of a regression in this product: {domain}",
    "An upgrade caused unexpected behavior in this codebase: {domain}",
    "A performance issue appears under load in this product: {domain}",
    "Users cannot complete the primary workflow described here: {domain}",
    "A security fix is needed in the project matching this description: {domain}",
    "The {language} service matching this description needs a bug fix: {domain}",
    "A dependency update broke functionality in this product: {domain}",
    "A customer-facing error points to the project described as: {domain}",
    "An accessibility regression belongs to this product: {domain}",
    "A flaky integration test covers the product described here: {domain}",
    "An API compatibility issue affects this product: {domain}",
    "The deployment for this product started failing: {domain}",
    "A data-loss report concerns the project described here: {domain}",
    "A mobile browser regression affects this product: {domain}",
    "A reliability alert maps to the product described as: {domain}",
)


def build_repo_selection_cases(*, target: int = 110) -> list[dict]:
    from products.signals.eval.agentic.repos import REGISTRY  # noqa: PLC0415

    repositories = tuple(REGISTRY.values())
    cases: list[dict] = []
    for i in range(target):
        repo = repositories[i % len(repositories)]
        scenario = _REPO_SCENARIOS[(i // len(repositories)) % len(_REPO_SCENARIOS)]
        content = scenario.format(domain=repo.domain, language=repo.primary_language)
        cases.append(
            {
                "case_id": f"reposel_gen_{i:03d}_{repo.key}",
                "signal": {"signal_id": f"sig_{i:03d}", "content": content, "source_product": "conversations"},
                "expected_repository": repo.full_name,
            }
        )
    # A few null cases: ops/billing/legal requests no repo owns.
    for j, detail in enumerate(
        [
            "A customer disputes an invoice and wants a prorated refund escalated to their account manager.",
            "Sales asks for a custom enterprise contract and updated pricing terms for a prospect.",
            "Legal needs a copy of our signed DPA and sub-processor list for a security review.",
            "A user asks to change the billing email on their subscription and re-send the last receipt.",
        ]
    ):
        cases.append(
            {
                "case_id": f"reposel_gen_null_{j:02d}",
                "signal": {"signal_id": f"sig_null_{j}", "content": detail, "source_product": "zendesk"},
                "expect_null": True,
            }
        )
    return _dedupe(cases)


_RESEARCH_ANGLES: tuple[str, ...] = (
    "Investigate the recent trend and assess whether it is worth acting on.",
    "Compare affected cohorts and determine the likely customer impact.",
    "Verify its frequency in project data and recommend the next action.",
    "Check for a change around recent releases and summarize the evidence.",
    "Decide whether the available evidence supports prioritizing engineering work.",
)


def build_research_cases(*, target: int = 110) -> list[dict]:
    from products.signals.eval.agentic.project.manifest import DEFAULT_MANIFEST  # noqa: PLC0415

    cases: list[dict] = []
    grounded_target = max(0, target - len(_VERDICT_DETAILS))

    def append_grounded(prefix: str, names: tuple[str, ...], source_product: str, source_type: str) -> None:
        for entity_index, name in enumerate(names):
            tok = _case_token(name)
            if tok is None:
                continue
            for angle_index, angle in enumerate(_RESEARCH_ANGLES):
                if len(cases) >= grounded_target:
                    return
                cases.append(
                    {
                        "case_id": f"research_gen_{prefix}_{entity_index:03d}_{angle_index}_{tok}",
                        "signal": {
                            "signal_id": f"sig_{prefix}_{entity_index:03d}_{angle_index}",
                            "content": f"The synthetic eval project reports '{name}'. {angle}",
                            "source_product": source_product,
                            "source_type": source_type,
                        },
                        "expectation": {"expect_data_evidence": True, "summary_must_mention": [tok]},
                    }
                )

    append_grounded("err", DEFAULT_MANIFEST.error_names, "error_tracking", "issue_spiking")
    append_grounded("evt", DEFAULT_MANIFEST.event_names, "session_replay", "replay_vision")
    append_grounded("exp", DEFAULT_MANIFEST.experiment_names, "github", "issue_created")

    # 4) Templated source/verdict variety — synthetic, so only the stable dimensions are
    # asserted. One case per detail; repeats would pad the suite with verbatim duplicates.
    n_variety = min(max(0, target - len(cases)), len(_VERDICT_DETAILS))
    for i in range(n_variety):
        kind, detail = _VERDICT_DETAILS[i]
        tmpl = next(t for t in _VERDICT_TEMPLATES if t["kind"] == kind)
        tok = _case_token(detail)
        if tok is None:
            continue
        expectation: dict = {"summary_must_mention": [tok]}
        if kind == "vague":
            expectation["expected_actionability"] = ["requires_human_input", "not_actionable"]
        cases.append(
            {
                "case_id": f"research_gen_var_{i:03d}_{kind}",
                "signal": {
                    "signal_id": f"sig_var_{i:03d}",
                    "content": tmpl["text"].format(detail=detail),
                    "source_product": tmpl["source_product"],
                    "source_type": tmpl["source_type"],
                },
                "expectation": expectation,
            }
        )
    return _dedupe(cases)


# Auto-verifiable implementation task templates on a small, fast-cloning repo.
_IMPL_REPO = "posthog/posthog-python"


def build_implementation_cases(*, target: int = 110) -> list[dict]:
    cases: list[dict] = []
    archetypes = ("function", "constant", "newfile", "docstring_file")
    for i in range(target):
        arch = archetypes[i % len(archetypes)]
        tag = f"{i:03d}"
        if arch == "function":
            fn = f"eval_fn_{tag}"
            val = f"signals-eval-{tag}"
            prompt = (
                f"In `posthog/__init__.py`, add a top-level function `def {fn}() -> str:` that returns "
                f"the string '{val}'. Keep the change minimal and place it near the other top-level functions."
            )
            exp: dict[str, Any] = {
                "expected_file_substrings": ["__init__.py"],
                "expected_diff_keywords": [fn, val],
            }
        elif arch == "constant":
            const = f"EVAL_CONST_{tag}"
            val = f"signals-eval-{tag}"
            prompt = (
                f"In `posthog/__init__.py`, add a module-level constant `{const} = '{val}'` near the top of "
                f"the module. Keep the change minimal."
            )
            exp = {"expected_file_substrings": ["__init__.py"], "expected_diff_keywords": [const, val]}
        elif arch == "newfile":
            fname = f"eval_notes/note_{tag}.md"
            marker = f"signals-eval-marker-{tag}"
            prompt = (
                f"Create a new file `{fname}` containing exactly one line: '{marker}'. Create the directory "
                f"if needed. Do not modify any other files."
            )
            exp = {"expected_file_substrings": [f"note_{tag}"], "expected_diff_keywords": [marker]}
        else:  # docstring_file
            fname = f"posthog/eval_module_{tag}.py"
            fn = f"helper_{tag}"
            prompt = (
                f"Create a new file `{fname}` with a module docstring and a function "
                f"`def {fn}() -> int: return {i}`. Keep it minimal."
            )
            exp = {"expected_file_substrings": [f"eval_module_{tag}"], "expected_diff_keywords": [fn]}
        exp.update(
            {
                "forbidden_file_substrings": ["pnpm-lock", "package-lock", "yarn.lock", "poetry.lock"],
                "min_files_changed": 1,
                "max_files_changed": 2,
            }
        )
        cases.append(
            {"case_id": f"impl_gen_{tag}_{arch}", "repo": _IMPL_REPO, "issue_prompt": prompt, "expectation": exp}
        )
    return _dedupe(cases)
