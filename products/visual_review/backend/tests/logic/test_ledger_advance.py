from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from django.db import connections
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.enums import (
    BaselineApprovalState,
    BaselineEvidence,
    BaselineMode,
    RunStatus,
    RunType,
)
from products.visual_review.backend.logic import errors, github_api, ledger, ledger_advance
from products.visual_review.backend.logic.baseline_record import METADATA_KEY, BaselineRecord
from products.visual_review.backend.models import (
    BaselineApproval,
    BaselineCommit,
    BaselineEntry,
    QuarantinedIdentifier,
    Repo,
    Run,
)
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ledger_fakes import SEED, approve, make_record, seeded_repo

EVIDENCE_SHA = "queue-run"
APPROVED_AT = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


class _FakeGitHub:
    def __init__(self, mocker) -> None:
        self.head = SEED
        self.commits: dict[str, github_api.ComparedCommit] = {}
        self.pull_requests: dict[int, github_api.PullRequestState | None] = {}
        self.commit_pulls: dict[str, list[github_api.MergedPullRequest]] = {}
        self.evidence_contains_head: bool | None = True
        self.compare_complete = True
        self.compare_commits = mocker.patch.object(github_api, "compare_commits", side_effect=self._compare)
        self.pull_request_state = mocker.patch.object(
            github_api, "pull_request_state", side_effect=lambda repo, number, _priority: self.pull_requests[number]
        )
        self.merged_pull_requests_for_commit = mocker.patch.object(
            github_api,
            "merged_pull_requests_for_commit",
            side_effect=lambda repo, sha, _priority: self.commit_pulls.get(sha, []),
        )
        self.commit_ancestry = mocker.patch.object(
            github_api,
            "commit_ancestry",
            side_effect=lambda repo, ancestor, head, _priority: self.evidence_contains_head,
        )
        mocker.patch.object(github_api, "default_branch_head_sha", side_effect=lambda repo, _priority: self.head)
        mocker.patch.object(github_api, "default_branch_name", return_value="master")

    def _compare(self, repo, base, head, _priority) -> github_api.Comparison:
        return github_api.Comparison(
            merge_base_sha=base, commits=tuple(self.commits.values()), complete=self.compare_complete
        )

    def push(self, sha: str, subject: str) -> None:
        self.commits[sha] = github_api.ComparedCommit(sha=sha, parent_shas=(self.head, "side"), subject=subject)
        self.head = sha

    def open_pull_request(self, pr_number: int) -> None:
        self.pull_requests[pr_number] = github_api.PullRequestState(
            state="open", merged=False, merge_commit_sha=None, base_ref="master", head_sha=f"head-{pr_number}"
        )

    def mark_merged(self, pr_number: int, sha: str) -> None:
        self.pull_requests[pr_number] = github_api.PullRequestState(
            state="closed", merged=True, merge_commit_sha=sha, base_ref="master", head_sha=f"head-{pr_number}"
        )

    def merge(self, pr_number: int, sha: str) -> None:
        self.push(sha, f"feat: change ({pr_number}) (#{pr_number})")
        self.mark_merged(pr_number, sha)


@pytest.fixture
def repo(team) -> Repo:
    return seeded_repo(team.id, BaselineMode.SHADOW)


@pytest.fixture
def github(mocker) -> _FakeGitHub:
    return _FakeGitHub(mocker)


def _ledger(repo: Repo) -> dict[str, str]:
    head = ledger.cursor(repo.id)
    assert head is not None
    return ledger.ledger_at(repo.id, RunType.STORYBOOK, head.position)


def _state(approval: BaselineApproval) -> tuple[str, str]:
    approval.refresh_from_db()
    return approval.state, approval.detail


def _push_directly(repo: Repo, github: _FakeGitHub) -> None:
    github.push("s2", "chore: direct push")


def _merge_another_button_change(repo: Repo, github: _FakeGitHub) -> None:
    approve(repo, 8, "Button", "b8")
    github.merge(8, "s2")


