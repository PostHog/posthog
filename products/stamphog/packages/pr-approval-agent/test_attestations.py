import json

import pytest

from attestations import ReviewedHead, lifted_files, pending_attestations, pending_check_names
from policy import Attestation

_GITHUB_ACTIONS_APP_ID = 15368
_MIGRATION_RISK_APP_ID = 2492437
_PROVER_APP_ID = 424242

_MIGRATION_RISK = Attestation(
    name="migration_risk",
    check="Migration risk",
    app_id=_MIGRATION_RISK_APP_ID,
    lifts=("migrations",),
    paths=(r"(?:^|/)migrations/(?!__init__\.py$)[^/]+\.py$",),
    sibling_files=("max_migration.txt",),
)
_DEPENDENCY_PROOF = Attestation(
    name="dependency_proof",
    check="Dependency proof",
    app_id=_PROVER_APP_ID,
    lifts=("deps_toolchain", "ci_workflows"),
    paths=(r"(?:^|/)pnpm-lock\.yaml$", r"(?:^|/)package\.json$"),
    publisher_files=(".github/workflows/dependency-proof.yml",),
)
_REVIEWED = ReviewedHead(pr_number=7, head_sha="a" * 40, merge_base_sha="b" * 40)
_MIGRATION = "posthog/migrations/1125_x.py"
_MAX_MIGRATION = "posthog/migrations/max_migration.txt"
_LOCKFILE = "pnpm-lock.yaml"


def _check(
    name: str = "Migration risk",
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    completed_at: str = "2026-04-30T12:00:00Z",
    files: list[str] | None = None,
    summary: str | None = None,
    app_id: int = _MIGRATION_RISK_APP_ID,
    run_id: int = 1,
    **extra: object,
) -> dict:
    if summary is None:
        summary = "no marker here" if files is None else f"<!-- stamphog:v1 {json.dumps(files)} -->\nreport body"
    return {
        "id": run_id,
        "name": name,
        "app": {"id": app_id},
        "status": status,
        "conclusion": conclusion,
        "completed_at": completed_at,
        "output": {"summary": summary},
        **extra,
    }


def _proof_marker(**overrides: object) -> str:
    payload = {
        "files": [_LOCKFILE],
        "pr": _REVIEWED.pr_number,
        "head_sha": _REVIEWED.head_sha,
        "merge_base": _REVIEWED.merge_base_sha,
        "blobs": dict.fromkeys(_DEPENDENCY_PROOF.publisher_files, "c" * 40),
        **overrides,
    }
    return f"<!-- stamphog:v1 {json.dumps(payload)} -->"


def _proof(**overrides: object) -> dict:
    marker_keys = {"files", "pr", "head_sha", "merge_base", "blobs"}
    marker_overrides = {k: overrides.pop(k) for k in list(overrides) if k in marker_keys}
    return _check(
        "Dependency proof",
        app_id=_PROVER_APP_ID,
        summary=_proof_marker(**marker_overrides),
        pinned_blobs_current=overrides.pop("pinned_blobs_current", True),
        **overrides,
    )


def _lifted(attestations: list[Attestation], check_runs: list[dict], files: list[str]) -> dict[str, set[str]]:
    return lifted_files(attestations, check_runs, files, _REVIEWED)


def test_success_check_lifts_listed_migrations_and_their_sibling_marker() -> None:
    files = [
        _MIGRATION,
        _MAX_MIGRATION,
        "products/signals/backend/migrations/0042_y.py",
        "posthog/clickhouse/migrations/0099_unrelated.py",
        "posthog/clickhouse/migrations/max_migration.txt",
        ".stamphog/policy.yml",
        "posthog/api/some.py",
    ]
    # The analyzer does not read ClickHouse migrations, so the marker names none.
    check = _check(
        files=[
            _MIGRATION,
            "products/signals/backend/migrations/0042_y.py",
            ".stamphog/policy.yml",
            "posthog/migrations/9999_not_in_diff.py",
        ]
    )

    assert _lifted([_MIGRATION_RISK], [check], files) == {
        "migrations": {_MIGRATION, _MAX_MIGRATION, "products/signals/backend/migrations/0042_y.py"}
    }


@pytest.mark.parametrize(
    "check_runs",
    [
        pytest.param([], id="no-checks"),
        pytest.param([_check(name="other-ci", files=[_MIGRATION])], id="different-check-name"),
        pytest.param([_check(files=[_MIGRATION], app_id=_GITHUB_ACTIONS_APP_ID)], id="same-name-from-another-app"),
        pytest.param([_check(conclusion="failure", files=[_MIGRATION])], id="completed-failure"),
        pytest.param([_check(conclusion="neutral", files=[_MIGRATION])], id="completed-needs-review"),
        pytest.param([_check(status="in_progress", conclusion=None, files=[_MIGRATION])], id="in-flight"),
        pytest.param([_check(files=[])], id="empty-marker"),
        pytest.param([_check()], id="no-marker"),
        pytest.param([_check(summary="<!-- stamphog:v1 not-json-array -->")], id="malformed-json"),
        pytest.param([_check(summary='<!-- stamphog:v1 ["missing close ')], id="truncated"),
        pytest.param([_check(summary='<!-- stamphog:v1 {"shape":"wrong"} -->')], id="object-without-identity"),
        pytest.param(
            [_check(summary=f"<!-- stamphog:v1 {json.dumps([_MIGRATION])} --> <!-- stamphog:v1 [] -->")],
            id="two-markers",
        ),
    ],
)
def test_nothing_lifts_without_a_complete_proof(check_runs: list[dict]) -> None:
    assert _lifted([_MIGRATION_RISK], check_runs, [_MIGRATION, _MAX_MIGRATION]) == {}


