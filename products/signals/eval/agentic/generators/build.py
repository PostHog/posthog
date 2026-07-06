"""Builders that turn the eval project's real data + templates into case dicts.

Each builder returns a list of JSON-serializable dicts (the loader in ``generated.py`` turns
them into typed Case objects and attaches scorers). Generation is deterministic (index-based,
no RNG) so regenerating the same project yields a stable, diffable dataset.

DB-backed builders (repo selection, research) require the local stack; the implementation
builder is pure templating. Run via the ``generate_eval_cases`` management command.
"""

from __future__ import annotations

import re
import json
import logging

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


def _stem(repo_name: str) -> str:
    """Normalized stem for grouping near-duplicate repos (tutoring/jstutoring, foo/foo-old)."""
    n = repo_name.lower()
    n = re.sub(r"^(js|ts|py|go|old|new|the)[-_]?", "", n)
    n = re.sub(r"[-_](old|new|v\d+|copy|fork|mirror|template|example|boilerplate|demo)$", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


# A description too short to discriminate the target repo makes the ground truth ambiguous.
_MIN_DESC_LEN = 25
# Name-embedding "known as 'X'" cases are trivially passable; keep only a handful as a sanity floor.
_MAX_NAME_ONLY_CASES = 8


def _usable_description(row: dict) -> str | None:
    desc = (row["description"] or "").strip()
    name = row["full_name"].split("/")[-1]
    if len(desc) < _MIN_DESC_LEN or desc.lower() == name.lower():
        return None
    return desc


def build_repo_selection_cases(team_id: int, *, target: int = 110) -> list[dict]:
    from posthog.models.integration import Integration  # noqa: PLC0415

    integration = Integration.objects.filter(team_id=team_id, kind="github").first()
    if integration is None:
        return []
    rows = list(
        integration.repository_cache_entries.filter(team_id=team_id, archived=False)
        .values("full_name", "description", "primary_language")
        .order_by("full_name")
    )
    # Group near-duplicate repos by stem so same-domain ambiguity is accepted, not penalized.
    by_stem: dict[str, list[str]] = {}
    # Repos sharing an identical description are mutually acceptable too — the signal only
    # carries the description, so any of them is a defensible pick.
    by_desc: dict[str, list[str]] = {}
    for r in rows:
        name = r["full_name"].split("/")[-1]
        by_stem.setdefault(_stem(name), []).append(r["full_name"])
        desc = _usable_description(r)
        if desc:
            by_desc.setdefault(desc.lower(), []).append(r["full_name"])

    cases: list[dict] = []
    # Prefer usably-described repos first (clearer signals), then the rest, for stable ordering.
    rows.sort(key=lambda r: (_usable_description(r) is None, r["full_name"]))
    name_only_count = 0
    for i, r in enumerate(rows):
        if len(cases) >= target:
            break
        full = r["full_name"]
        name = full.split("/")[-1]
        desc = _usable_description(r)
        lang = r["primary_language"] or "software"
        accepted_set = set(by_stem.get(_stem(name), [full]))
        if desc:
            accepted_set |= set(by_desc.get(desc.lower(), ()))
            content = (
                f"A user reported a problem in one of our connected projects. The affected product is "
                f'best described as: "{desc}". They hit a bug in its core functionality and we need to '
                f"find the repository that owns this code."
            )
        else:
            if name_only_count >= _MAX_NAME_ONLY_CASES:
                continue
            name_only_count += 1
            content = (
                f"A bug was reported in our {lang} project known as '{name}'. Identify which connected "
                f"repository owns this code."
            )
        accepted = sorted(accepted_set)
        cases.append(
            {
                "case_id": f"reposel_gen_{i:03d}_{_stem(name) or 'repo'}",
                "signal": {"signal_id": f"sig_{i:03d}", "content": content, "source_product": "conversations"},
                "expected_repository": accepted if len(accepted) > 1 else accepted[0],
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


def build_research_cases(team_id: int, *, target: int = 110) -> list[dict]:
    from django.apps import apps  # noqa: PLC0415

    from posthog.clickhouse.client import sync_execute  # noqa: PLC0415
    from posthog.clickhouse.query_tagging import tag_queries  # noqa: PLC0415

    cases: list[dict] = []
    section_counts: dict[str, int] = {}
    # A keyword reused across cases can't discriminate which case's summary passed.
    used_tokens: set[str] = set()

    def _fresh_token(name: str) -> str | None:
        tok = _case_token(name)
        if tok is None or tok in used_tokens:
            return None
        used_tokens.add(tok)
        return tok

    # 1) Data-grounded from real error-tracking issues (dedupe names).
    section_start = len(cases)
    try:
        from products.error_tracking.backend.models import ErrorTrackingIssue  # noqa: PLC0415

        names: list[str] = []
        seen: set[str] = set()
        for n in (
            ErrorTrackingIssue.objects.filter(team_id=team_id)
            .exclude(name__isnull=True)
            .values_list("name", flat=True)
            .order_by("name")
        ):
            key = (n or "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                names.append(n)
        for i, name in enumerate(names):
            tok = _fresh_token(name)
            if tok is None:
                continue
            cases.append(
                {
                    "case_id": f"research_gen_err_{i:03d}_{tok}",
                    "signal": {
                        "signal_id": f"sig_err_{i:03d}",
                        "content": (
                            f"Error tracking shows a '{name}' issue. Customers are hitting it. Investigate the "
                            f"real impact via the project's data and assess whether it's worth acting on."
                        ),
                        "source_product": "error_tracking",
                        "source_type": "issue_spiking",
                    },
                    "expectation": {"expect_data_evidence": True, "summary_must_mention": [tok]},
                }
            )
    except Exception:
        logger.exception("research case generation: error-tracking section failed; its cases were lost")
    section_counts["error_tracking"] = len(cases) - section_start

    # 2) Data-grounded from real top events.
    section_start = len(cases)
    try:
        tag_queries(product="max_ai", feature="management_command")
        rows = sync_execute(
            "SELECT event, count() c FROM events WHERE team_id=%(t)s AND event NOT LIKE '$%%' "
            "GROUP BY event ORDER BY c DESC LIMIT 20",
            {"t": team_id},
        )
        for i, (event, _c) in enumerate(rows):
            tok = _fresh_token(event)
            if tok is None:
                continue
            cases.append(
                {
                    "case_id": f"research_gen_evt_{i:03d}_{tok}",
                    "signal": {
                        "signal_id": f"sig_evt_{i:03d}",
                        "content": (
                            f"We suspect the '{event}' behavior has shifted recently. Check the trend in the "
                            f"project's analytics and assess whether there's a real change worth acting on."
                        ),
                        "source_product": "session_replay",
                        "source_type": "replay_vision",
                    },
                    "expectation": {"expect_data_evidence": True, "summary_must_mention": [tok]},
                }
            )
    except Exception:
        logger.exception("research case generation: top-events section failed; its cases were lost")
    section_counts["events"] = len(cases) - section_start

    # 3) Data-grounded from real experiments.
    section_start = len(cases)
    try:
        Experiment = apps.get_model("experiments", "Experiment")
        for i, name in enumerate(
            Experiment.objects.filter(team_id=team_id).values_list("name", flat=True).order_by("id")
        ):
            tok = _fresh_token(name or "")
            if tok is None:
                continue
            cases.append(
                {
                    "case_id": f"research_gen_exp_{i:03d}_{tok}",
                    "signal": {
                        "signal_id": f"sig_exp_{i:03d}",
                        "content": (
                            f"A teammate flagged that the '{name}' experiment may be inconclusive or negative. "
                            f"Read the experiment results in the project and recommend ship / iterate / roll back."
                        ),
                        "source_product": "github",
                        "source_type": "issue_created",
                    },
                    "expectation": {"expect_data_evidence": True, "summary_must_mention": [tok]},
                }
            )
    except Exception:
        logger.exception("research case generation: experiments section failed; its cases were lost")
    section_counts["experiments"] = len(cases) - section_start

    logger.info("research case generation: data-grounded section counts %s", section_counts)
    if not any(section_counts.values()):
        raise RuntimeError(
            "research case generation produced zero data-grounded cases across all sections "
            f"({section_counts}); the stack/project data is broken — a purely-templated dataset "
            "would silently lose the live suite's data-grounded coverage"
        )

    # 4) Templated source/verdict variety. These are synthetic (no real data/code), so the verdict
    # is genuinely variable — asserting a tight actionability/priority would just add noise. We assert
    # only the stable dimensions: the summary stays on-topic, and (for clearly-vague signals) the
    # agent must NOT call it immediately actionable. Relative quality is captured by the LLM judge.
    # Capped at one case per detail: repeating details pads the suite with verbatim duplicates.
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
            exp = {"expected_file_substrings": ["__init__.py"], "expected_diff_keywords": [fn, val]}
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
