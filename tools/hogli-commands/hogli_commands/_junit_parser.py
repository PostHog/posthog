"""Lean JUnit XML parser for the `hogli test-timings:*` commands.

Deliberately separate from `.github/scripts/report_test_timings.py`: that
script runs as a PEP 723 `uv run --script` with its own inline dep block, so
cross-runtime sharing would require sys.path hacks. The duplication is
~100 LOC and bounded; the runtimes never share modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET


@dataclass(frozen=True)
class TestCase:
    nodeid: str
    classname: str
    name: str
    duration: float
    outcome: str  # passed | failed | error | skipped | rerun_passed
    attempts: int


@dataclass(frozen=True)
class Shard:
    artifact_name: str  # e.g. "junit-results-backend-core-29"
    suite: str
    segment: str
    group: int | None
    junit_filename: str
    wall_seconds: float
    tests: tuple[TestCase, ...]

    @property
    def testcase_seconds(self) -> float:
        return sum(t.duration for t in self.tests)

    @property
    def overhead_seconds(self) -> float:
        return max(0.0, self.wall_seconds - self.testcase_seconds)

    @property
    def label(self) -> str:
        return f"{self.segment}-{self.group}" if self.group is not None else self.segment


def parse_artifact_dir_name(name: str) -> tuple[str, str, int | None]:
    """`junit-results-backend-core-29` -> ("backend", "core", 29)."""
    suffix = name.removeprefix("junit-results-")
    parts = suffix.split("-")
    group = int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() else None
    name_parts = parts[:-1] if group is not None else parts
    if not name_parts:
        return "", "", group
    if name_parts[0] == "backend" and len(name_parts) > 1:
        return "backend", "-".join(name_parts[1:]), group
    joined = "-".join(name_parts)
    return joined, joined, group


def _classify_testcase(testcase: Any) -> tuple[str, int]:
    """Return (outcome, attempts). pytest-rerunfailures emits prior attempts
    as `<rerunFailure>` / `<rerunError>` siblings before the final outcome."""
    rerun_count = 0
    final: str | None = None
    for child in testcase:
        tag = child.tag
        if tag.startswith("rerun"):
            rerun_count += 1
        elif tag in ("failure", "error", "skipped") and final is None:
            final = "failed" if tag == "failure" else tag
    if final is None:
        final = "rerun_passed" if rerun_count else "passed"
    return final, 1 + rerun_count


def _to_nodeid(classname: str, name: str) -> str:
    return f"{classname.replace('.', '/')}::{name}" if classname else name


def parse_shard(xml_path: Path, artifact_name: str) -> Shard | None:
    """Parse one `junit*.xml`. Returns None on malformed input."""
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return None
    suite_elem = root if root.tag == "testsuite" else root.find("testsuite")
    if suite_elem is None:
        return None
    try:
        wall = float(suite_elem.get("time", "0"))
    except ValueError:
        wall = 0.0

    suite, segment, group = parse_artifact_dir_name(artifact_name)
    tests: list[TestCase] = []
    for tc in suite_elem.iter("testcase"):
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        outcome, attempts = _classify_testcase(tc)
        try:
            duration = float(tc.get("time", "0"))
        except ValueError:
            duration = 0.0
        tests.append(
            TestCase(
                nodeid=_to_nodeid(classname, name),
                classname=classname,
                name=name,
                duration=duration,
                outcome=outcome,
                attempts=attempts,
            )
        )
    return Shard(
        artifact_name=artifact_name,
        suite=suite,
        segment=segment,
        group=group,
        junit_filename=xml_path.name,
        wall_seconds=wall,
        tests=tuple(tests),
    )


def collect_shards(artifacts_root: Path) -> list[Shard]:
    """Walk `<artifacts_root>/junit-results-*/junit*.xml` -> list[Shard].

    Falls through to the root itself if no subdirectories are present
    (single-shard / locally-staged case).
    """
    if not artifacts_root.exists():
        return []
    subdirs = sorted(d for d in artifacts_root.iterdir() if d.is_dir())
    artifact_dirs = subdirs if subdirs else [artifacts_root]
    shards: list[Shard] = []
    for d in artifact_dirs:
        for xml_path in sorted(d.rglob("junit*.xml")):
            shard = parse_shard(xml_path, d.name)
            if shard is not None:
                shards.append(shard)
    return shards


def per_test_durations(shards: list[Shard], *, segment: str | None = None) -> dict[str, float]:
    """Collapse shards into a single nodeid -> duration map.

    Skipped tests are dropped. When the same nodeid appears in multiple
    shards (parametrized tests sharded on params share a base nodeid in
    rare cases), the max duration wins so the slow case stays visible.
    """
    out: dict[str, float] = {}
    for s in shards:
        if segment is not None and s.segment != segment:
            continue
        for t in s.tests:
            if t.outcome == "skipped":
                continue
            prev = out.get(t.nodeid)
            if prev is None or t.duration > prev:
                out[t.nodeid] = t.duration
    return out
