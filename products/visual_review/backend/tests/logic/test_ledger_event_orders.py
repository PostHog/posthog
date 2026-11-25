from datetime import datetime, timedelta
from enum import StrEnum

import pytest

from django.utils import timezone

from posthog.dataclasses import frozen

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.contracts import NoRunNeededInput
from products.visual_review.backend.facade.enums import (
    BaselineApprovalState,
    BaselineEntrySource,
    BaselineMode,
    RunPurpose,
    RunType,
)
from products.visual_review.backend.logic import approvals, commit_status, gating, ledger, ledger_advance
from products.visual_review.backend.logic.baseline_record import record_for_run
from products.visual_review.backend.models import BaselineApproval, BaselineEntry, Repo, Run
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ci_workflow import (
    FIXED_WORKFLOW,
    MASTER_WORKFLOW,
    REPORT_CHECK,
    SETUP_CHECK,
    CiInputs,
    CiOutcome,
    CiWorkflow,
    WorkflowConfig,
)
from products.visual_review.backend.tests.logic.event_orders import (
    CI_GAP_SCENARIOS,
    CI_SCENARIOS,
    SCENARIOS,
    Layer,
    Scenario,
)
from products.visual_review.backend.tests.logic.ledger_fakes import SEED, FakeActions, FakeGit, LedgerFlow, seeded_repo

COLORS = {
    "b0": (255, 0, 0, 255),
    "b1": (0, 0, 255, 255),
    "b2": (0, 255, 0, 255),
    "b3": (255, 255, 0, 255),
    "c0": (128, 128, 128, 255),
}
GATE = commit_status.gate_context(RunType.STORYBOOK)

GUARANTEE_QUEUE = (
    "A queue run whose rendered pictures were all approved passes, and one that renders a picture nobody "
    "approved does not get through"
)
GUARANTEE_LEDGER_MATCHES_MASTER = "After the landings, the ledger holds the picture the default branch renders"
GUARANTEE_ONLY_RENDERED_PICTURES = "No approval is promoted for a picture that no landed queue run rendered"
CHECK_RESTACK = (
    "A restacked layer keeps its approval only when the approval was made over the picture the ledger now holds, "
    "or over an open layer below whose approval still counts"
)
GUARANTEE_UNRELATED_NOT_BOTH = (
    "Two unrelated pull requests with different pictures never both land unless the second approved again "
    "after the first landed, and one left behind shows a failing gate"
)
GUARANTEE_GREEN_HEAD = (
    "A pull request head whose last gate status is success has a run that passes against the ledger and the "
    "approvals now, or the pull request changes no picture against its base"
)

REASON_APPROVED = "every picture it renders was approved"
REASON_NOBODY_APPROVED = "it renders a picture that no pull request in the batch approved"
REASON_LAYER_NOT_APPROVED = "a pull request in the batch has no approval, so its gate fails"
REASON_APPROVED_UNDER_OLD_BASELINE = (
    "the layer below landed alone, and this layer's approval was made over a picture the ledger does not hold, "
    "so the baseline moved under the approval and the layer has to approve again"
)

REASON_RESTACK_NOT_APPROVED_YET = "the layer has no approval yet, so its restacked run asks for one"
REASON_RESTACK_APPROVED_OVER_LEDGER = (
    "the approval was made over the picture the ledger now holds, so it still applies after the restack"
)
REASON_RESTACK_APPROVED_OVER_OPEN_LAYER = (
    "the approval was made over the picture of an open layer below whose approval still counts, so it chains on "
    "that approval and still applies after the restack"
)
# Accepted: `_stack_tip` needs the approved commits in the commit graph, and a restack leaves them out.
REASON_RESTACK_NO_HASH_LINK = (
    "the approval was made over the ledger picture while an approved layer below it was not in its tree, so after "
    "the restack both approvals apply with no hash link between them, and the restacked run asks for a new approval"
)
REASON_RESTACK_APPROVED_OVER_OLD_BASELINE = (
    "the approval was made over the baseline from before the layer below landed, so the restacked run asks for "
    "a new approval"
)


