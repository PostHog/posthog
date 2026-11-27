#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "defusedxml>=0.7.1",
# ]
# ///
"""Compare test selection against actual JUnit failures to produce a verdict.

Evaluates whether the shadow test selector would have caught the tests
that actually failed in CI. Outputs a JSON verdict suitable for batch
collection across PRs.
"""

from __future__ import annotations

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Any

from defusedxml import ElementTree


def classname_to_filepath(classname: str) -> str:
    """Map a JUnit classname to a Python file path.

    Split on '.', take parts until hitting one that starts uppercase,
    join with '/', append '.py'.

    Example:
        posthog.api.test.test_web_experiment.TestWebExperiment
        -> posthog/api/test/test_web_experiment.py
    """
    parts = classname.split(".")
    file_parts: list[str] = []
    for part in parts:
        if part and part[0].isupper():
            break
        file_parts.append(part)
    if not file_parts:
        return classname + ".py"
    return "/".join(file_parts) + ".py"


def parse_junit_failures(junit_dir: Path) -> tuple[list[str], int, int]:
    """Parse all JUnit XML files and return (failed_test_files, total_tests_run, xml_files_seen)."""
    failed_files: set[str] = set()
    total_tests = 0
    xml_files_seen = 0

    if not junit_dir.exists():
        return [], 0, 0

    for xml_file in sorted(junit_dir.rglob("*.xml")):
        xml_files_seen += 1
        try:
            tree = ElementTree.parse(xml_file)
        except ElementTree.ParseError:
            continue

        root = tree.getroot()

        # Handle both <testsuites> and <testsuite> as root
        if root.tag == "testsuites":
            suites = root.findall("testsuite")
        elif root.tag == "testsuite":
            suites = [root]
        else:
            continue

        # Use ".//testcase" so nested <testsuite> elements (e.g. pytest-xdist,
        # Gradle) are not silently skipped.
        for suite in suites:
            for testcase in suite.findall(".//testcase"):
                total_tests += 1
                has_failure = testcase.find("failure") is not None
                has_error = testcase.find("error") is not None
                if has_failure or has_error:
                    classname = testcase.get("classname", "")
                    if classname:
                        failed_files.add(classname_to_filepath(classname))

    return sorted(failed_files), total_tests, xml_files_seen


def compute_verdict(
    selection_path: Path,
    junit_dir: Path,
) -> dict[str, object]:
    """Build the verdict JSON comparing selection against actual failures."""
    with open(selection_path) as f:
        selection = json.load(f)

    failed_test_files, total_tests_run, xml_files_seen = parse_junit_failures(junit_dir)

    combined = selection.get("combined", {})
    selected_tests: list[str] = combined.get("tests", [])
    selected_set = set(selected_tests)

    ast_data = selection.get("ast", {})
    full_run_reasons: list[str] = ast_data.get("full_run_reasons", [])
    full_run_triggered = len(full_run_reasons) > 0

    # No JUnit XMLs means we don't actually know what happened — the upstream
    # artifact upload may have failed or the job may have run before tests
    # finished. Emit "unknown" rather than the misleading "success" we'd
    # otherwise infer from "0 failures observed".
    if xml_files_seen == 0:
        conclusion = "unknown"
        recall: float | None = None
        caught: list[str] = []
        missed: list[str] = []
    elif not failed_test_files:
        conclusion = "success"
        recall = None
        caught = []
        missed = []
    elif full_run_triggered:
        # Selector explicitly opted into running the whole suite, so every
        # failure would have been executed. Recording these as "missed"
        # against `combined.tests` would skew the recall metric.
        conclusion = "failure"
        caught = list(failed_test_files)
        missed = []
        recall = 1.0
    else:
        conclusion = "failure"
        caught = sorted(f for f in failed_test_files if f in selected_set)
        missed = sorted(f for f in failed_test_files if f not in selected_set)
        recall = len(caught) / len(failed_test_files)

    pr = os.environ.get("PR_NUMBER", "")
    sha = os.environ.get("PR_SHA", "")
    branch = os.environ.get("PR_BRANCH", "")

    return {
        "pr": pr,
        "sha": sha,
        "branch": branch,
        "backend_conclusion": conclusion,
        "junit_xml_files_seen": xml_files_seen,
        "total_tests_run": total_tests_run,
        "failure_count": len(failed_test_files),
        "failed_test_files": failed_test_files,
        "selected_test_count": len(selected_tests),
        "caught": caught,
        "missed": missed,
        "recall": recall,
        "full_run_triggered": full_run_triggered,
        "full_run_reasons": full_run_reasons,
    }


EVENT_MISSED_FILES_LIMIT = 20
EVENT_FULL_RUN_REASONS_LIMIT = 5


