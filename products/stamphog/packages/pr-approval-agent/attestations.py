"""CI results that lift named deny categories for the files they list.

An attestation is a policy entry (see `policy.Attestation`). It names a CI result, the deny
categories it may lift, and `paths`, the files it is expected to judge. A result lifts its
categories only for the files it lists itself, intersected with `paths` and the PR's files.
The engine knows no ecosystem, tool or bot. The publisher decides what a passing result proves.

A result lists its files in a `<!-- stamphog:v1 [...] -->` marker in the check's summary. It is
read from the head commit's check runs, which GitHub binds to that commit. A PR that edits one of
the attestation's `publisher_paths` ran its own copy of the publisher, so its result lifts nothing
and waits for nothing.
"""

import re
import json
from collections.abc import Iterable, Mapping

from policy import Attestation

_MARKER_RE = re.compile(r"<!--\s*stamphog:v1\s+(\[[^\]]*\])\s*-->")


def marker_files(text: str) -> frozenset[str]:
    """The paths in the one `stamphog:v1` marker in ``text``. Anything malformed lists nothing.

    A publisher can quote PR content next to its marker, so a second marker means the text is not
    only the publisher's, and it lists nothing.
    """
    markers = _MARKER_RE.findall(text)
    if len(markers) != 1:
        return frozenset()
    try:
        paths = json.loads(markers[0])
    except json.JSONDecodeError:
        return frozenset()
    return frozenset(p for p in paths if isinstance(p, str)) if isinstance(paths, list) else frozenset()


# Per attestation name, the files a reported result lists (empty when it lifts nothing), or None
# when it has not reported for this head yet.
Results = Mapping[str, frozenset[str] | None]


def _edits_publisher(rule: Attestation, pr_files: Iterable[str]) -> bool:
    return any(re.search(pattern, path) for path in pr_files for pattern in rule.publisher_paths)


def _check_result(rule: Attestation, check_runs: Iterable[dict]) -> frozenset[str] | None:
    completed = [
        run
        for run in check_runs
        if run.get("name") == rule.check
        and run.get("status") == "completed"
        and (run.get("app") or {}).get("slug") == rule.app
    ]
    if not completed:
        return None
    latest = max(completed, key=lambda run: run.get("completed_at") or "")
    if latest.get("conclusion") != "success":
        return frozenset()
    return marker_files((latest.get("output") or {}).get("summary") or "")


def resolve_results(
    rules: Iterable[Attestation], check_runs: Iterable[dict], pr_files: Iterable[str]
) -> dict[str, frozenset[str] | None]:
    """Each rule's result by name. None means it has not reported for this head yet."""
    check_runs = list(check_runs)
    pr_files = list(pr_files)
    return {
        rule.name: frozenset() if _edits_publisher(rule, pr_files) else _check_result(rule, check_runs)
        for rule in rules
    }


def _expected_files(rule: Attestation, pr_files: Iterable[str]) -> set[str]:
    return {path for path in pr_files if any(re.search(pattern, path) for pattern in rule.paths)}


def lifted_files(rules: Iterable[Attestation], results: Results, pr_files: Iterable[str]) -> dict[str, frozenset[str]]:
    """Per deny category, the PR files a passing attestation listed and may lift it for."""
    pr_files = list(pr_files)
    lifted: dict[str, set[str]] = {}
    for rule in rules:
        listed = results.get(rule.name)
        if not listed:
            continue
        covered = _expected_files(rule, pr_files) & listed
        for category in rule.lifts:
            lifted.setdefault(category, set()).update(covered)
    return {category: frozenset(files) for category, files in lifted.items() if files}


def assume_passing(
    assumed: Iterable[Attestation], results: Results, pr_files: Iterable[str]
) -> dict[str, frozenset[str] | None]:
    """``results`` with each ``assumed`` attestation passing for every PR file it judges."""
    pr_files = list(pr_files)
    return {
        **results,
        **{rule.name: frozenset(_expected_files(rule, pr_files)) for rule in assumed},
    }


def pending(rules: Iterable[Attestation], results: Results, pr_files: Iterable[str]) -> list[Attestation]:
    """The attestations that have not reported yet although the PR changes a file they judge."""
    pr_files = list(pr_files)
    return [rule for rule in rules if results.get(rule.name) is None and _expected_files(rule, pr_files)]