@frozen
class Expectation:
    gets_through: bool
    reason: str


@frozen
class RestackCheck:
    name: str
    gate_passes: bool
    expected_to_pass: bool
    reason: str
    outcome: str


class WorkflowResult(StrEnum):
    RAN = "ran"
    SKIPPED = "skipped"
    FAILED = "failed"


@frozen
class Workflow:
    frontend_diff: frozenset[str]
    base: str | None
    result: WorkflowResult


@frozen
class QueueAttempt:
    group: tuple[str, ...]
    master_head: str
    expected: Expectation
    passed: bool
    # The picture the queue run rendered, or None when a failing gate kept the batch out of the queue.
    picture: str | None
    outcome: str


def story_file(name: str) -> str:
    return f"{name}-story@1"


def ledger_button(repo: Repo) -> str:
    head = ledger.cursor(repo.id)
    assert head is not None
    return ledger.ledger_at(repo.id, RunType.STORYBOOK, head.position).get("Button", "")


class OrderPlayer:
    def __init__(
        self,
        scenario: Scenario,
        repo: Repo,
        git: FakeGit,
        flow: LedgerFlow,
        user,
        capture,
        actions: FakeActions,
        workflow: CiWorkflow,
    ) -> None:
        self.scenario = scenario
        self.repo = repo
        self.git = git
        self.flow = flow
        self.user = user
        self.capture = capture
        self.actions = actions
        self.workflow = workflow
        self.commits = 0
        self.clock = timezone.now() - timedelta(days=1)
        # The pull requests whose changes each commit's tree holds, which decides the picture it renders.
        self.changes: dict[str, frozenset[str]] = {SEED: frozenset()}
        # The frontend files each commit's tree changes against the seed, as "<layer>-<file>@<version>".
        self.frontend_files: dict[str, frozenset[str]] = {SEED: frozenset()}
        self.master_frontend_files: frozenset[str] = frozenset()
        # The layer each pull request is based on, or None for the default branch.
        self.bases: dict[str, str | None] = {layer.name: layer.stacked_on for layer in scenario.layers}
        self.first_heads: dict[str, str] = {}
        # Heads that a push to the open pull request moved to, so their workflow runs for `synchronize`.
        self.pushed_heads: set[str] = set()
        self.bot_heads: set[str] = set()
        self.workflows: dict[str, list[Workflow]] = {layer.name: [] for layer in scenario.layers}
        self.green_head_breaks: list[str] = []
        self.master_changes: frozenset[str] = frozenset()
        self.heads: dict[str, str] = {}
        self.runs: dict[str, Run] = {}
        self.picture_below_at_run: dict[str, str] = {}
        self.approved_pictures: dict[str, set[str]] = {layer.name: set() for layer in scenario.layers}
        self.approved_after_a_landing: dict[str, set[str]] = {layer.name: set() for layer in scenario.layers}
        self.approved_commits: dict[str, set[str]] = {layer.name: set() for layer in scenario.layers}
        self.approved_over: dict[str, str] = {}
        self.restacks: list[RestackCheck] = []
        self.attempts: list[QueueAttempt] = []
        self.landed: list[str] = []
        self.landed_pictures: dict[str, str] = {}
        self.trace: list[str] = []
        for picture, color in COLORS.items():
            flow.picture(picture, color)
        # `gh stack submit` pushes every layer at once, before any run finishes.
        for layer in scenario.layers:
            parent = SEED if layer.stacked_on is None else self.heads[layer.stacked_on]
            own_change = frozenset({layer.name}) if layer.frontend else frozenset()
            own_files = frozenset({story_file(layer.name)}) if layer.frontend else frozenset()
            self._move_head(
                layer, (parent,), self.changes[parent] | own_change, self.frontend_files[parent] | own_files
            )
            self.first_heads[layer.name] = self.heads[layer.name]

    def _next_sha(self, prefix: str) -> str:
        self.commits += 1
        return f"{prefix}-{self.commits}"

    def _tick(self) -> datetime:
        self.clock += timedelta(minutes=1)
        return self.clock

    def _move_head(
        self,
        layer: Layer,
        parents: tuple[str, ...],
        changes: frozenset[str],
        frontend_files: frozenset[str] | None = None,
    ) -> None:
        sha = self.git.commit(self._next_sha(layer.name), *parents)
        self.changes[sha] = changes
        self.frontend_files[sha] = self.frontend_files[parents[0]] if frontend_files is None else frontend_files
        self.heads[layer.name] = sha
        self.git.open_pull_request(layer.pr_number, sha)

    def _picture(self, changes: frozenset[str]) -> str:
        return self.scenario.pictures[changes]

    def _renders(self, sha: str) -> dict[str, str]:
        return {"Button": self._picture(self.changes[sha]), "Card": "c0"}

    def _chain(self, name: str) -> frozenset[str]:
        names: set[str] = set()
        below: str | None = name
        while below is not None:
            names.add(below)
            below = self.scenario.layer(below).stacked_on
        return frozenset(names)

    def _approval_in_tree(self, name: str, sha: str) -> bool:
        ancestors = self.git.ancestors(sha)
        return bool(self.approved_pictures[name]) and (
            self.heads[name] in ancestors or bool(self.approved_commits[name] & ancestors)
        )

    # The baseline a reviewer sees under a layer: the picture up to the highest layer below it that landed or
    # whose approval is in the tree, otherwise what the default branch held at the branch's merge base.
    def _picture_below(self, layer: Layer, sha: str) -> str:
        landed_in_tree = self.changes[sha] & self.master_changes
        below = layer.stacked_on
        while below is not None:
            if below in self.landed or self._approval_in_tree(below, sha):
                return self._picture(self._chain(below) | landed_in_tree)
            below = self.scenario.layer(below).stacked_on
        return self._picture(landed_in_tree)

    def gate(self, sha: str) -> tuple[str, str]:
        posts = [
            call.kwargs
            for call in self.flow.statuses.call_args_list
            if call.args[1] == sha and call.kwargs["context"] == GATE
        ]
        if not posts:
            return "none", ""
        return posts[-1]["state"], posts[-1]["description"]

    def run(self, name: str) -> str:
        layer = self.scenario.layer(name)
        sha = self.heads[name]
        with self.capture(using=WRITER_DB, execute=True):
            run = self.flow.run(sha, self._renders(sha), branch=name, pr_number=layer.pr_number)
        self.runs[name] = run
        self.picture_below_at_run[name] = self._picture_below(layer, sha)
        button = run.snapshots.get(identifier="Button")
        return f"{sha} Button {button.result} {button.baseline_hash} -> {button.current_hash}, gate {self.gate(sha)}"

    def push(self, name: str) -> str:
        old_head = self.heads[name]
        self._move_head(self.scenario.layer(name), (old_head,), self.changes[old_head])
        return self.run(name)

    def _open_base(self, name: str) -> str | None:
        base = self.bases[name]
        if base is None or base in self.landed:
            return None
        return base

    # The frontend files the pull request's diff against its base changes.
    def _frontend_diff(self, name: str, sha: str) -> frozenset[str]:
        base = self._open_base(name)
        base_files = self.master_frontend_files if base is None else self.frontend_files[self.heads[base]]
        return self.frontend_files[sha] - base_files

    # paths-filter searches the earlier heads, newest first, for one with the same frontend files where the suite
    # ran and passed. A failed workflow on a newer head stops the search, and a base change since then too.
    def _proven_head_matches(self, name: str, frontend_diff: frozenset[str]) -> bool:
        base = self._open_base(name)
        for workflow in reversed(self.workflows[name]):
            if workflow.result == WorkflowResult.FAILED:
                return False
            if workflow.frontend_diff != frontend_diff or workflow.base != base:
                continue
            if workflow.result == WorkflowResult.RAN:
                return True
        return False

    def _report_no_run(self, name: str, sha: str) -> str:
        report = NoRunNeededInput(
            repo_id=self.repo.id,
            run_type=RunType.STORYBOOK,
            commit_sha=sha,
            branch=name,
            pr_number=self.scenario.layer(name).pr_number,
        )
        with self.capture(using=WRITER_DB, execute=True):
            outcome = commit_status.report_no_run_needed(self.repo, report)
        return f"{sha} skip report {outcome}, gate {self.gate(sha)}"

    def ci(self, name: str, *, rerun: bool = False) -> str:
        sha = self.heads[name]
        frontend_diff = self._frontend_diff(name, sha)
        inputs = CiInputs(
            pr_touches_frontend=bool(frontend_diff),
            proven_head_matches=self._proven_head_matches(name, frontend_diff),
            synchronize=sha in self.pushed_heads,
            rerun=rerun,
            bot_baseline_only_push=sha in self.bot_heads,
            affected_stories=any("-story@" in file for file in frontend_diff),
        )
        decision = self.workflow.decide(inputs)
        finished_at = self._tick()
        self.actions.finish(sha, SETUP_CHECK, decision.setup_conclusion, finished_at)
        self.actions.finish(sha, REPORT_CHECK, decision.report_conclusion, finished_at)
        result = WorkflowResult.RAN if decision.outcome == CiOutcome.CREATE_RUN else WorkflowResult.SKIPPED
        self.workflows[name].append(Workflow(frontend_diff=frontend_diff, base=self._open_base(name), result=result))
        decided = f"{decision.outcome}{' after a reuse' if decision.reused else ''}"
        if decision.outcome == CiOutcome.CREATE_RUN:
            return f"{decided}: {self.run(name)}"
        if decision.outcome == CiOutcome.REPORT_NO_RUN:
            return f"{decided}: {self._report_no_run(name, sha)}"
        return f"{decided}: {sha} gate {self.gate(sha)}"

    def fail(self, name: str) -> str:
        sha = self.heads[name]
        finished_at = self._tick()
        # vr-setup and vr-skip both need a successful build on a frontend head, so both are skipped.
        self.actions.finish(sha, SETUP_CHECK, "skipped", finished_at)
        self.actions.finish(sha, REPORT_CHECK, "skipped", finished_at)
        self.workflows[name].append(
            Workflow(
                frontend_diff=self._frontend_diff(name, sha),
                base=self._open_base(name),
                result=WorkflowResult.FAILED,
            )
        )
        return f"{sha} build failed, gate {self.gate(sha)}"

    def push_without_ci(self, name: str, kind: str) -> str:
        layer = self.scenario.layer(name)
        old_head = self.heads[name]
        if kind == "back":
            sha = self.first_heads[name]
            self.heads[name] = sha
            self.git.open_pull_request(layer.pr_number, sha)
            self.pushed_heads.add(sha)
            self.bot_heads.discard(sha)
            return f"{sha}, gate {self.gate(sha)}"
        changes = self.changes[old_head]
        files = self.frontend_files[old_head]
        if kind == "revert":
            changes, files = changes - {name}, files - {story_file(name)}
        elif kind == "restore":
            changes, files = changes | {name}, files | {story_file(name)}
        elif kind == "bot":
            files = files | {f"{name}-snapshots@{self.commits + 1}"}
        elif kind != "backend":
            raise ValueError(f"Unknown push kind {kind!r}")
        self._move_head(layer, (old_head,), changes, files)
        sha = self.heads[name]
        self.pushed_heads.add(sha)
        if kind == "bot":
            self.bot_heads.add(sha)
        return sha

    def retarget(self, name: str) -> str:
        self.bases[name] = None
        self.actions.retarget(self.scenario.layer(name).pr_number, self._tick())
        sha = self.heads[name]
        return f"{sha} targets the default branch, gate {self.gate(sha)}"

    def recheck(self, name: str) -> str:
        sha = self.heads[name]
        with self.capture(using=WRITER_DB, execute=True):
            result = commit_status.publish_recheck(
                self.repo,
                sha,
                RunType.STORYBOOK,
                SETUP_CHECK,
                REPORT_CHECK,
                current={},
                only_success=False,
                wait=lambda: None,
                stacked=self._open_base(name) is not None,
                pr_numbers=(self.scenario.layer(name).pr_number,),
            )
        return f"{sha} recheck {result.outcome}, gate {self.gate(sha)}"

    def _changes_a_picture(self, name: str, sha: str) -> bool:
        base = self._open_base(name)
        base_changes = self.master_changes if base is None else self.changes[self.heads[base]] | self.master_changes
        return not self.changes[sha] <= base_changes

    def check_green_heads(self, event: str) -> None:
        for layer in self.scenario.layers:
            if layer.name in self.landed:
                continue
            sha = self.heads[layer.name]
            state, description = self.gate(sha)
            if state != "success" or not self._changes_a_picture(layer.name, sha):
                continue
            verdict = commit_status.ledger_verdict(self.repo, sha, RunType.STORYBOOK)
            if verdict.state == "success":
                continue
            self.green_head_breaks.append(
                f"{GUARANTEE_GREEN_HEAD}: after '{event}', {layer.name} head {sha} shows '{description}', "
                f"and its verdict now is {verdict.state} '{verdict.description}'"
            )

    def _expect_after_restack(self, layer: Layer) -> tuple[bool, str]:
        if layer.name not in self.approved_over:
            return False, REASON_RESTACK_NOT_APPROVED_YET
        approved_over = self.approved_over[layer.name]
        open_below = [
            name
            for name in self._chain(layer.name) - {layer.name}
            if name not in self.landed and self.approved_pictures[name]
        ]
        if approved_over == self._picture(self.master_changes):
            if open_below:
                return False, REASON_RESTACK_NO_HASH_LINK
            return True, REASON_RESTACK_APPROVED_OVER_LEDGER
        if any(approved_over == self._picture(self._chain(name)) for name in open_below):
            return True, REASON_RESTACK_APPROVED_OVER_OPEN_LAYER
        return False, REASON_RESTACK_APPROVED_OVER_OLD_BASELINE

    def restack(self, name: str) -> str:
        layer = self.scenario.layer(name)
        below = layer.stacked_on
        parent = self.heads[below] if below is not None and below not in self.landed else self.git.head
        own_files = frozenset(file for file in self.frontend_files[self.heads[name]] if file.startswith(f"{name}-"))
        self._move_head(layer, (parent,), self.changes[parent] | {name}, self.frontend_files[parent] | own_files)
        outcome = self.run(name)
        expected_to_pass, reason = self._expect_after_restack(layer)
        gate_passes = self.gate(self.heads[name])[0] == "success"
        self.restacks.append(
            RestackCheck(
                name=name, gate_passes=gate_passes, expected_to_pass=expected_to_pass, reason=reason, outcome=outcome
            )
        )
        return f"{outcome}; expected gate to pass={expected_to_pass}"

    def update(self, name: str) -> str:
        old_head = self.heads[name]
        self._move_head(
            self.scenario.layer(name),
            (old_head, self.git.head),
            self.changes[old_head] | self.master_changes,
            self.frontend_files[old_head] | self.master_frontend_files,
        )
        return self.run(name)

    def approve(self, name: str) -> str:
        run = Run.objects.using(WRITER_DB).get(id=self.runs[name].id)
        # A person approves only a run that asks for a review.
        if gating.count_gating(run) == 0:
            return f"nothing to approve at {run.commit_sha}"
        with self.capture(using=WRITER_DB, execute=True):
            approvals.finalize_run(run_id=run.id, user_id=self.user.id, approve_all=True)
        picture = self._renders(run.commit_sha)["Button"]
        self.approved_pictures[name].add(picture)
        self.approved_commits[name].add(run.commit_sha)
        self.approved_over[name] = self.picture_below_at_run[name]
        if self.landed:
            self.approved_after_a_landing[name].add(picture)
        return f"{run.commit_sha} approved, gate {self.gate(run.commit_sha)}"

    def expect(self, group: tuple[str, ...], picture: str) -> Expectation:
        if any(not self.approved_pictures[name] for name in group):
            return Expectation(gets_through=False, reason=REASON_LAYER_NOT_APPROVED)
        owners = [self.scenario.layer(name) for name in group if picture in self.approved_pictures[name]]
        if not owners:
            return Expectation(gets_through=False, reason=REASON_NOBODY_APPROVED)
        owner = owners[-1]
        under_old_baseline = self.approved_over[owner.name] != self._picture(self.master_changes)
        if owner.stacked_on in self.landed and under_old_baseline:
            return Expectation(gets_through=False, reason=REASON_APPROVED_UNDER_OLD_BASELINE)
        return Expectation(gets_through=True, reason=REASON_APPROVED)

    def _test_in_queue(self, group: tuple[str, ...]) -> QueueAttempt:
        heads = [self.heads[name] for name in group]
        changes = self.master_changes.union(*(self.changes[head] for head in heads))
        picture = self._picture(changes)
        expected = self.expect(group, picture)
        failing_gates = [(name, self.gate(self.heads[name])) for name in group]
        failing_gates = [(name, gate) for name, gate in failing_gates if gate[0] != "success"]
        if failing_gates:
            return QueueAttempt(
                group=group,
                master_head=self.git.head,
                expected=expected,
                passed=False,
                picture=None,
                outcome=f"blocked by gates {failing_gates}",
            )
        sha = self.git.commit(self._next_sha("q"), self.git.head, *heads)
        self.changes[sha] = changes
        with self.capture(using=WRITER_DB, execute=True):
            run = self.flow.run(sha, self._renders(sha), branch=f"trunk-merge/{sha}", purpose=RunPurpose.OBSERVE)
        state, description = self.gate(sha)
        record = record_for_run(run)
        conflicts = {} if record is None else record.conflicts
        return QueueAttempt(
            group=group,
            master_head=self.git.head,
            expected=expected,
            passed=state == "success",
            picture=picture,
            outcome=f"{sha} renders {picture}: {state} '{description}', conflicts {conflicts}",
        )

    def queue(self, group: tuple[str, ...]) -> str:
        attempt = self._test_in_queue(group)
        self.attempts.append(attempt)
        return f"{attempt.outcome}; expected through={attempt.expected.gets_through}"

    def land(self, group: tuple[str, ...]) -> str:
        retested = ""
        attempt = next(attempt for attempt in reversed(self.attempts) if attempt.group == group)
        # The queue tests a batch on top of the default branch it merges into, so a merge in between means a new test.
        if attempt.master_head != self.git.head:
            retested = f"tested again: {self.queue(group)}; "
            attempt = self.attempts[-1]
        if not attempt.passed or attempt.picture is None:
            return f"{retested}the queue removed the batch"
        merged = []
        for name in group:
            sha = self.git.merge(self.scenario.layer(name).pr_number, self._next_sha("m"), squash=True)
            self.master_changes = self.master_changes | self.changes[self.heads[name]]
            self.master_frontend_files = self.master_frontend_files | self.frontend_files[self.heads[name]]
            self.changes[sha] = self.master_changes
            self.frontend_files[sha] = self.master_frontend_files
            merged.append(sha)
            self.landed.append(name)
            self.landed_pictures[name] = attempt.picture
        with self.capture(using=WRITER_DB, execute=True):
            ledger_advance.advance(self.repo)
            ledger_advance.reconcile_open_approvals(self.repo)
        return f"{retested}merged as {merged}, ledger Button {ledger_button(self.repo)}"

    def play(self, event: str) -> None:
        verb, *names = event.split(" ")
        if verb == "run":
            outcome = self.run(names[0])
        elif verb == "push" and len(names) == 1:
            outcome = self.push(names[0])
        elif verb == "push":
            outcome = self.push_without_ci(names[0], names[1])
        elif verb == "ci":
            outcome = self.ci(names[0])
        elif verb == "rerun":
            outcome = self.ci(names[0], rerun=True)
        elif verb == "fail":
            outcome = self.fail(names[0])
        elif verb == "retarget":
            outcome = self.retarget(names[0])
        elif verb == "recheck":
            outcome = self.recheck(names[0])
        elif verb == "restack":
            outcome = self.restack(names[0])
        elif verb == "update":
            outcome = self.update(names[0])
        elif verb == "approve":
            outcome = self.approve(names[0])
        elif verb == "queue":
            outcome = self.queue(tuple(names))
        elif verb == "land":
            outcome = self.land(tuple(names))
        else:
            raise ValueError(f"Unknown event {event!r}")
        self.trace.append(f"{event}: {outcome}")
        self.check_green_heads(event)


