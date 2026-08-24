#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "defusedxml>=0.7.1",
# ]
# ///
"""Compare test selection against actual JUnit failures to produce a verdict.

Evaluates whether the shadow test selector would have caught the tests that
actually failed in CI, separately for the two matrices ci-backend runs: the
Django shards (junit-results-backend-* artifacts) and the product shards
(product-junit-results-* artifacts). The product side is scored twice: by test
file, like Django, and by product, which is the grain the product matrix is
built at. Outputs a JSON verdict suitable for batch collection across PRs.
"""

from __future__ import annotations

import os
import sys
import json
import argparse
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree

DJANGO = "django"
PRODUCTS = "products"

# select-tests only runs on PRs, so these are empty on every other trigger.
CONTEXT_ENV_VARS = {
    "selection_mode": "SELECTION_MODE",
    "selection_skip_reason": "SELECTION_SKIP_REASON",
    "run_legacy_reason": "RUN_LEGACY_REASON",
}


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


def junit_side(xml_file: Path, junit_dir: Path) -> str:
    """Which matrix produced a JUnit file.

    download-artifact unpacks each artifact into a directory named after it, so the
    first path component under junit_dir is the artifact name. turbo-tests stages its
    files as junit-product-<name>.xml, which also identifies a file on its own.
    """
    try:
        artifact = xml_file.relative_to(junit_dir).parts[0]
    except ValueError:
        artifact = ""
    if artifact.startswith("product-junit-results-") or xml_file.name.startswith("junit-product-"):
        return PRODUCTS
    return DJANGO


@dataclass(frozen=True, kw_only=True, slots=True)
class JunitResults:
    failed_test_files: list[str]
    total_tests_run: int
    xml_files_seen: int


@dataclass(frozen=True, kw_only=True, slots=True)
class Score:
    caught: list[str]
    missed: list[str]
    recall: float | None


def parse_junit_failures(junit_dir: Path, side: str | None = None) -> JunitResults:
    """Parse JUnit XML files under junit_dir.

    With `side`, only files from that matrix count; the others are invisible to
    every field of the result.
    """
    failed_files: set[str] = set()
    total_tests = 0
    xml_files_seen = 0

    if not junit_dir.exists():
        return JunitResults(failed_test_files=[], total_tests_run=0, xml_files_seen=0)

    for xml_file in sorted(junit_dir.rglob("*.xml")):
        if side is not None and junit_side(xml_file, junit_dir) != side:
            continue
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

    return JunitResults(
        failed_test_files=sorted(failed_files), total_tests_run=total_tests, xml_files_seen=xml_files_seen
    )


