"""Builders that turn the eval project's real data + templates into case dicts.

Each builder returns a list of JSON-serializable dicts (the loader in ``generated.py`` turns
them into typed Case objects and attaches scorers). Generation is deterministic (index-based,
no RNG) so regenerating the same project yields a stable, diffable dataset.

DB-backed builders (repo selection, research) require the local stack; the implementation
builder is pure templating. Run via the ``generate_eval_cases`` management command.
"""

from __future__ import annotations

import re

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


def _salient(name: str) -> str:
    toks = [t for t in re.findall(r"[A-Za-z]{3,}", name.lower()) if t not in _STOP]
    if toks:
        return max(toks, key=lambda t: len(t))
    fallback = re.findall(r"[A-Za-z]{2,}", name.lower())
    return fallback[0] if fallback else "signal"


def _stem(repo_name: str) -> str:
    """Normalized stem for grouping near-duplicate repos (tutoring/jstutoring, foo/foo-old)."""
    n = repo_name.lower()
    n = re.sub(r"^(js|ts|py|go|old|new|the)[-_]?", "", n)
    n = re.sub(r"[-_](old|new|v\d+|copy|fork|mirror|template|example|boilerplate|demo)$", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


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
    for r in rows:
        name = r["full_name"].split("/")[-1]
        by_stem.setdefault(_stem(name), []).append(r["full_name"])

    cases: list[dict] = []
    # Prefer described repos first (clearer signals), then the rest, for stable ordering.
    rows.sort(key=lambda r: (not (r["description"] or "").strip(), r["full_name"]))
    for i, r in enumerate(rows):
        if len(cases) >= target:
            break
        full = r["full_name"]
        name = full.split("/")[-1]
        desc = (r["description"] or "").strip()
        lang = r["primary_language"] or "software"
        accepted = sorted(set(by_stem.get(_stem(name), [full])))
        if desc:
            content = (
                f"A user reported a problem in one of our connected projects. The affected product is "
                f'best described as: "{desc}". They hit a bug in its core functionality and we need to '
                f"find the repository that owns this code."
            )
        else:
            content = (
                f"A bug was reported in our {lang} project known as '{name}'. Identify which connected "
                f"repository owns this code."
            )
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
    return cases


def build_research_cases(team_id: int, *, target: int = 110) -> list[dict]:
    from django.apps import apps  # noqa: PLC0415

    from posthog.clickhouse.client import sync_execute  # noqa: PLC0415
    from posthog.clickhouse.query_tagging import tag_queries  # noqa: PLC0415

    cases: list[dict] = []

    # 1) Data-grounded from real error-tracking issues (dedupe names).
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
            cases.append(
                {
                    "case_id": f"research_gen_err_{i:03d}_{_salient(name)}",
                    "signal": {
                        "signal_id": f"sig_err_{i:03d}",
                        "content": (
                            f"Error tracking shows a '{name}' issue. Customers are hitting it. Investigate the "
                            f"real impact via the project's data and assess whether it's worth acting on."
                        ),
                        "source_product": "error_tracking",
                        "source_type": "issue_spiking",
                    },
                    "expectation": {"expect_data_evidence": True, "summary_must_mention": [_salient(name)]},
                }
            )
    except Exception:
        pass

    # 2) Data-grounded from real top events.
    try:
        tag_queries(product="max_ai", feature="management_command")
        rows = sync_execute(
            "SELECT event, count() c FROM events WHERE team_id=%(t)s AND event NOT LIKE '$%%' "
            "GROUP BY event ORDER BY c DESC LIMIT 20",
            {"t": team_id},
        )
        for i, (event, _c) in enumerate(rows):
            tok = _salient(event)
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
        pass

    # 3) Data-grounded from real experiments.
    try:
        Experiment = apps.get_model("experiments", "Experiment")
        for i, name in enumerate(
            Experiment.objects.filter(team_id=team_id).values_list("name", flat=True).order_by("id")
        ):
            tok = _salient(name or "experiment")
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
        pass

    # 4) Templated source/verdict variety. These are synthetic (no real data/code), so the verdict
    # is genuinely variable — asserting a tight actionability/priority would just add noise. We assert
    # only the stable dimensions: the summary stays on-topic, and (for clearly-vague signals) the
    # agent must NOT call it immediately actionable. Relative quality is captured by the LLM judge.
    n_variety = max(0, target - len(cases))
    for i in range(n_variety):
        kind, detail = _VERDICT_DETAILS[i % len(_VERDICT_DETAILS)]
        tmpl = next(t for t in _VERDICT_TEMPLATES if t["kind"] == kind)
        tok = _salient(detail)
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
    return cases


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
    return cases