def broken_guarantees(player: OrderPlayer) -> list[str]:
    broken = list(player.green_head_breaks)
    for attempt in player.attempts:
        if attempt.passed != attempt.expected.gets_through:
            broken.append(
                f"{GUARANTEE_QUEUE}: queue {' '.join(attempt.group)} {attempt.outcome}, "
                f"expected through={attempt.expected.gets_through} because {attempt.expected.reason}"
            )

    for restack in player.restacks:
        if restack.gate_passes != restack.expected_to_pass:
            broken.append(
                f"{CHECK_RESTACK}: restack {restack.name} {restack.outcome}, expected gate to pass="
                f"{restack.expected_to_pass} because {restack.reason}"
            )

    master_picture = player.scenario.pictures[player.master_changes]
    if ledger_button(player.repo) != master_picture:
        broken.append(
            f"{GUARANTEE_LEDGER_MATCHES_MASTER}: ledger {ledger_button(player.repo)}, default branch {master_picture}"
        )

    entry_hashes = set(
        BaselineEntry.objects.using(WRITER_DB)
        .filter(repo=player.repo, source=BaselineEntrySource.MERGE)
        .values_list("content_hash", flat=True)
    )
    promoted_hashes = set(
        BaselineApproval.objects.using(WRITER_DB)
        .filter(repo=player.repo, state=BaselineApprovalState.PROMOTED)
        .values_list("content_hash", flat=True)
    )
    landed_pictures = set(player.landed_pictures.values())
    never_rendered = (entry_hashes | promoted_hashes) - landed_pictures
    if never_rendered:
        broken.append(
            f"{GUARANTEE_ONLY_RENDERED_PICTURES}: {sorted(never_rendered)}, landed queue runs rendered "
            f"{sorted(landed_pictures)}"
        )

    unrelated = all(layer.stacked_on is None for layer in player.scenario.layers)
    if unrelated and player.landed:
        left_behind = [layer.name for layer in player.scenario.layers if layer.name not in player.landed]
        green_left_behind = [name for name in left_behind if player.gate(player.heads[name])[0] == "success"]
        last = player.landed[-1]
        all_landed_without_new_approval = (
            not left_behind and player.landed_pictures[last] not in player.approved_after_a_landing[last]
        )
        if all_landed_without_new_approval or green_left_behind:
            broken.append(
                f"{GUARANTEE_UNRELATED_NOT_BOTH}: landed {player.landed}, green gates left behind {green_left_behind}"
            )
    return broken


