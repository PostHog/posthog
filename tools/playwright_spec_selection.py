#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Affected-only Playwright E2E spec selection.

Maps a PR's changed files to the Playwright specs they could affect, so CI can
run a subset on incremental `synchronize` pushes to ready PRs instead of the
full suite. Wired into `.github/workflows/ci-e2e-playwright.yml`; the map lives
in `tools/playwright_area_map.json`.

Trust model (deliberately different from the backend snob selector, which
skips): this selector is FAIL-CLOSED per file — any changed file not explicitly
mapped forces the FULL suite — and the workflow falls open to the full suite on
any selector error. Over-selection silently drops coverage, so the only safe
default is "run everything". A selection miss that slips through is caught by
the post-merge full run on master (the backstop).

Two carve-outs soften fail-closed where the full suite provably adds nothing:

- `ignore`: paths that cannot affect the app under test (docs, agent
  instructions, lint rules, workflows for other suites) contribute nothing to
  selection instead of forcing a full run. `force_full` outranks `ignore`, and
  a diff where EVERY file is ignored still falls closed to a full run (category
  `all_ignored`) — running nothing is a trust-model change this selector
  deliberately doesn't make; the category exists to measure how much a skip
  mode would save before anyone builds it.
- `scenes_smoke_only` + `smoke_subset`: a scene listed here declares it has NO
  direct e2e coverage — no spec navigates to it, so the full suite wouldn't
  exercise it either. Changes there run the cheap `smoke_subset` (app boots,
  auth works) instead of everything. A mapping in `scenes` outranks the
  smoke-only list; writing a real spec for the scene means moving it to
  `scenes`.

Emits a single JSON object to stdout:

    {
      "mode": "selected" | "full",
      "spec_files": [...],              # [] when mode == "full"
      "full_run_reasons": [...],        # why a full run was chosen (empty when selected)
      "full_run_reason_category": "",   # low-cardinality category (empty when selected)
      "full_run_reason_detail": "",     # low-cardinality trigger (the pattern/scene/product/dir)
      "changed_files": [...],
      "changed_file_count": N,
      "selected_count": M,
      "total_spec_count": T
    }

`full_run_reason_detail` names the specific thing that forced the full run, normalized
to stay low-cardinality so it groups cleanly in analytics: the matched `force_full`
pattern, the unmapped scene/product name, or the offending file's directory prefix
(for `unmapped_path`). It's what tells you which map gap to close next.
"""

from __future__ import annotations

import re
import sys
import json
import argparse
import traceback
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = Path(__file__).with_name("playwright_area_map.json")

# Above this many changed files the diff is too broad to narrow safely -> full run.
MAX_CHANGED_FILES = 100

# The two roots Playwright discovers specs from (see playwright/playwright.config.ts testMatch).
SPEC_GLOBS = ("playwright/e2e/**/*.spec.ts", "products/*/frontend/e2e/**/*.spec.ts")

_PRODUCT_FRONTEND_RE = re.compile(r"^products/([^/]+)/frontend/")
_SCENE_RE = re.compile(r"^frontend/src/scenes/([^/]+)/")

# How many leading path segments to keep when normalizing an unmapped file to a
# directory prefix — enough to point at the area to map, bounded so cardinality stays low.
_DETAIL_PREFIX_SEGMENTS = 3


def _dir_prefix(path: str) -> str:
    """The file's directory, capped to the first few segments, as a low-cardinality label."""
    parts = path.split("/")[:-1]
    if not parts:
        return "./"
    return "/".join(parts[:_DETAIL_PREFIX_SEGMENTS]) + "/"


class MapError(Exception):
    """A map entry doesn't resolve to a real spec on disk — treat as untrustworthy."""


def _compile_glob(pattern: str) -> re.Pattern[str]:
    """Compile a gitignore-style glob: `*` stays within a path segment, `**` spans segments."""
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + r"\Z")


def discover_specs(root: Path) -> set[str]:
    """All spec files on disk, as repo-relative POSIX paths."""
    found: set[str] = set()
    for glob in SPEC_GLOBS:
        for path in root.glob(glob):
            found.add(path.relative_to(root).as_posix())
    return found


def expand_target(target: str, all_specs: set[str]) -> set[str]:
    """Resolve a map target (dir prefix, glob, or exact file) to concrete specs on disk."""
    if target.endswith("/"):
        matches = {s for s in all_specs if s.startswith(target)}
    elif "*" in target or "?" in target:
        rx = _compile_glob(target)
        matches = {s for s in all_specs if rx.match(s)}
    else:
        matches = {target} if target in all_specs else set()
    if not matches:
        raise MapError(f"map target {target!r} resolved to no specs on disk")
    return matches


