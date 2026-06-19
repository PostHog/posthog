"""Cache writes must not be able to land on a non-default branch ref.

A cache written on a PR/branch ref is scoped to that ref alone: no other branch
can read it, it evicts the shared default-branch cache, and it only ever serves
that one PR's re-runs before LRU eviction. Near the repo's 10 GB cache cap that
churns the useful master caches out.

A cache WRITE is one of:
  - actions/cache@         combined action; auto-saves every run in its post step
  - actions/cache/save@    explicit save
  - actions/setup-*@ with a truthy `cache:` input — auto-saves in a post step that
    can't be gated (gating the whole step would skip the toolchain on PRs)

A write is FINE when any of these hold:
  1. its workflow can't run on a branch ref at all — triggers are default-only
     (push to the default branch, schedule, workflow_run). ``workflow_dispatch``
     is treated as default-scoped on purpose: a cache write behind a *manual*
     dispatch on a branch is an explicit choice, not the silent PR/push pollution
     this rule guards against;
  2. the step ``if:`` gates it to the default branch — ``github.ref ==
     'refs/heads/<default>'``, ``ref_name == '<default>'``, or (only when the
     workflow's own ``push:`` trigger is default-branch-only) ``event_name ==
     'push'``;
  3. the cache key embeds a per-PR/branch/run id (e.g.
     ``github.event.pull_request.number``) — it's deliberately unique, not a
     shared cache that fragmented.

Scans ``.github/workflows/**`` and ``.github/actions/*/action.yml`` — cache
writes live in both (the shared ``pnpm-install`` action saves the store, and
un-gating it would leak from every workflow that uses it). Composite actions have
no triggers, so they run wherever called: condition 1 never applies to them.
"""

from __future__ import annotations

import yaml
from hogli.manifest import REPO_ROOT

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

DEFAULT_BRANCHES = ("master", "main")

# setup actions whose `cache:` input enables an ungatable post-save
SETUP_CACHE_ACTIONS = (
    "actions/setup-node",
    "actions/setup-python",
    "actions/setup-go",
    "actions/setup-java",
    "actions/setup-dotnet",
    "actions/setup-ruby",
)

# triggers whose runs can land on a non-default ref (workflow_dispatch is excluded
# on purpose — see module docstring, condition 1)
BRANCH_REF_TRIGGERS = frozenset({"pull_request", "pull_request_target", "merge_group", "workflow_call"})

# step `if:` substrings (whitespace-stripped) that pin a write to the default branch.
# Positive `==` only, so a negation like `github.ref != 'refs/heads/master'` (which runs
# on branches) isn't mistaken for a gate.
GATE_MARKERS = tuple(f"=='refs/heads/{b}'" for b in DEFAULT_BRANCHES) + tuple(
    f"ref_name=='{b}'" for b in DEFAULT_BRANCHES
)

# cache-key substrings that make the entry deliberately unique per ref/PR/run
PER_REF_KEY_MARKERS = (
    "github.event.pull_request.number",
    "github.event.number",
    "github.head_ref",
    "github.ref_name",
    "github.run_id",
)


def _triggers(on: object) -> dict:
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    if isinstance(on, dict):
        return on
    return {}


def _push_is_default_only(cfg: object) -> bool:
    # bare `push:` (no filter) runs on every branch push — can leak
    if not isinstance(cfg, dict):
        return False
    branches = cfg.get("branches")
    if branches:
        return all(b in DEFAULT_BRANCHES for b in branches)
    # push restricted to tags only (release pushes) — treat as default-scoped
    return bool(cfg.get("tags"))


def _can_run_on_branch_ref(on: object) -> bool:
    for name, cfg in _triggers(on).items():
        if name in BRANCH_REF_TRIGGERS:
            return True
        if name == "push" and not _push_is_default_only(cfg):
            return True
    return False


def _push_trigger_is_default_only(on: object) -> bool:
    """Whether `event_name == 'push'` is a real master-only gate here.

    True when the workflow has no push trigger, or its push is default-only.
    """
    triggers = _triggers(on)
    if "push" not in triggers:
        return True
    return _push_is_default_only(triggers["push"])