def describe(order: tuple[str, ...], player: OrderPlayer) -> str:
    rows = (
        BaselineApproval.objects.using(WRITER_DB)
        .filter(repo=player.repo)
        .order_by("pr_number", "approved_at")
        .values_list("pr_number", "content_hash", "ledger_base_hash", "effective_base_hash", "state", "evidence")
    )
    return "\n".join(
        [
            f"order: {', '.join(order)}",
            *(f"  {line}" for line in player.trace),
            "approvals (pr, hash, ledger base, effective base, state, evidence):",
            *(f"  {row}" for row in rows),
            f"ledger Button at the end: {ledger_button(player.repo)}",
        ]
    )


def play_order(
    scenario: Scenario, order: tuple[str, ...], workflow: WorkflowConfig, team, user, mocker, capture
) -> OrderPlayer:
    repo = seeded_repo(team.id, BaselineMode.LEDGER)
    player = OrderPlayer(
        scenario,
        repo,
        FakeGit(mocker, SEED),
        LedgerFlow(repo, mocker),
        user,
        capture,
        FakeActions(mocker),
        CiWorkflow(workflow),
    )
    for event in order:
        try:
            player.play(event)
        except Exception as error:
            raise AssertionError(f"{event!r} raised {error!r}\n{describe(order, player)}") from error
    return player


