import json

import pytest

from attestations import lifted_files, pending, resolve_results
from policy import Attestation

_MIGRATION = "posthog/migrations/1125_x.py"

MIGRATION_RISK = Attestation(
    name="Migration risk",
    check="Migration risk",
    app="tests-posthog",
    lifts=("migrations",),
    paths=(r"(?:^|/)migrations/(?!__init__\.py$)[^/]+\.py$", r"(?:^|/)migrations/max_migration\.txt$"),
)
RULES = (MIGRATION_RISK,)


def _check(
    *,
    name: str = "Migration risk",
    app: str = "tests-posthog",
    status: str = "completed",
    conclusion: str | None = "success",
    completed_at: str = "2026-11-01T12:00:00Z",
    summary: str | None = None,
    files: list[str] | None = None,
) -> dict:
    if summary is None:
        summary = f"<!-- stamphog:v1 {json.dumps(files or [])} -->\nreport body"
    return {
        "name": name,
        "app": {"slug": app},
        "status": status,
        "conclusion": conclusion,
        "completed_at": completed_at,
        "output": {"summary": summary},
    }


def _lifted(check_runs: list[dict], pr_files: list[str]) -> dict[str, frozenset[str]]:
    return lifted_files(RULES, resolve_results(RULES, check_runs), pr_files)


@pytest.mark.parametrize(
    "check_runs, pr_files, expected",
    [
        pytest.param(
            [_check(files=[_MIGRATION, "posthog/migrations/max_migration.txt", "products/x/migrations/0001_y.py"])],
            [_MIGRATION, "posthog/migrations/max_migration.txt", "posthog/api/some.py"],
            {"migrations": frozenset({_MIGRATION, "posthog/migrations/max_migration.txt"})},
            id="listed-and-changed-files-only",
        ),
        pytest.param(
            [_check(files=[_MIGRATION, "posthog/api/some.py"])],
            [_MIGRATION, "posthog/api/some.py"],
            {"migrations": frozenset({_MIGRATION})},
            id="listed-file-outside-paths",
        ),
        pytest.param(
            [
                _check(files=[], completed_at="2026-11-01T13:00:00Z"),
                _check(files=[_MIGRATION], completed_at="2026-11-01T12:00:00Z"),
                _check(status="in_progress", conclusion=None),
            ],
            [_MIGRATION],
            {},
            id="latest-completed-run-wins",
        ),
        pytest.param([_check(files=[_MIGRATION], conclusion="neutral")], [_MIGRATION], {}, id="not-success"),
        pytest.param([_check(files=[_MIGRATION], app="someone-else")], [_MIGRATION], {}, id="other-app"),
        pytest.param([_check(files=[_MIGRATION], name="other-ci")], [_MIGRATION], {}, id="other-name"),
        pytest.param([_check(summary="no marker here")], [_MIGRATION], {}, id="no-marker"),
        pytest.param([_check(summary="<!-- stamphog:v1 not-json -->")], [_MIGRATION], {}, id="malformed-marker"),
        pytest.param([_check(summary='<!-- stamphog:v1 {"a": 1} -->')], [_MIGRATION], {}, id="wrong-shape"),
        # The analyzer quotes PR content in its report, which can carry a marker of its own.
        pytest.param(
            [_check(summary=f'<!-- stamphog:v1 [] -->\n<!-- stamphog:v1 ["{_MIGRATION}"] -->')],
            [_MIGRATION],
            {},
            id="injected-second-marker",
        ),
    ],
)
def test_check_attestation_lifts_listed_files(
    check_runs: list[dict], pr_files: list[str], expected: dict[str, frozenset[str]]
) -> None:
    assert _lifted(check_runs, pr_files) == expected


@pytest.mark.parametrize(
    "check_runs, pr_files, expected",
    [
        pytest.param([], [_MIGRATION], ["Migration risk"], id="no-check-yet"),
        pytest.param([_check(status="queued", conclusion=None)], [_MIGRATION], ["Migration risk"], id="queued"),
        pytest.param([_check(conclusion="failure")], [_MIGRATION], [], id="completed"),
        pytest.param([], ["posthog/migrations/__init__.py", "clickhouse/migrations/0001.sql"], [], id="no-judged-file"),
    ],
)
def test_pending_only_for_files_the_attestation_judges(
    check_runs: list[dict], pr_files: list[str], expected: list[str]
) -> None:
    results = resolve_results(RULES, check_runs)

    assert [rule.name for rule in pending(RULES, results, pr_files)] == expected