def _rewrite_the_branch(github: _FakeGitHub) -> None:
    github.head = "rewritten-root"


def _cut_the_compare_short(github: _FakeGitHub) -> None:
    github.compare_complete = False


def _approval(**fields) -> BaselineApproval:
    defaults = {
        "pr_number": 7,
        "identifier": "Button",
        "content_hash": "b1",
        "ledger_base_hash": "b0",
        "effective_base_hash": "b0",
        "commit_sha": "head-7",
        "carried_commit_sha": "",
        "evidence": "",
        "approved_at": APPROVED_AT,
    }
    return BaselineApproval(run_type=RunType.STORYBOOK, **{**defaults, **fields})


def _verdict(state: BaselineApprovalState, detail: str, appends_entry: bool) -> ledger_advance.LandingVerdict:
    return ledger_advance.LandingVerdict(state=state, detail=detail, appends_entry=appends_entry)


PROMOTED_UNVERIFIED = _verdict(BaselineApprovalState.PROMOTED, ledger_advance.DETAIL_UNVERIFIED, True)


class TestLandingVerdict:
    @pytest.mark.parametrize(
        ("approval", "current_hash", "facts", "expected"),
        [
            pytest.param(
                _approval(content_hash="b0", ledger_base_hash="older"),
                "b0",
                {},
                _verdict(BaselineApprovalState.PROMOTED, ledger_advance.DETAIL_ALREADY_IN_BASELINE, False),
                id="already_in_baseline",
            ),
            pytest.param(
                _approval(identifier="Gone", content_hash="", ledger_base_hash="g0"),
                "",
                {},
                _verdict(BaselineApprovalState.PROMOTED, ledger_advance.DETAIL_ALREADY_IN_BASELINE, False),
                id="removal_of_an_absent_story_is_already_in_baseline",
            ),
            pytest.param(
                _approval(),
                "b0",
                {"position": 0},
                _verdict(BaselineApprovalState.CONFLICTED, ledger_advance.DETAIL_SEEDED_AFTER_MERGE, False),
                id="merged_before_the_seed",
            ),
            pytest.param(
                _approval(),
                "b0",
                {"has_newer_entry": True},
                _verdict(BaselineApprovalState.CONFLICTED, ledger_advance.DETAIL_LATER_MERGE_CHANGED_IT, False),
                id="a_later_merge_changed_it",
            ),
            pytest.param(
                _approval(ledger_base_hash="older", effective_base_hash="older"),
                "b0",
                {},
                _verdict(BaselineApprovalState.CONFLICTED, ledger_advance.DETAIL_BASELINE_MOVED, False),
                id="baseline_moved",
            ),
            pytest.param(
                _approval(ledger_base_hash="older", effective_base_hash="b0"),
                "b0",
                {},
                PROMOTED_UNVERIFIED,
                id="effective_base_holds",
            ),
            pytest.param(
                _approval(evidence=BaselineEvidence.NOT_REPRODUCED),
                "b0",
                {"quarantined": True, "evidence_applies": True},
                _verdict(BaselineApprovalState.PROMOTED, ledger_advance.DETAIL_QUARANTINED, True),
                id="quarantined_lands_despite_evidence",
            ),
            pytest.param(
                _approval(evidence=BaselineEvidence.NOT_REPRODUCED),
                "b0",
                {"evidence_applies": True},
                _verdict(BaselineApprovalState.VOIDED, ledger_advance.DETAIL_NOT_REPRODUCED, False),
                id="not_reproduced",
            ),
            pytest.param(
                _approval(evidence=BaselineEvidence.REPRODUCED),
                "b0",
                {"evidence_applies": True},
                _verdict(BaselineApprovalState.PROMOTED, ledger_advance.DETAIL_REPRODUCED, True),
                id="reproduced",
            ),
            pytest.param(
                _approval(evidence=BaselineEvidence.NOT_REPRODUCED),
                "b0",
                {},
                PROMOTED_UNVERIFIED,
                id="evidence_from_a_run_without_the_merged_head",
            ),
            pytest.param(
                _approval(identifier="Card", content_hash="", ledger_base_hash="c0", effective_base_hash="c0"),
                "c0",
                {},
                PROMOTED_UNVERIFIED,
                id="approved_removal",
            ),
            pytest.param(
                _approval(commit_sha="head-7-before-rebase", carried_commit_sha="head-7"),
                "b0",
                {},
                PROMOTED_UNVERIFIED,
                id="carried_to_the_merged_head",
            ),
            pytest.param(
                _approval(commit_sha="head-7-before-split", carried_commit_sha="head-7-before-split"),
                "b0",
                {},
                _verdict(BaselineApprovalState.VOIDED, ledger_advance.DETAIL_NOT_RENDERED_AT_MERGE, False),
                id="no_run_at_the_merged_head",
            ),
            pytest.param(
                _approval(pr_number=1, commit_sha="head-1"),
                "b0",
                {},
                None,
                id="another_pull_requests_approval_without_evidence_stays_open",
            ),
            pytest.param(
                _approval(pr_number=1, commit_sha="head-1", evidence=BaselineEvidence.REPRODUCED),
                "b0",
                {"evidence_applies": True},
                _verdict(BaselineApprovalState.PROMOTED, ledger_advance.DETAIL_REPRODUCED, True),
                id="another_pull_requests_approval_with_evidence_lands",
            ),
        ],
    )
    def test_landing_table(self, approval, current_hash, facts, expected) -> None:
        landing = {
            "landing_pr_number": 7,
            "merged_head_sha": "head-7",
            "evidence_applies": False,
            "quarantined": False,
            "has_newer_entry": False,
            "position": 1,
        }

        assert ledger_advance.landing_verdict(approval, current_hash, **{**landing, **facts}) == expected

    @pytest.mark.parametrize(
        ("approvals", "expected"),
        [
            pytest.param(
                [
                    _approval(pr_number=2, content_hash="b2", effective_base_hash="b1"),
                    _approval(pr_number=1, content_hash="b1", approved_at=APPROVED_AT + timedelta(minutes=1)),
                ],
                [1, 2],
                id="a_stack_parent_lands_before_a_child_approved_earlier",
            ),
            pytest.param(
                [
                    _approval(pr_number=2, content_hash="b0", effective_base_hash="b1"),
                    _approval(pr_number=1, content_hash="b1", approved_at=APPROVED_AT + timedelta(minutes=1)),
                ],
                [2, 1],
                id="a_cycle_keeps_approval_order",
            ),
            pytest.param(
                [
                    _approval(pr_number=3, identifier="Card", approved_at=APPROVED_AT + timedelta(minutes=2)),
                    _approval(pr_number=1, approved_at=APPROVED_AT + timedelta(minutes=1)),
                    _approval(pr_number=2, identifier="Other"),
                ],
                [2, 1, 3],
                id="unrelated_approvals_keep_approval_order",
            ),
        ],
    )
    def test_landing_order(self, approvals, expected) -> None:
        assert [approval.pr_number for approval in ledger_advance.landing_order(approvals)] == expected

    @pytest.mark.parametrize(
        ("subject", "expected"),
        [
            pytest.param("feat: change (#12)", 12, id="squash_suffix"),
            pytest.param('Revert "feat: change (#12)" (#15)', 15, id="the_last_number_counts"),
            pytest.param("chore: direct push", None, id="no_number"),
            pytest.param("fix: issue #12", None, id="a_bare_issue_reference"),
        ],
    )
    def test_named_pull_request(self, subject, expected) -> None:
        assert ledger_advance.named_pull_request(subject) == expected


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestAdvance:
    @pytest.mark.parametrize(
        ("fields", "quarantined", "evidence_contains_head", "expected", "ledger_hash"),
        [
            pytest.param(
                {"evidence": BaselineEvidence.REPRODUCED, "evidence_commit_sha": EVIDENCE_SHA},
                (),
                True,
                (BaselineApprovalState.PROMOTED, ledger_advance.DETAIL_REPRODUCED),
                "b1",
                id="evidence_at_the_merged_head",
            ),
            pytest.param(
                {"evidence": BaselineEvidence.NOT_REPRODUCED, "evidence_commit_sha": EVIDENCE_SHA},
                (),
                False,
                (BaselineApprovalState.PROMOTED, ledger_advance.DETAIL_UNVERIFIED),
                "b1",
                id="evidence_from_a_run_without_the_merged_head",
            ),
            pytest.param(
                {"evidence": BaselineEvidence.NOT_REPRODUCED, "evidence_commit_sha": EVIDENCE_SHA},
                ("Button",),
                True,
                (BaselineApprovalState.PROMOTED, ledger_advance.DETAIL_QUARANTINED),
                "b1",
                id="quarantined_lands_despite_evidence",
            ),
        ],
    )
    def test_a_merge_lands_by_the_landing_table(
        self, repo, github, fields, quarantined, evidence_contains_head, expected, ledger_hash
    ) -> None:
        approval = approve(repo, 7, "Button", "b1", **fields)
        for identifier in quarantined:
            QuarantinedIdentifier.objects.create(
                team_id=repo.team_id, repo=repo, identifier=identifier, run_type=RunType.STORYBOOK, reason="flaky"
            )
        github.evidence_contains_head = evidence_contains_head
        github.merge(7, "s1")

        result = ledger_advance.advance(repo)

        assert _state(approval) == expected
        assert _ledger(repo)["Button"] == ledger_hash
        approval.refresh_from_db()
        assert (approval.landed_position, approval.landed_commit_sha) == (1, "s1")
        assert result == ledger_advance.AdvanceResult(
            commits_added=1, commits_resolved_late=0, approvals_landed=1, commits_unresolved_recently=0
        )

    def test_a_stack_lands_as_two_commits(self, repo, github) -> None:
        parent = approve(repo, 1, "Button", "b1")
        child = approve(repo, 2, "Button", "b2", effective_base_hash="b1")
        github.merge(1, "s1")
        github.merge(2, "s2")

        ledger_advance.advance(repo)

        assert [_state(parent)[0], _state(child)[0]] == [BaselineApprovalState.PROMOTED] * 2
        entries = BaselineEntry.objects.filter(repo=repo, identifier="Button", position__gt=0).order_by("id")
        assert [(e.position, e.previous_hash, e.content_hash) for e in entries] == [(1, "b0", "b1"), (2, "b1", "b2")]

    @pytest.mark.parametrize(
        ("parent_evidence", "evidence_commit_sha", "expected_parent", "landed"),
        [
            pytest.param(BaselineEvidence.REPRODUCED, EVIDENCE_SHA, BaselineApprovalState.PROMOTED, 2, id="reproduced"),
            pytest.param("", "", BaselineApprovalState.OPEN, 1, id="without_evidence"),
        ],
    )
    def test_another_pull_requests_approval_lands_through_the_run_record(
        self, repo, github, parent_evidence, evidence_commit_sha, expected_parent, landed
    ) -> None:
        # The child was approved first, so only the stack order lands the parent before it.
        child = approve(
            repo, 2, "Button", "b2", effective_base_hash="b1", approved_at=timezone.now() - timedelta(minutes=10)
        )
        parent = approve(
            repo,
            1,
            "Button",
            "b1",
            evidence=parent_evidence,
            evidence_commit_sha=evidence_commit_sha,
        )
        unrelated = approve(repo, 3, "Card", "c3", ledger_base_hash="c0")
        record = make_record(mode=BaselineMode.SHADOW, candidate_approval_ids=(parent.id, child.id))
        Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            run_type=RunType.STORYBOOK,
            branch="child",
            pr_number=2,
            commit_sha="head-2",
            status=RunStatus.COMPLETED,
            metadata={METADATA_KEY: record.to_json()},
        )
        github.merge(2, "s1")
        github.open_pull_request(1)
        github.open_pull_request(3)

        result = ledger_advance.advance(repo)
        github.pull_request_state.reset_mock()
        ledger_advance.reconcile_open_approvals(repo)

        assert _state(parent)[0] == expected_parent
        assert _state(child)[0] == BaselineApprovalState.PROMOTED
        assert _state(unrelated)[0] == BaselineApprovalState.OPEN
        assert _ledger(repo) == {"Button": "b2", "Card": "c0"}
        # The open approval neither holds the commit unresolved nor makes the hourly pass land pull request 2 again.
        assert BaselineCommit.objects.get(repo=repo, commit_sha="s1").resolved
        assert result.approvals_landed == landed
        assert 2 not in {call.args[1] for call in github.pull_request_state.call_args_list}

    @pytest.mark.parametrize(
        ("next_commit", "expected_state", "button_at_its_position", "button_at_the_head"),
        [
            pytest.param(_push_directly, BaselineApprovalState.PROMOTED, "b7", "b7", id="lands_at_its_own_position"),
            pytest.param(
                _merge_another_button_change, BaselineApprovalState.CONFLICTED, "b0", "b8", id="a_newer_entry_wins"
            ),
        ],
    )
    def test_an_unresolved_commit_lands_late_at_its_own_position(
        self, repo, github, next_commit, expected_state, button_at_its_position, button_at_the_head
    ) -> None:
        late = approve(repo, 7, "Button", "b7")
        github.push("s1", "feat: late (#7)")
        github.open_pull_request(7)
        next_commit(repo, github)

        first = ledger_advance.advance(repo)
        github.mark_merged(7, "s1")
        second = ledger_advance.advance(repo)

        assert (first.commits_added, second.commits_added, second.commits_resolved_late) == (2, 0, 1)
        assert BaselineCommit.objects.get(repo=repo, commit_sha="s1").resolved
        assert _state(late)[0] == expected_state
        assert ledger.ledger_at(repo.id, RunType.STORYBOOK, 1)["Button"] == button_at_its_position
        assert _ledger(repo)["Button"] == button_at_the_head

    @pytest.mark.parametrize(
        ("name", "recorded_ago", "counted"),
        [
            ("recorded_just_now", timedelta(0), 1),
            ("recorded_ten_minutes_ago", timedelta(minutes=10), 0),
        ],
    )
    def test_only_a_recently_recorded_unresolved_commit_asks_for_a_quick_follow_up(
        self, repo, github, name, recorded_ago, counted
    ) -> None:
        late = approve(repo, 7, "Button", "b7")
        github.push("s1", "feat: late (#7)")
        github.open_pull_request(7)

        first = ledger_advance.advance(repo)
        BaselineCommit.objects.filter(repo=repo, commit_sha="s1").update(created_at=timezone.now() - recorded_ago)
        still_open = ledger_advance.advance(repo)
        github.mark_merged(7, "s1")
        merged = ledger_advance.advance(repo)

        assert first.commits_unresolved_recently == 1
        assert still_open.commits_unresolved_recently == counted
        assert merged.commits_resolved_late == 1
        assert _state(late)[0] == BaselineApprovalState.PROMOTED

    def test_evidence_github_cannot_place_waits_instead_of_landing(self, repo, github) -> None:
        flaky = approve(
            repo,
            7,
            "Button",
            "b7",
            evidence=BaselineEvidence.NOT_REPRODUCED,
            evidence_commit_sha=EVIDENCE_SHA,
        )
        github.merge(7, "s1")

        github.evidence_contains_head = None
        ledger_advance.advance(repo)
        assert _state(flaky)[0] == BaselineApprovalState.OPEN
        assert not BaselineCommit.objects.get(repo=repo, commit_sha="s1").resolved

        github.evidence_contains_head = True
        ledger_advance.advance(repo)
        assert _state(flaky)[0] == BaselineApprovalState.VOIDED
        assert _ledger(repo)["Button"] == "b0"

    @pytest.mark.parametrize(
        ("break_the_walk", "error"),
        [
            pytest.param(_rewrite_the_branch, errors.BaselineBranchRewrittenError, id="rewritten_branch"),
            pytest.param(_cut_the_compare_short, errors.BaselineCommitGapTooLargeError, id="gap_past_the_compare_cap"),
        ],
    )
    def test_a_walk_it_cannot_finish_writes_nothing(self, repo, github, break_the_walk, error) -> None:
        approval = approve(repo, 7, "Button", "b1")
        break_the_walk(github)
        github.merge(7, "s1")

        with pytest.raises(error):
            ledger_advance.advance(repo)

        assert BaselineCommit.objects.filter(repo=repo).count() == 1
        assert _state(approval)[0] == BaselineApprovalState.OPEN

    def test_a_concurrent_caller_does_not_land_twice(self, repo, github) -> None:
        approval = approve(repo, 7, "Button", "b1")
        github.merge(7, "s1")
        github.push("s2", "chore: direct push")
        last_read = github.merged_pull_requests_for_commit.side_effect

        # The other caller runs between this caller's last GitHub read and its write, and saw an
        # older head, so it writes only the first commit.
        def other_caller_finishes_first(*args):
            github.merged_pull_requests_for_commit.side_effect = last_read
            github.head = "s1"
            ledger_advance.advance(repo)
            github.head = "s2"
            return last_read(*args)

        github.merged_pull_requests_for_commit.side_effect = other_caller_finishes_first

        result = ledger_advance.advance(repo)

        assert result.commits_added == 1
        assert list(BaselineCommit.objects.filter(repo=repo).order_by("position").values_list("commit_sha")) == [
            (SEED,),
            ("s1",),
            ("s2",),
        ]
        assert BaselineEntry.objects.filter(repo=repo, approval=approval).count() == 1

    @pytest.mark.parametrize(
        ("name", "subject", "commit_pulls", "expected_pr", "expected_state"),
        [
            (
                "subject_names_a_different_merge",
                "feat: thing (#7)",
                [github_api.MergedPullRequest(number=9, base_ref="master", head_sha="head-9")],
                9,
                BaselineApprovalState.PROMOTED,
            ),
        ],
    )
    def test_a_commit_without_a_usable_subject_asks_github_for_its_pull_request(
        self, repo, github, name, subject, commit_pulls, expected_pr, expected_state
    ) -> None:
        approve(repo, 7, "Card", "c7", ledger_base_hash="c0")
        approval = approve(repo, 9, "Button", "b9")
        github.pull_requests[7] = github_api.PullRequestState(
            state="closed", merged=True, merge_commit_sha="elsewhere", base_ref="master", head_sha="head-7"
        )
        github.push("s1", subject)
        github.commit_pulls["s1"] = commit_pulls

        ledger_advance.advance(repo)

        commit = BaselineCommit.objects.get(repo=repo, commit_sha="s1")
        assert (commit.pr_number, commit.resolved) == (expected_pr, True)
        assert _state(approval)[0] == expected_state

    @pytest.mark.parametrize(
        ("name", "approve_first", "recorded_ago", "pulls_later", "first_pass", "commit_after", "button_at_position"),
        [
            (
                "github_links_the_pull_request_later",
                True,
                timedelta(0),
                [github_api.MergedPullRequest(number=9, base_ref="master", head_sha="head-9")],
                (False, 1),
                (9, True),
                "b9",
            ),
            ("still_unlinked_after_the_window", True, timedelta(minutes=10), [], (False, 1), (None, True), "b0"),
            ("no_open_approval_in_the_repo", False, timedelta(0), [], (True, 0), (None, True), "b0"),
        ],
    )
    def test_a_new_commit_github_has_not_linked_yet_waits_while_an_approval_is_open(
        self, repo, github, name, approve_first, recorded_ago, pulls_later, first_pass, commit_after, button_at_position
    ) -> None:
        if approve_first:
            approve(repo, 9, "Button", "b9")
        github.push("s1", "Merge branch 'feature'")

        first = ledger_advance.advance(repo)
        first_resolved = BaselineCommit.objects.get(repo=repo, commit_sha="s1").resolved
        BaselineCommit.objects.filter(repo=repo, commit_sha="s1").update(created_at=timezone.now() - recorded_ago)
        github.commit_pulls["s1"] = pulls_later
        ledger_advance.advance(repo)

        commit = BaselineCommit.objects.get(repo=repo, commit_sha="s1")
        assert (first_resolved, first.commits_unresolved_recently) == first_pass
        assert (commit.pr_number, commit.resolved) == commit_after
        assert ledger.ledger_at(repo.id, RunType.STORYBOOK, commit.position)["Button"] == button_at_position

    def test_commits_of_pull_requests_with_nothing_to_land_cost_one_compare(self, repo, github) -> None:
        for number in range(1, 6):
            github.merge(number, f"s{number}")

        result = ledger_advance.advance(repo)

        assert result.commits_added == 5
        assert github.compare_commits.call_count == 1
        github.pull_request_state.assert_not_called()
        github.merged_pull_requests_for_commit.assert_not_called()
        assert list(
            BaselineCommit.objects.filter(repo=repo, position__gt=0).order_by("position").values_list("pr_number")
        ) == [(1,), (2,), (3,), (4,), (5,)]

    def test_a_landing_costs_the_same_queries_for_one_approval_and_for_many(self, repo, github) -> None:
        approve(repo, 7, "Story-0", "h7", ledger_base_hash="")
        for number in range(40):
            approve(
                repo, 8, f"Story-{number}", "h8", ledger_base_hash="", effective_base_hash="h7" if number == 0 else ""
            )

        query_counts = []
        for pr_number, sha in ((7, "s1"), (8, "s2")):
            github.merge(pr_number, sha)
            with CaptureQueriesContext(connections[WRITER_DB]) as queries:
                result = ledger_advance.advance(repo)
            query_counts.append(len(queries))
            assert result.approvals_landed == (1 if pr_number == 7 else 40)

        assert query_counts[0] == query_counts[1]
        assert _ledger(repo)["Story-0"] == "h8"

    def test_a_yaml_repo_is_left_alone(self, repo, github) -> None:
        repo.baseline_mode = BaselineMode.YAML
        repo.save()
        github.merge(7, "s1")

        ledger_advance.advance(repo)

        github.compare_commits.assert_not_called()
        assert BaselineCommit.objects.filter(repo=repo).count() == 1


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestReconcileOpenApprovals:
    def test_lands_merged_abandons_closed_and_skips_unreadable(self, repo, github) -> None:
        # The commit is in the ledger without its pull request, as after a walk that missed it.
        github.push("s1", "chore: no pull request named")
        ledger_advance.advance(repo)
        merged = approve(repo, 7, "Button", "b7")
        closed = approve(repo, 8, "Card", "c8", ledger_base_hash="c0")
        unreadable = approve(repo, 9, "Card", "c9", ledger_base_hash="c0")
        github.mark_merged(7, "s1")
        github.pull_requests[8] = github_api.PullRequestState(
            state="closed", merged=False, merge_commit_sha=None, base_ref="master", head_sha="head-8"
        )
        github.pull_requests[9] = None

        ledger_advance.reconcile_open_approvals(repo)

        assert _state(merged) == (BaselineApprovalState.PROMOTED, ledger_advance.DETAIL_UNVERIFIED)
        assert ledger.ledger_at(repo.id, RunType.STORYBOOK, 1)["Button"] == "b7"
        assert _state(closed) == (BaselineApprovalState.ABANDONED, ledger_advance.DETAIL_CLOSED_WITHOUT_MERGE)
        assert _state(unreadable)[0] == BaselineApprovalState.OPEN

    def test_late_landings_apply_in_ledger_position_order(self, repo, github) -> None:
        github.push("s1", "chore: no pull request named")
        github.push("s2", "chore: no pull request named")
        ledger_advance.advance(repo)
        earlier_merge = approve(repo, 9, "Button", "b9")
        later_merge = approve(repo, 5, "Button", "b5")
        github.mark_merged(9, "s1")
        github.mark_merged(5, "s2")

        ledger_advance.reconcile_open_approvals(repo)

        assert _state(earlier_merge) == (BaselineApprovalState.PROMOTED, ledger_advance.DETAIL_UNVERIFIED)
        assert _state(later_merge) == (BaselineApprovalState.CONFLICTED, ledger_advance.DETAIL_BASELINE_MOVED)
        assert _ledger(repo)["Button"] == "b9"

    @pytest.mark.parametrize(
        ("name", "approved_hash", "ancestry", "expected_state", "expected_detail"),
        [
            (
                "seed_holds_the_picture",
                "b0",
                True,
                BaselineApprovalState.PROMOTED,
                ledger_advance.DETAIL_ALREADY_IN_BASELINE,
            ),
            (
                "seed_holds_another_picture",
                "b7",
                True,
                BaselineApprovalState.CONFLICTED,
                ledger_advance.DETAIL_SEEDED_AFTER_MERGE,
            ),
            ("github_cannot_tell", "b7", None, BaselineApprovalState.OPEN, ""),
            ("past_the_cursor", "b7", False, BaselineApprovalState.OPEN, ""),
        ],
    )
    def test_a_merge_commit_without_a_position_lands_at_the_seed_only_when_older(
        self, repo, github, name, approved_hash, ancestry, expected_state, expected_detail
    ) -> None:
        approval = approve(repo, 7, "Button", approved_hash)
        github.pull_requests[7] = github_api.PullRequestState(
            state="closed", merged=True, merge_commit_sha="before-seed", base_ref="master", head_sha="head-7"
        )
        github.commit_ancestry.side_effect = lambda repo, ancestor, head, _priority: ancestry

        ledger_advance.reconcile_open_approvals(repo)

        assert _state(approval) == (expected_state, expected_detail)
        approval.refresh_from_db()
        if expected_state != BaselineApprovalState.OPEN:
            assert approval.landed_position == 0
        assert not BaselineEntry.objects.filter(repo=repo, approval=approval).exists()
        assert ledger.ledger_at(repo.id, RunType.STORYBOOK, 0)["Button"] == "b0"

    @pytest.mark.parametrize(
        ("merged_days_ago", "expected_state"),
        [(13, BaselineApprovalState.OPEN), (15, BaselineApprovalState.ABANDONED), (None, BaselineApprovalState.OPEN)],
    )
    def test_approvals_of_a_pull_request_merged_into_another_branch_wait_before_they_are_abandoned(
        self, repo, github, merged_days_ago, expected_state
    ) -> None:
        approval = approve(repo, 7, "Button", "b7", approved_at=timezone.now() - timedelta(days=30))
        merged_at = None if merged_days_ago is None else timezone.now() - timedelta(days=merged_days_ago)
        github.pull_requests[7] = github_api.PullRequestState(
            state="closed",
            merged=True,
            merge_commit_sha="m7",
            base_ref="release",
            head_sha="head-7",
            merged_at=merged_at,
        )

        ledger_advance.reconcile_open_approvals(repo)

        assert _state(approval)[0] == expected_state


def test_record_ids_survive_the_json_round_trip() -> None:
    approval_id = UUID("01890000-0000-7000-8000-000000000001")
    record = BaselineRecord(
        mode=BaselineMode.SHADOW,
        merge_base_sha=SEED,
        position=3,
        clamped_to_seed=False,
        containment_complete=True,
        overlay={},
        candidate_approval_ids=(approval_id,),
        conflicts={"Button": (1, 2)},
        second_candidates={},
        differences={"Button": "b1"},
    )

    assert BaselineRecord.from_json(record.to_json()) == record