CASES = [
    pytest.param(scenario, order, id=f"{scenario.key}-{index:03d}")
    for scenario in (*SCENARIOS, *CI_SCENARIOS)
    for index, order in enumerate(scenario.every_order())
]


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
@pytest.mark.parametrize("scenario,order", CASES)
def test_every_event_order_keeps_the_ledger_guarantees(
    scenario, order, team, user, mocker, django_capture_on_commit_callbacks
) -> None:
    player = play_order(scenario, order, FIXED_WORKFLOW, team, user, mocker, django_capture_on_commit_callbacks)

    broken = broken_guarantees(player)
    assert not broken, "\n".join([*broken, describe(order, player)])


@frozen
class Gap:
    scenario_key: str
    workflow: WorkflowConfig
    order: tuple[str, ...]
    reason: str


REASON_REUSE = (
    "a backend-only push reuses the passing workflow of a red head, so the skip report greens a head with no run"
)
REASON_REUSE_OVER_STALE_APPROVAL = (
    "the push reuses the workflow of an approved head after another pull request landed the same story, so the "
    "skip report greens a head whose approval is stale"
)
REASON_BOT_SHORTCUT = (
    "a bot push of the baseline file only clears the frontend filter, so the skip report greens a red pull request, "
    "and a re-run keeps the push payload and greens it again"
)
REASON_RETARGET = (
    "the child's diff against its parent changes no frontend file, so the skip report greens it, and the retarget "
    "to the default branch keeps the green on the same commit while recheck leaves a retargeted head alone"
)
REASON_FORCE_PUSH_BACK = (
    "a force-push back to an older head shows that head's green from before the baseline moved, because the "
    "republish after a landing reaches only the commit of the newest run, until CI finishes on the head again"
)