def load_map(path: Path) -> dict:
    return json.loads(path.read_text())


def _result(
    mode: str,
    spec_files: list[str],
    reasons: list[str],
    changed_files: list[str],
    total_spec_count: int,
    reason_category: str = "",
    reason_detail: str = "",
) -> dict:
    return {
        "mode": mode,
        "spec_files": spec_files,
        "full_run_reasons": reasons,
        # Low-cardinality labels for analytics grouping (the reasons carry file paths).
        "full_run_reason_category": reason_category,
        "full_run_reason_detail": reason_detail,
        "changed_files": changed_files,
        "changed_file_count": len(changed_files),
        "selected_count": len(spec_files),
        "total_spec_count": total_spec_count,
    }


@dataclass(frozen=True)
class FullRun:
    """A changed file that forces the full suite: the human reason plus its analytics labels."""

    reason: str
    category: str
    detail: str = ""


# One file's contribution to the selection: a full run, the specs it selects, or
# `None` when the file is ignore-listed and contributes nothing.
FileOutcome = FullRun | set[str] | None


class AreaMap:
    """The area map with every glob compiled once, and one classifier per rule kind."""

    def __init__(self, area_map: dict, all_specs: set[str]) -> None:
        self._all_specs = all_specs
        self._force_full = [(p, _compile_glob(p)) for p in area_map.get("force_full", [])]
        self._ignore = [_compile_glob(p) for p in area_map.get("ignore", [])]
        self._products = area_map.get("products", {})
        self._scenes = area_map.get("scenes", {})
        self._scenes_smoke_only = set(area_map.get("scenes_smoke_only", []))
        self._smoke_subset = area_map.get("smoke_subset", [])
        self._explicit = [(p, _compile_glob(p), targets) for p, targets in area_map.get("explicit", {}).items()]

    def _expand(self, targets: Iterable[str]) -> set[str]:
        specs: set[str] = set()
        for target in targets:
            specs |= expand_target(target, self._all_specs)
        return specs

    def force_full_pattern(self, path: str) -> str | None:
        for pattern, rx in self._force_full:
            if rx.match(path):
                return pattern
        return None

    def is_ignored(self, path: str) -> bool:
        return any(rx.match(path) for rx in self._ignore)

    def explicit_specs(self, path: str) -> set[str] | None:
        """The specs an explicit path rule maps this file to, or None when no rule matches."""
        for _pattern, rx, targets in self._explicit:
            if rx.match(path):
                return self._expand(targets)
        return None

    def product_specs(self, path: str) -> FileOutcome:
        """Product-owned frontend -> that product's specs (or an explicit rule for products
        whose behavior is exercised by top-level specs). None when not product frontend code."""
        match = _PRODUCT_FRONTEND_RE.match(path)
        if not match:
            return None
        name = match.group(1)
        if name in self._products:
            return self._expand(self._products[name])
        explicit = self.explicit_specs(path)
        if explicit is not None:
            return explicit
        return FullRun(f"{path}: product '{name}' has no spec mapping", "unmapped_product", name)

    def scene_specs(self, path: str) -> FileOutcome:
        """Frontend scene -> mapped specs, or the smoke subset for scenes that declared they
        have no direct e2e coverage (the full suite wouldn't exercise them either, so it only
        buys the boot/auth smoke signal). None when not a scene file."""
        match = _SCENE_RE.match(path)
        if not match:
            return None
        area = match.group(1)
        if area in self._scenes:
            return self._expand(self._scenes[area])
        if area in self._scenes_smoke_only:
            return self._expand(self._smoke_subset)
        return FullRun(f"{path}: scene '{area}' has no spec mapping", "unmapped_scene", area)

    def classify(self, path: str) -> FileOutcome:
        """The ordered decision flow for one changed file."""
        # 1. Shared infra / backend / unattributable code -> full (highest priority,
        #    deliberately above `ignore` so an ignore glob can never swallow a
        #    force-full path like the playwright workflow file itself).
        pattern = self.force_full_pattern(path)
        if pattern is not None:
            return FullRun(f"{path} matches force-full pattern '{pattern}'", "force_full", pattern)

        # 2. Provably inert paths contribute nothing (and don't force full).
        if self.is_ignored(path):
            return None

        # 3. Product-owned frontend.
        product = self.product_specs(path)
        if product is not None:
            return product

        # 4. Frontend scene.
        scene = self.scene_specs(path)
        if scene is not None:
            return scene

        # 5. Explicit path rules.
        explicit = self.explicit_specs(path)
        if explicit is not None:
            return explicit

        # 6. A directly-edited spec runs itself.
        if path in self._all_specs:
            return {path}

        # 7. Anything unrecognized -> full (fail closed).
        return FullRun(f"{path}: unmapped path", "unmapped_path", _dir_prefix(path))


