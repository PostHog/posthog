"""``dorny/paths-filter`` ``!``-patterns must be guarded by ``predicate-quantifier: 'every'``.

With dorny's default predicate-quantifier (``some``), each filter rule is
OR'd independently. A ``!path`` rule then matches every file NOT at that path
— silently inverting the intended exclusion. Using ``!`` patterns is only
safe when the step also sets ``predicate-quantifier: 'every'``.

Docs: https://github.com/dorny/paths-filter#advanced-options
"""

from __future__ import annotations

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow, parse_filters

DORNY_PREFIX = "dorny/paths-filter@"
DOCS_URL = "https://github.com/dorny/paths-filter#advanced-options"


class DornyNegationCheck(WorkflowCheck):
    id = "WF003-dorny-negation"
    label = "dorny negation guarded"
    description = "dorny/paths-filter '!' patterns require predicate-quantifier: 'every'"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Either remove the '!' patterns and use positive filters with count comparison, "
            "or add `predicate-quantifier: 'every'` to the step's `with:` block. "
            f"See {DOCS_URL}."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            for job in wf.jobs:
                for step in job.steps:
                    if step.uses is None or not step.uses.startswith(DORNY_PREFIX):
                        continue
                    if step.with_ is None:
                        continue
                    filters = parse_filters(step.with_.get("filters"))
                    if filters is None:
                        continue
                    quantifier = step.with_.get("predicate-quantifier")
                    if quantifier == "every":
                        continue
                    for filter_name, patterns in filters.items():
                        if not isinstance(patterns, list):
                            continue
                        for pattern in patterns:
                            if isinstance(pattern, str) and pattern.startswith("!"):
                                result.issues.append(
                                    Issue(
                                        workflow=wf.path.name,
                                        job=job.name,
                                        step=step.ref,
                                        message=(
                                            f"filter '{filter_name}' uses negation '{pattern}' without "
                                            "`predicate-quantifier: 'every'` — with the default 'some' "
                                            "quantifier, '!' rules match every file NOT at the path "
                                            f"(including unrelated changes). See {DOCS_URL}."
                                        ),
                                        file=str(wf.path),
                                    )
                                )
        return result