GAPS = [
    Gap(
        scenario_key="ci_red_frontend_pr_then_backend_push",
        workflow=MASTER_WORKFLOW,
        order=("ci F", "push F backend", "ci F 2", "rerun F", "recheck F"),
        reason=REASON_REUSE,
    ),
    Gap(
        scenario_key="ci_approved_pr_baseline_moves_then_backend_push",
        workflow=MASTER_WORKFLOW,
        order=("ci A", "ci B", "approve A", "approve B", "queue B", "land B", "push A backend", "ci A 2", "recheck A"),
        reason=REASON_REUSE_OVER_STALE_APPROVAL,
    ),
    Gap(
        scenario_key="ci_bot_baseline_push_on_red_pr",
        workflow=MASTER_WORKFLOW,
        order=("ci F", "push F bot", "ci F 2", "rerun F", "recheck F"),
        reason=REASON_BOT_SHORTCUT,
    ),
    Gap(
        scenario_key="ci_stacked_child_skipped_then_retargeted",
        workflow=FIXED_WORKFLOW,
        order=("ci P", "ci C", "retarget C", "recheck C"),
        reason=REASON_RETARGET,
    ),
    Gap(
        scenario_key="ci_force_push_back_after_baseline_moves",
        workflow=FIXED_WORKFLOW,
        order=(
            "ci A",
            "ci B",
            "approve A",
            "approve B",
            "queue B",
            "push A backend",
            "ci A 2",
            "land B",
            "push A back",
            "ci A 3",
            "recheck A",
        ),
        reason=REASON_FORCE_PUSH_BACK,
    ),
]


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
@pytest.mark.parametrize("gap", [pytest.param(gap, id=f"{gap.scenario_key}") for gap in GAPS])
def test_the_model_finds_each_known_green_head_gap(gap, team, user, mocker, django_capture_on_commit_callbacks) -> None:
    scenario = next(scenario for scenario in (*CI_SCENARIOS, *CI_GAP_SCENARIOS) if scenario.key == gap.scenario_key)
    assert gap.order in scenario.every_order()

    player = play_order(scenario, gap.order, gap.workflow, team, user, mocker, django_capture_on_commit_callbacks)

    assert player.green_head_breaks, f"expected a green head without a passing run because {gap.reason}\n" + describe(
        gap.order, player
    )