def product_of(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "products":
        return parts[1]
    return None


def score(failed: list[str], selected: set[str], full_run_triggered: bool) -> Score:
    """Split failures into caught and missed.

    A selector that asked for a full run would have executed every failure, so
    counting those as missed against the narrowed list would skew recall.
    """
    if not failed:
        return Score(caught=[], missed=[], recall=None)
    if full_run_triggered:
        return Score(caught=list(failed), missed=[], recall=1.0)
    caught = sorted(f for f in failed if f in selected)
    missed = sorted(f for f in failed if f not in selected)
    return Score(caught=caught, missed=missed, recall=len(caught) / len(failed))


def side_verdict(results: JunitResults, selected: set[str], full_run_triggered: bool) -> dict[str, object]:
    # No JUnit XMLs means we don't actually know what happened: the upstream
    # artifact upload may have failed, the job may have run before tests
    # finished, or this matrix was skipped. Emit "unknown" rather than the
    # misleading "success" we'd otherwise infer from "0 failures observed".
    if results.xml_files_seen == 0:
        conclusion = "unknown"
    elif not results.failed_test_files:
        conclusion = "success"
    else:
        conclusion = "failure"

    scored = score(results.failed_test_files, selected, full_run_triggered)
    return {
        "conclusion": conclusion,
        "junit_xml_files_seen": results.xml_files_seen,
        "total_tests_run": results.total_tests_run,
        "failure_count": len(results.failed_test_files),
        "failed_test_files": results.failed_test_files,
        "caught": scored.caught,
        "missed": scored.missed,
        "recall": scored.recall,
    }


def product_level(failed_files: list[str], selected: set[str], full_run_triggered: bool) -> dict[str, object]:
    """Score the product side at the grain the product matrix is built at.

    The question is whether a product matrix narrowed to the products the selector
    touched would still have run the failing product's suite.
    """
    selected_products = sorted({p for p in (product_of(t) for t in selected) if p})
    failed_products = sorted({p for p in (product_of(f) for f in failed_files) if p})
    scored = score(failed_products, set(selected_products), full_run_triggered)
    return {
        "selected_products": selected_products,
        "failed_products": failed_products,
        "caught_products": scored.caught,
        "missed_products": scored.missed,
        "product_recall": scored.recall,
    }


def compute_verdict(selection_path: Path, junit_dir: Path) -> dict[str, object]:
    """Build the verdict JSON comparing selection against actual failures."""
    with open(selection_path) as f:
        selection = json.load(f)

    combined = selection.get("combined", {})
    selected_tests: list[str] = combined.get("tests", [])
    selected = set(selected_tests)

    ast_data = selection.get("ast", {})
    full_run_reasons: list[str] = ast_data.get("full_run_reasons", [])
    full_run_triggered = len(full_run_reasons) > 0

    django = side_verdict(parse_junit_failures(junit_dir, DJANGO), selected, full_run_triggered)
    product_results = parse_junit_failures(junit_dir, PRODUCTS)
    products = side_verdict(product_results, selected, full_run_triggered)
    products.update(product_level(product_results.failed_test_files, selected, full_run_triggered))

    return {
        "pr": os.environ.get("PR_NUMBER", ""),
        "sha": os.environ.get("PR_SHA", ""),
        "branch": os.environ.get("PR_BRANCH", ""),
        **{key: os.environ.get(var, "") for key, var in CONTEXT_ENV_VARS.items()},
        "selected_test_count": len(selected_tests),
        "full_run_triggered": full_run_triggered,
        "full_run_reasons": full_run_reasons,
        DJANGO: django,
        PRODUCTS: products,
    }


def format_side(title: str, side: dict[str, object]) -> list[str]:
    lines: list[str] = [f"### {title}", ""]
    conclusion = side["conclusion"]
    failure_count = side["failure_count"]
    recall = side["recall"]

    if conclusion == "unknown":
        lines.append("Conclusion unknown. No JUnit XML artifacts were found for this matrix.")
    elif conclusion == "success":
        lines.append("Passed. No failures to evaluate recall against.")
    else:
        recall_str = f"{recall:.0%}" if isinstance(recall, float) else "n/a"
        lines.append(f"**File recall: {recall_str}** ({failure_count} failed test files)")
        product_recall = side.get("product_recall")
        if isinstance(product_recall, float):
            failed_products = side.get("failed_products", [])
            assert isinstance(failed_products, list)
            lines.append(f"**Product recall: {product_recall:.0%}** ({len(failed_products)} failed products)")
        lines.append("")

        for label, key in (("Caught", "caught"), ("Missed", "missed"), ("Missed products", "missed_products")):
            items = side.get(key, [])
            assert isinstance(items, list)
            if items:
                lines.append("")
                lines.append(f"**{label}** ({len(items)}):")
                lines.extend(f"- `{item}`" for item in items)

    lines.append("")
    return lines


def format_summary(verdict: dict[str, object]) -> str:
    """Produce a concise markdown summary for GITHUB_STEP_SUMMARY."""
    lines: list[str] = ["## Test selection verdict", ""]

    context = ", ".join(f"{key}={verdict[key]}" for key in CONTEXT_ENV_VARS if verdict.get(key))
    lines.append(
        f"{verdict['selected_test_count']} tests selected by the shadow selector" + (f" ({context})" if context else "")
    )
    if verdict.get("full_run_triggered"):
        lines.append("")
        lines.append("Full-run mode was active, so every failure counts as caught.")
    lines.append("")

    django = verdict[DJANGO]
    products = verdict[PRODUCTS]
    assert isinstance(django, dict)
    assert isinstance(products, dict)
    lines.extend(format_side("Django matrix", django))
    lines.extend(format_side("Product matrix", products))

    full_run_reasons = verdict.get("full_run_reasons", [])
    assert isinstance(full_run_reasons, list)
    if full_run_reasons:
        lines.append("**Full-run triggered**, so the selector would have run everything anyway:")
        lines.extend(f"- {reason}" for reason in full_run_reasons)
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection_json", help="Path to the selection JSON from snob_backend_test_selection_shadow.py")
    parser.add_argument("junit_dir", help="Directory containing JUnit XML files (searched recursively)")
    parser.add_argument("--summary-path", help="Append markdown summary to this file (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
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


if __name__ == "__main__":
    main()
