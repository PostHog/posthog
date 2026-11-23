"""Set the baseline ledger of a ledger-mode repo to what a full default-branch run rendered, for named identifiers.

In ledger mode the baseline file no longer follows the baselines, so a repair has nothing to compare
the ledger against. Adopting renders takes the picture from a full default-branch run that the operator
chose, and appends one entry per identifier at the newest resolved commit. Like a repair, it never
changes or deletes an entry, and it leaves the approvals as they are.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.db import transaction
from django.db.models import Count

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority

from ..db import WRITER_DB
from ..facade.contracts import BaselineLedgerAdoption, BaselineLedgerAdoptionItem
from ..facade.enums import BaselineApprovalState, BaselineEntrySource, BaselineMode, RunPurpose, RunStatus
from ..models import BaselineApproval, BaselineCommit, BaselineEntry, Repo, Run, RunSnapshot
from . import errors, github_api, ledger


@frozen
class _CheckedRun:
    run: Run
    identifiers: tuple[str, ...]


def _require_ledger_mode(repo: Repo) -> None:
    if repo.baseline_mode == BaselineMode.LEDGER:
        return
    raise errors.BaselineAdoptionError(
        f"{repo.repo_full_name} is in {repo.baseline_mode} mode. Adopting renders only runs in ledger mode. "
        "In shadow mode, use repair."
    )


def _identifiers(identifiers: Iterable[str]) -> tuple[str, ...]:
    named = tuple(sorted(set(identifiers)))
    if not named:
        raise errors.BaselineAdoptionError("Name at least one identifier.")
    return named


def _full_run(repo: Repo, run_type: str, run_id: UUID) -> Run:
    """The run, when it is a completed full observe run without a pull request.

    `_require_default_branch` checks its branch, because that needs a GitHub read.
    """
    run = Run.objects.using(WRITER_DB).filter(id=run_id, repo_id=repo.id, team_id=repo.team_id).first()
    if run is None:
        raise errors.BaselineAdoptionError(f"Run {run_id} is not a run of {repo.repo_full_name}.")
    if run.run_type != run_type:
        raise errors.BaselineAdoptionError(f"Run {run_id} is a {run.run_type} run, not a {run_type} run.")
    if run.status != RunStatus.COMPLETED:
        raise errors.BaselineAdoptionError(f"Run {run_id} is {run.status}, not completed.")
    if run.is_partial:
        raise errors.BaselineAdoptionError(
            f"Run {run_id} is a partial run. Pick a full run, because a partial run does not render every story."
        )
    if run.purpose != RunPurpose.OBSERVE or run.pr_number is not None:
        raise errors.BaselineAdoptionError(
            f"Run {run_id} is not a default-branch run: it is a {run.purpose} run"
            + (f" of PR #{run.pr_number}." if run.pr_number is not None else ".")
        )
    return run


def _require_default_branch(repo: Repo, run: Run) -> None:
    """The branch name is client-supplied, so it is compared with the default branch that GitHub names."""
    try:
        default_branch = github_api.default_branch_name(repo, Priority.BATCH)
    except github_api.GITHUB_READ_REFUSED as e:
        raise errors.BaselineAdoptionError(
            "GitHub or the egress budget refused the read of the default branch. Try again later."
        ) from e
    if default_branch is None:
        raise errors.BaselineAdoptionError("GitHub did not name the default branch. Nothing was written.")
    if run.branch != default_branch:
        raise errors.BaselineAdoptionError(
            f"Run {run.id} ran on {run.branch}, not on the default branch {default_branch}."
        )


def _newest_resolved_commit(repo: Repo) -> BaselineCommit:
    """The adoption writes here, because an unresolved commit above it can still land an approval of its own."""
    commit = (
        BaselineCommit.objects.using(WRITER_DB).filter(repo_id=repo.id, resolved=True).order_by("-position").first()
    )
    if commit is None:
        raise errors.BaselineAdoptionError(f"{repo.repo_full_name} has no resolved ledger commit.")
    return commit


def _run_position(repo: Repo, run: Run) -> int:
    """The ledger position of the run's commit. Every resolved commit is at or below the cursor."""
    commit = BaselineCommit.objects.using(WRITER_DB).filter(repo_id=repo.id, commit_sha=run.commit_sha).first()
    if commit is None or not commit.resolved:
        raise errors.BaselineAdoptionError(
            f"The commit {run.commit_sha} of run {run.id} is not a resolved commit of the ledger. "
            "Pick a run of a commit the ledger has resolved."
        )
    return commit.position


def _renders(run: Run, identifiers: tuple[str, ...]) -> dict[str, str]:
    rows = (
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id=run.id, team_id=run.team_id, identifier__in=identifiers)
        .values_list("identifier", "current_hash")
    )
    renders = {identifier: current_hash for identifier, current_hash in rows if current_hash}
    not_rendered = [identifier for identifier in identifiers if identifier not in renders]
    if not_rendered:
        raise errors.BaselineAdoptionError(
            f"Run {run.id} did not render {', '.join(not_rendered)}. Nothing was written."
        )
    return renders


