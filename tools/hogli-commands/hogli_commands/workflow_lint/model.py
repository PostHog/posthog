"""Parsed model of `.github/workflows/*.yml`.

This is the deep module of the workflow_lint package: it hides every PyYAML
quirk and yields typed Workflow / Job / Step objects so individual checks can
ignore parsing details and just iterate.

Quirks hidden here:
- Top-level `on:` parses to a Python `True` key (PyYAML interprets `on` as the
  boolean literal). We normalize back to the original string/list/dict.
- `dorny/paths-filter` accepts `with.filters` either as a dict or as a YAML
  block-string; we parse the block-string form here so checks see one shape.
- Reusable workflow calls (jobs with `uses:` at the job level) have no steps
  and no `timeout-minutes` — surfaced as `is_reusable_call` so checks can skip
  cleanly.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PR_TRIGGERS = frozenset({"pull_request", "pull_request_target"})


class WorkflowParseError(Exception):
    """Raised when a workflow file fails to parse as valid YAML."""

    def __init__(self, path: Path, original: Exception) -> None:
        super().__init__(f"{path.name}: failed to parse YAML: {original}")
        self.path = path
        self.original = original


@dataclass(frozen=True, slots=True)
class Step:
    idx: int
    uses: str | None
    run: str | None
    with_: dict | None
    id_: str | None
    raw: dict

    @property
    def ref(self) -> str:
        """Human-readable step reference, e.g. ``step id 'install'`` or ``step[3]``."""
        return f"step id '{self.id_}'" if self.id_ else f"step[{self.idx}]"


@dataclass(frozen=True, slots=True)
class Job:
    name: str
    uses: str | None  # set when this job is a reusable-workflow call
    has_timeout: bool  # any value at the `timeout-minutes` key (int OR `${{ ... }}` expression)
    timeout_minutes: int | None  # the int value, or None if absent or expression
    steps: list[Step] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def is_reusable_call(self) -> bool:
        return self.uses is not None


@dataclass(frozen=True, slots=True)
class Workflow:
    path: Path
    name: str
    on: object  # str | list | dict — original form, with the True-key quirk normalized away
    concurrency: dict | str | None
    jobs: list[Job] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def is_pr_triggered(self) -> bool:
        return _matches_pr_trigger(self.on)


def _matches_pr_trigger(triggers: object) -> bool:
    if isinstance(triggers, str):
        return triggers in PR_TRIGGERS
    if isinstance(triggers, (list, dict)):
        return any(t in PR_TRIGGERS for t in triggers)
    return False


def _normalize_on(data: dict) -> object:
    # PyYAML parses the bare YAML key `on:` as the boolean literal `True`.
    # `safe_load` of a quoted "on" gives us the string. Either way, surface
    # the original triggers regardless of how they were typed.
    if True in data:
        return data[True]
    return data.get("on")


def parse_filters(raw: object) -> dict | None:
    """Parse `dorny/paths-filter` `with.filters`. Returns None for non-dict / external-path strings."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    # Single-line strings without a colon are external-file path refs (dorny supports those).
    if "\n" not in raw and ":" not in raw:
        return None
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _build_step(idx: int, raw: object) -> Step | None:
    if not isinstance(raw, dict):
        return None
    uses = raw.get("uses")
    run = raw.get("run")
    with_block = raw.get("with")
    step_id = raw.get("id")
    return Step(
        idx=idx,
        uses=uses if isinstance(uses, str) else None,
        run=run if isinstance(run, str) else None,
        with_=with_block if isinstance(with_block, dict) else None,
        id_=step_id if isinstance(step_id, str) else None,
        raw=raw,
    )


def _build_job(name: str, raw: object) -> Job | None:
    if not isinstance(raw, dict):
        return None
    uses = raw.get("uses")
    raw_steps = raw.get("steps")
    steps: list[Step] = []
    if isinstance(raw_steps, list):
        for idx, step_raw in enumerate(raw_steps):
            step = _build_step(idx, step_raw)
            if step is not None:
                steps.append(step)
    has_timeout = "timeout-minutes" in raw
    timeout = raw.get("timeout-minutes")
    return Job(
        name=name,
        uses=uses if isinstance(uses, str) else None,
        has_timeout=has_timeout,
        timeout_minutes=timeout if isinstance(timeout, int) else None,
        steps=steps,
        raw=raw,
    )


def _build_workflow(path: Path) -> Workflow | None:
    """Parse one workflow file. Returns None for non-mapping YAML (rare but legal)."""
    with open(path, encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise WorkflowParseError(path, exc) from exc
    if not isinstance(data, dict):
        return None

    raw_jobs = data.get("jobs")
    jobs: list[Job] = []
    if isinstance(raw_jobs, dict):
        for job_name, job_raw in raw_jobs.items():
            job = _build_job(str(job_name), job_raw)
            if job is not None:
                jobs.append(job)

    concurrency = data.get("concurrency")
    return Workflow(
        path=path,
        name=str(data.get("name") or path.name),
        on=_normalize_on(data),
        concurrency=concurrency if isinstance(concurrency, (dict, str)) else None,
        jobs=jobs,
        raw=data,
    )


def read_workflows(workflows_dir: Path, glob: str = "*.y*ml") -> Iterator[Workflow]:
    """Walk ``workflows_dir`` and yield parsed :class:`Workflow` objects."""
    for path in sorted(workflows_dir.glob(glob)):
        wf = _build_workflow(path)
        if wf is not None:
            yield wf


__all__ = [
    "Job",
    "PR_TRIGGERS",
    "Step",
    "Workflow",
    "WorkflowParseError",
    "parse_filters",
    "read_workflows",
]
