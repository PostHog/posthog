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
import subprocess
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
        return path
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


def select(changed_files: list[str], area_map: dict, all_specs: set[str]) -> dict:
    """Pure selection: changed files + map + on-disk specs -> a full/selected decision."""
    total = len(all_specs)

    def full(reason: str, category: str, detail: str = "") -> dict:
        return _result("full", [], [reason], changed_files, total, category, detail)

    if not changed_files:
        return full("empty diff (defensive full run)", "empty_diff")
    if len(changed_files) > MAX_CHANGED_FILES:
        return full(f"{len(changed_files)} changed files exceed the {MAX_CHANGED_FILES} ceiling", "over_ceiling")

    force_full = [(p, _compile_glob(p)) for p in area_map.get("force_full", [])]
    products = area_map.get("products", {})
    scenes = area_map.get("scenes", {})
    explicit = [(p, _compile_glob(p), targets) for p, targets in area_map.get("explicit", {}).items()]

    def explicit_match(path: str, selected: set[str]) -> bool:
        for _pat, rx, targets in explicit:
            if rx.match(path):
                for t in targets:
                    selected |= expand_target(t, all_specs)
                return True
        return False

    selected: set[str] = set()
    for f in changed_files:
        # 1. Shared infra / backend / unattributable code -> full (highest priority).
        for pat, rx in force_full:
            if rx.match(f):
                return full(f"{f} matches force-full pattern '{pat}'", "force_full", pat)

        # 2. Product-owned frontend -> that product's specs (or an explicit rule for
        #    products whose behavior is exercised by top-level specs).
        pm = _PRODUCT_FRONTEND_RE.match(f)
        if pm:
            name = pm.group(1)
            if name in products:
                for t in products[name]:
                    selected |= expand_target(t, all_specs)
                continue
            if explicit_match(f, selected):
                continue
            return full(f"{f}: product '{name}' has no spec mapping", "unmapped_product", name)

        # 3. Frontend scene -> mapped specs.
        sm = _SCENE_RE.match(f)
        if sm:
            area = sm.group(1)
            if area in scenes:
                for t in scenes[area]:
                    selected |= expand_target(t, all_specs)
                continue
            return full(f"{f}: scene '{area}' has no spec mapping", "unmapped_scene", area)

        # 4. Explicit path rules.
        if explicit_match(f, selected):
            continue

        # 5. A directly-edited spec runs itself.
        if f in all_specs:
            selected.add(f)
            continue

        # 6. Anything unrecognized -> full (fail closed).
        return full(f"{f}: unmapped path", "unmapped_path", _dir_prefix(f))

    # Belt-and-suspenders: a directly-edited spec always runs even if its area also mapped.
    selected |= {f for f in changed_files if f in all_specs}

    if not selected:
        return full("no specs selected (defensive full run)", "no_specs")
    return _result("selected", sorted(selected), [], changed_files, total)


def _error_result(detail: str) -> dict:
    """The selector itself failed. Fall closed to a full run, but record why so the
    failure is visible in telemetry instead of surfacing as an opaque empty output."""
    return _result("full", [], [f"selector error: {detail}"], [], 0, "selector_error", detail)


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True, help="Base ref to diff against, e.g. origin/master")
    parser.add_argument("--map", default=str(MAP_PATH), help="Path to the area map JSON")
    parser.add_argument("--summary-path", default="", help="Append a Markdown summary here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON output")
    args = parser.parse_args()

    # Fall closed to a full run on any failure, tagging the cause so selector_error
    # runs are diagnosable (a stale map target, a git failure) rather than opaque.
    try:
        area_map = load_map(Path(args.map))
        all_specs = discover_specs(REPO_ROOT)
        changed = changed_files_from_git(args.base_ref)
        result = select(changed, area_map, all_specs)
    except subprocess.CalledProcessError:
        result = _error_result("git_diff_failed")
    except MapError:
        result = _error_result("map_target_unresolved")
    except (OSError, ValueError):
        result = _error_result("map_load_failed")
    except Exception:
        result = _error_result("unexpected_error")

    if args.summary_path:
        write_summary(Path(args.summary_path), result)

    sys.stdout.write(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