def _open_approvals(repo: Repo, run_type: str, identifiers: tuple[str, ...]) -> dict[str, int]:
    rows = (
        BaselineApproval.objects.using(WRITER_DB)
        .filter(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=run_type,
            identifier__in=identifiers,
            state=BaselineApprovalState.OPEN,
        )
        .values_list("identifier")
        .annotate(count=Count("id"))
        .order_by()
    )
    return dict(rows)


def _plan(repo: Repo, run_type: str, checked: _CheckedRun) -> BaselineLedgerAdoption:
    """Compare the ledger at the cursor with the render, for each identifier.

    An identifier whose ledger hash changed between the run's position and the cursor stops the
    plan, unless the ledger already holds the render. The run is older than the newest decision
    about that identifier, so its picture can be the one that decision replaced.
    """
    identifiers = checked.identifiers
    cursor = _newest_resolved_commit(repo)
    run_position = _run_position(repo, checked.run)
    renders = _renders(checked.run, identifiers)
    at_cursor = ledger.hashes_at(repo.id, run_type, identifiers, cursor.position)
    at_run = ledger.hashes_at(repo.id, run_type, identifiers, run_position)
    approvals = _open_approvals(repo, run_type, identifiers)

    items: list[BaselineLedgerAdoptionItem] = []
    changed_after_run: list[str] = []
    for identifier in identifiers:
        item = BaselineLedgerAdoptionItem(
            identifier=identifier,
            ledger_hash=at_cursor.get(identifier, ""),
            render_hash=renders[identifier],
            open_approvals=approvals.get(identifier, 0),
        )
        if not item.already_matches and item.ledger_hash != at_run.get(identifier, ""):
            changed_after_run.append(identifier)
        items.append(item)
    if changed_after_run:
        raise errors.BaselineAdoptionError(
            f"The ledger changed {', '.join(changed_after_run)} after position {run_position} of run "
            f"{checked.run.id}, so the run is older than the newest decision about them. "
            "Pick a newer full default-branch run. Nothing was written."
        )
    return BaselineLedgerAdoption(
        run_type=run_type,
        run_id=checked.run.id,
        run_position=run_position,
        cursor_position=cursor.position,
        cursor_sha=cursor.commit_sha,
        items=tuple(items),
    )


def _check_run(repo: Repo, run_type: str, run_id: UUID, identifiers: Iterable[str]) -> _CheckedRun:
    _require_ledger_mode(repo)
    named = _identifiers(identifiers)
    run = _full_run(repo, run_type, run_id)
    _require_default_branch(repo, run)
    return _CheckedRun(run=run, identifiers=named)


def plan_adoption(repo: Repo, run_type: str, run_id: UUID, identifiers: Iterable[str]) -> BaselineLedgerAdoption:
    """The entries an adoption would append, without writing them. Raises `BaselineAdoptionError`."""
    checked = _check_run(repo, run_type, run_id, identifiers)
    return _plan(repo, run_type, checked)


def _write(repo: Repo, plan: BaselineLedgerAdoption) -> None:
    ledger.append_entries(
        [
            BaselineEntry(
                repo=repo,
                team_id=repo.team_id,
                run_type=plan.run_type,
                identifier=item.identifier,
                content_hash=item.render_hash,
                previous_hash=item.ledger_hash,
                position=plan.cursor_position,
                commit_sha=plan.cursor_sha,
                source=BaselineEntrySource.REPAIR,
            )
            for item in plan.to_append
        ]
    )


def adopt_renders(repo: Repo, run_type: str, run_id: UUID, identifiers: Iterable[str]) -> BaselineLedgerAdoption:
    """Append the planned entries at the cursor and return the plan that was written.

    GitHub is read before the lock, so a slow GitHub never holds it. Under the lock the plan is
    made again from the ledger as it is then. The cursor can have moved on, and the plan is checked
    again against the new cursor. When the planned items differ, an approval landed in between,
    and nothing is written.
    """
    checked = _check_run(repo, run_type, run_id, identifiers)
    shown = _plan(repo, run_type, checked)
    with transaction.atomic(using=WRITER_DB):
        ledger.lock_ledger(repo.id)
        repo.refresh_from_db(using=WRITER_DB, fields=["baseline_mode"])
        _require_ledger_mode(repo)
        plan = _plan(repo, run_type, checked)
        if plan.items != shown.items:
            raise errors.BaselineAdoptionError(
                f"The ledger of {repo.repo_full_name} changed while the adoption was planned. "
                "Nothing was written. Run adopt-renders again."
            )
        _write(repo, plan)
    return plan