def select(changed_files: list[str], area_map: dict, all_specs: set[str]) -> dict:
    """Pure selection: changed files + map + on-disk specs -> a full/selected decision."""
    total = len(all_specs)

    def full(reason: str, category: str, detail: str = "") -> dict:
        return _result("full", [], [reason], changed_files, total, category, detail)

    if not changed_files:
        return full("empty diff (defensive full run)", "empty_diff")
    if len(changed_files) > MAX_CHANGED_FILES:
        return full(f"{len(changed_files)} changed files exceed the {MAX_CHANGED_FILES} ceiling", "over_ceiling")

    rules = AreaMap(area_map, all_specs)
    selected: set[str] = set()
    ignored_count = 0
    for f in changed_files:
        outcome = rules.classify(f)
        if isinstance(outcome, FullRun):
            return full(outcome.reason, outcome.category, outcome.detail)
        if outcome is None:
            ignored_count += 1
            continue
        selected |= outcome

    # Belt-and-suspenders: a directly-edited spec always runs even if its area also mapped.
    selected |= {f for f in changed_files if f in all_specs}

    if not selected:
        if ignored_count == len(changed_files):
            return full(
                f"all {ignored_count} changed files are ignore-listed (full run until a skip mode exists)",
                "all_ignored",
            )
        return full("no specs selected (defensive full run)", "no_specs")
    return _result("selected", sorted(selected), [], changed_files, total)


def _error_result(detail: str, changed_files: list[str] | None = None, total_spec_count: int = 0) -> dict:
    """The selector itself failed. Fall closed to a full run, but record why so the
    failure is visible in telemetry instead of surfacing as an opaque empty output.

    Carry through whatever counts were already known when the failure hit, so the
    telemetry doesn't report false zeroes for inputs we'd successfully computed."""
    return _result(
        "full", [], [f"selector error: {detail}"], changed_files or [], total_spec_count, "selector_error", detail
    )


def changed_files_from_git(base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def write_summary(summary_path: Path, result: dict) -> None:
    lines = ["## Playwright spec selection", ""]
    if result["mode"] == "selected":
        lines.append(
            f"**Selected {result['selected_count']} of {result['total_spec_count']} specs** "
            f"from {result['changed_file_count']} changed files:"
        )
        lines.append("")
        lines += [f"- `{s}`" for s in result["spec_files"]]
    else:
        reason = result["full_run_reasons"][0] if result["full_run_reasons"] else "unknown"
        lines.append(f"**Full run** — {reason}")
    lines.append("")
    lines.append("> A selection miss is caught by the post-merge full run on master (the backstop).")
    lines.append("")
    with summary_path.open("a") as fh:
        fh.write("\n".join(lines) + "\n")


def _compute_result(args: argparse.Namespace) -> dict:
    """Run the selection, falling closed to a categorized full run on any failure.

    Each step is tagged separately so telemetry points at the real cause — a git
    environment failure reads as ``git_diff_failed``, not ``map_load_failed`` — and
    carries whatever counts were known by the time the failure hit. The category is
    the low-cardinality bucket; the traceback (git's captured stderr, the unresolved
    map target, the unforeseen bug) is printed to stderr so the CI step log keeps the
    specific cause a category alone can't carry."""
    try:
        area_map = load_map(Path(args.map))
        all_specs = discover_specs(REPO_ROOT)
    except (OSError, ValueError):
        traceback.print_exc(file=sys.stderr)
        return _error_result("map_load_failed")

    try:
        changed = changed_files_from_git(args.base_ref)
    except (subprocess.CalledProcessError, OSError):
        traceback.print_exc(file=sys.stderr)
        return _error_result("git_diff_failed", total_spec_count=len(all_specs))

    try:
        return select(changed, area_map, all_specs)
    except MapError:
        traceback.print_exc(file=sys.stderr)
        return _error_result("map_target_unresolved", changed, len(all_specs))
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return _error_result("unexpected_error", changed, len(all_specs))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True, help="Base ref to diff against, e.g. origin/master")
    parser.add_argument("--map", default=str(MAP_PATH), help="Path to the area map JSON")
    parser.add_argument("--summary-path", default="", help="Append a Markdown summary here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON output")
    args = parser.parse_args()

    result = _compute_result(args)

    if args.summary_path:
        write_summary(Path(args.summary_path), result)

    sys.stdout.write(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