def test_lift_matches_paths_case_sensitively() -> None:
    renamed = "posthog/Migrations/1125_x.py"

    assert _lifted([_MIGRATION_RISK], [_check(files=[renamed])], [renamed]) == {}


def test_newest_completed_run_by_id_wins_over_older_and_in_flight() -> None:
    older_failure = _check(conclusion="failure", completed_at="2099-01-01T00:00:00Z", files=[_MIGRATION], run_id=1)
    newer_success = _check(conclusion="success", completed_at="2026-04-30T12:00:00Z", files=[_MIGRATION], run_id=2)
    in_flight = _check(status="in_progress", conclusion=None, completed_at="", run_id=3)

    assert _lifted([_MIGRATION_RISK], [older_failure, newer_success, in_flight], [_MIGRATION]) == {
        "migrations": {_MIGRATION}
    }


def test_object_marker_lifts_every_declared_category_for_the_proven_files() -> None:
    files = [_LOCKFILE, "frontend/package.json", ".github/workflows/ci.yml"]

    assert _lifted([_DEPENDENCY_PROOF], [_proof()], files) == {
        "deps_toolchain": {_LOCKFILE},
        "ci_workflows": {_LOCKFILE},
    }


@pytest.mark.parametrize(
    "proof",
    [
        pytest.param(_proof(pr=8), id="other-pr"),
        pytest.param(_proof(head_sha="d" * 40), id="other-head"),
        pytest.param(_proof(merge_base="d" * 40), id="other-merge-base"),
        pytest.param(_proof(pinned_blobs_current=False), id="publisher-changed"),
        pytest.param(_proof(blobs={"pnpm-workspace.yaml": "c" * 40}), id="publisher-file-not-pinned"),
        pytest.param(_proof(blobs=None), id="no-blobs"),
        pytest.param(_check("Dependency proof", app_id=_PROVER_APP_ID, summary=_proof_marker()), id="unconfirmed"),
        pytest.param(_check("Dependency proof", app_id=_PROVER_APP_ID, files=[_LOCKFILE]), id="list-marker"),
    ],
)
def test_object_marker_must_prove_this_review_and_a_current_publisher(proof: dict) -> None:
    assert _lifted([_DEPENDENCY_PROOF], [proof], [_LOCKFILE]) == {}


def test_object_marker_never_matches_an_unknown_merge_base() -> None:
    reviewed = ReviewedHead(pr_number=7, head_sha="a" * 40, merge_base_sha="")
    proof = _proof(merge_base="")

    assert lifted_files([_DEPENDENCY_PROOF], [proof], [_LOCKFILE], reviewed) == {}


def test_each_attestation_lifts_only_its_own_categories() -> None:
    files = [_MIGRATION, _LOCKFILE]

    lifted = _lifted([_MIGRATION_RISK, _DEPENDENCY_PROOF], [_check(files=[_MIGRATION]), _proof()], files)

    assert lifted == {"migrations": {_MIGRATION}, "deps_toolchain": {_LOCKFILE}, "ci_workflows": {_LOCKFILE}}


@pytest.mark.parametrize(
    "check_runs",
    [
        pytest.param([], id="no-check"),
        pytest.param([_check(status="in_progress", conclusion=None)], id="in-progress"),
        pytest.param([_check(status="queued", conclusion=None)], id="queued"),
        pytest.param([_check(app_id=_GITHUB_ACTIONS_APP_ID)], id="completed-by-another-app"),
    ],
)
def test_pending_when_pr_touches_the_paths_and_no_completed_check(check_runs: list[dict]) -> None:
    assert pending_attestations([_MIGRATION_RISK, _DEPENDENCY_PROOF], check_runs, [_MIGRATION]) == [_MIGRATION_RISK]


@pytest.mark.parametrize("conclusion", ["success", "failure"])
def test_not_pending_once_the_check_completed(conclusion: str) -> None:
    assert pending_attestations([_MIGRATION_RISK], [_check(conclusion=conclusion)], [_MIGRATION]) == []


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(["posthog/api/views.py"], id="no-matching-path"),
        pytest.param(["posthog/migrations/__init__.py"], id="excluded-by-the-pattern"),
        pytest.param([_MAX_MIGRATION], id="sibling-alone"),
    ],
)
def test_not_pending_when_no_file_matches_the_paths(files: list[str]) -> None:
    assert pending_attestations([_MIGRATION_RISK], [_check(status="in_progress", conclusion=None)], files) == []


def test_pending_check_names_backticks_each_check() -> None:
    assert pending_check_names([_MIGRATION_RISK, _DEPENDENCY_PROOF]) == "`Migration risk` and `Dependency proof`"