def _write_kind(step: dict) -> str | None:
    uses = str(step.get("uses") or "")
    if uses.startswith("actions/cache/restore@"):
        return None
    if uses.startswith("actions/cache/save@"):
        return "cache/save"
    if uses.startswith("actions/cache@"):
        return "cache (combined)"
    if uses.startswith(SETUP_CACHE_ACTIONS) and (step.get("with") or {}).get("cache"):
        return "setup auto-cache"
    return None


def _clause_pins_to_default(clause: str, push_is_default_only: bool) -> bool:
    if any(marker in clause for marker in GATE_MARKERS):
        return True
    # `event_name == 'push'` only pins to the default branch when push can't fire on a branch
    return push_is_default_only and "event_name=='push'" in clause


def _is_gated(step: dict, push_is_default_only: bool) -> bool:
    cond = str(step.get("if") or "").replace(" ", "")
    if not cond:
        return False
    # an `||` lets the step also run on the other operand, so EVERY alternative must
    # independently pin to the default branch — `master || event_name == 'pull_request'`
    # is not a gate, but `master || main` is
    return all(_clause_pins_to_default(part, push_is_default_only) for part in cond.split("||"))


def _key_is_per_ref(step: dict) -> bool:
    key = str((step.get("with") or {}).get("key") or "").replace(" ", "")
    return any(marker in key for marker in PER_REF_KEY_MARKERS)


def _violation_kind(step: dict, push_is_default_only: bool) -> str | None:
    """The write kind if this step is an unsafe cache write, else None."""
    kind = _write_kind(step)
    if kind is None:
        return None
    # setup-* auto-caches can't be gated; everything else is fine once gated or per-ref
    if kind != "setup auto-cache" and (_is_gated(step, push_is_default_only) or _key_is_per_ref(step)):
        return None
    return kind


def _composite_action_steps() -> list[tuple[str, dict]]:
    """(`relative path`, raw step) for every step in every composite action.

    Composite actions run wherever they're called, so all their cache writes must
    be gated regardless of the calling workflow.
    """
    actions_dir = REPO_ROOT / ".github" / "actions"
    out: list[tuple[str, dict]] = []
    if not actions_dir.exists():
        return out
    for path in sorted(actions_dir.glob("*/action.yml")):
        try:
            doc = yaml.safe_load(path.read_text())
        except yaml.YAMLError:
            continue
        runs = doc.get("runs") if isinstance(doc, dict) else None
        steps = runs.get("steps") if isinstance(runs, dict) else None
        if not isinstance(steps, list):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        out.extend((rel, step) for step in steps if isinstance(step, dict))
    return out


class CacheWriteGateCheck(WorkflowCheck):
    id = "WF006-cache-writes"
    label = "Cache write gating"
    description = "cache writes can't land on a branch ref (gated to the default branch, per-ref keyed, or in a default-only workflow)"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Make the cache write safe one of these ways:\n"
            "  - gate the save to the default branch: `if: github.ref == 'refs/heads/master'`\n"
            "  - replace a setup-* `cache:` input with an explicit restore + gated save\n"
            "    (see .github/actions/pnpm-install/action.yml)\n"
            "  - if the cache is meant to be per-PR, key it on github.event.pull_request.number"
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            if not _can_run_on_branch_ref(wf.on):
                continue
            push_default_only = _push_trigger_is_default_only(wf.on)
            for job in wf.jobs:
                for step in job.steps:
                    kind = _violation_kind(step.raw, push_default_only)
                    if kind is not None:
                        result.issues.append(
                            Issue(
                                workflow=wf.path.name,
                                message=f"{kind} can land on a non-default branch ref",
                                file=str(wf.path),
                                job=job.name,
                                step=str(step.raw.get("name") or step.ref),
                            )
                        )
        for rel, step in _composite_action_steps():
            kind = _violation_kind(step, push_is_default_only=False)
            if kind is not None:
                result.issues.append(
                    Issue(
                        workflow=rel,
                        message=f"{kind} can land on a non-default branch ref (composite action runs wherever it's called)",
                        file=rel,
                        step=str(step.get("name") or "<unnamed>"),
                    )
                )
        return result