def event_properties(
    verdict: dict[str, Any],
    *,
    pr_number: int | None,
    pr_draft: bool | None,
    merge_queue: bool,
    branch: str,
    sha: str,
    run_id: str,
) -> dict[str, object]:
    missed: list[str] = verdict["missed"]
    return {
        "suite": "backend",
        "backend_conclusion": verdict["backend_conclusion"],
        "junit_xml_files_seen": verdict["junit_xml_files_seen"],
        "total_tests_run": verdict["total_tests_run"],
        "failure_count": verdict["failure_count"],
        "selected_test_count": verdict["selected_test_count"],
        "caught_count": len(verdict["caught"]),
        "missed_count": len(missed),
        "missed_files": missed[:EVENT_MISSED_FILES_LIMIT],
        "missed_files_truncated": len(missed) > EVENT_MISSED_FILES_LIMIT,
        "recall": verdict["recall"],
        "full_run_triggered": verdict["full_run_triggered"],
        "full_run_reasons": verdict["full_run_reasons"][:EVENT_FULL_RUN_REASONS_LIMIT],
        "pr_number": pr_number,
        "pr_draft": pr_draft,
        "merge_queue": merge_queue,
        "branch": branch,
        "sha": sha,
        "run_id": run_id,
    }


def event_properties_from_env(verdict: dict[str, Any]) -> dict[str, object]:
    pr_number = os.environ.get("PR_NUMBER", "")
    pr_draft = os.environ.get("PR_DRAFT", "")
    return event_properties(
        verdict,
        pr_number=int(pr_number) if pr_number.isdigit() else None,
        pr_draft={"true": True, "false": False}.get(pr_draft),
        merge_queue=os.environ.get("MERGE_QUEUE") == "true",
        branch=os.environ.get("BRANCH", ""),
        sha=os.environ.get("GITHUB_SHA", ""),
        run_id=os.environ.get("GITHUB_RUN_ID", ""),
    )


def format_summary(verdict: dict[str, object]) -> str:
    """Produce a concise markdown summary for GITHUB_STEP_SUMMARY."""
    lines: list[str] = []
    lines.append("## Test selection verdict")
    lines.append("")

    conclusion = verdict["backend_conclusion"]
    failure_count = verdict["failure_count"]
    recall = verdict["recall"]
    selected = verdict["selected_test_count"]
    full_run_triggered = verdict.get("full_run_triggered", False)

    if conclusion == "unknown":
        lines.append("Backend conclusion unknown — no JUnit XML artifacts were found.")
        lines.append("")
        lines.append(f"{selected} tests would have been selected by the shadow selector.")
    elif conclusion == "success":
        lines.append(f"Backend passed. {selected} tests were selected by the shadow selector.")
        lines.append("")
        lines.append("No failures to evaluate recall against.")
    else:
        recall_str = f"{recall:.0%}" if recall is not None else "n/a"
        lines.append(f"**Recall: {recall_str}** ({failure_count} failed test files, {selected} selected)")
        if full_run_triggered:
            lines.append("")
            lines.append("Full-run mode was active, so every failure counts as caught.")
        lines.append("")

        caught = verdict.get("caught", [])
        missed = verdict.get("missed", [])

        if caught:
            lines.append(f"**Caught** ({len(caught)}):")
            for f in caught:
                lines.append(f"- `{f}`")

        if missed:
            lines.append("")
            lines.append(f"**Missed** ({len(missed)}):")
            for f in missed:
                lines.append(f"- `{f}`")

    full_run_reasons = verdict.get("full_run_reasons", [])
    if full_run_reasons:
        lines.append("")
        lines.append("**Full-run triggered** — selector would have run everything anyway:")
        for reason in full_run_reasons:
            lines.append(f"- {reason}")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection_json", help="Path to the selection JSON from snob_backend_test_selection_shadow.py")
    parser.add_argument("junit_dir", help="Directory containing JUnit XML files (searched recursively)")
    parser.add_argument("--summary-path", help="Append markdown summary to this file (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--event-path", help="Write the telemetry event properties as JSON to this file")
    args = parser.parse_args()

    selection_path = Path(args.selection_json)
    junit_dir = Path(args.junit_dir)

    if not selection_path.exists():
        sys.stderr.write(f"Error: selection JSON not found: {selection_path}\n")
        sys.exit(1)

    verdict = compute_verdict(selection_path, junit_dir)

    indent = 2 if args.pretty else None
    sys.stdout.write(json.dumps(verdict, indent=indent, sort_keys=True) + "\n")

    if args.summary_path:
        with Path(args.summary_path).expanduser().open("a") as fh:
            fh.write(format_summary(verdict))

    if args.event_path:
        Path(args.event_path).write_text(json.dumps(event_properties_from_env(verdict)) + "\n")


if __name__ == "__main__":
    main()
