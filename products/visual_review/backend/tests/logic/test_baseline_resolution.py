import pytest

from posthog.egress.limiter.policies import Priority

from products.visual_review.backend.classifier import ToleratedKey
from products.visual_review.backend.facade.enums import BaselineMode, RunPurpose, RunType
from products.visual_review.backend.logic import baseline_resolution, errors, github_api, ledger
from products.visual_review.backend.logic.baseline_resolution import BaselinePick
from products.visual_review.backend.models import Repo, Run, ToleratedHash
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ledger_fakes import (
    DEFAULT_BRANCH,
    SEED,
    FakeGit,
    approve,
    seeded_repo,
    set_baseline_mode,
)


@pytest.fixture
def repo(team) -> Repo:
    return seeded_repo(team.id, BaselineMode.LEDGER)


@pytest.fixture
def git(mocker) -> FakeGit:
    return FakeGit(mocker, SEED)


def _run(repo: Repo, commit_sha: str, *, branch: str = "feat", pr_number: int | None = 8) -> Run:
    return Run.objects.create(
        repo=repo,
        team_id=repo.team_id,
        run_type=RunType.STORYBOOK,
        commit_sha=commit_sha,
        branch=branch,
        pr_number=pr_number,
        purpose=RunPurpose.REVIEW,
    )


def _nothing(mocker) -> None:
    pass


def _head_unreadable(mocker) -> None:
    mocker.patch.object(github_api, "default_branch_head_sha", return_value=None)


def _ancestry_unknown(mocker) -> None:
    mocker.patch.object(github_api, "commit_ancestry", return_value=None)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestResolveLedgerBaseline:
    def test_default_branch_run_reads_the_ledger_at_its_own_commit_without_candidates(self, repo, git) -> None:
        approve(repo, 5, "Button", "b5", commit_sha=SEED)

        resolution = baseline_resolution.resolve_ledger_baseline(
            _run(repo, SEED, branch=DEFAULT_BRANCH, pr_number=None), {"Button": "b5"}
        )

        assert resolution.baseline == {"Button": "b0", "Card": "c0"}
        assert (resolution.record.merge_base_sha, resolution.record.position) == (SEED, 0)
        assert resolution.record.candidate_approval_ids == ()

    @pytest.mark.parametrize(
        ("older_commit_unreadable", "expected_position"),
        [
            pytest.param(False, 1, id="advance_succeeds"),
            pytest.param(True, 2, id="retry_of_an_older_commit_fails_after_the_merge_base_is_written"),
        ],
    )
    def test_merge_base_past_the_cursor_is_learned_by_advance(
        self, repo, git, mocker, older_commit_unreadable, expected_position
    ) -> None:
        ancestry = mocker.patch.object(github_api, "commit_ancestry")
        parent = SEED
        if older_commit_unreadable:
            # GitHub does not return pull request #3, so the retry of its unresolved commit raises.
            approve(repo, 3, "Card", "c3")
            parent = git.commit("u1", SEED, subject="feat: card (#3)")
            ledger.append_commit(repo, position=1, commit_sha="u1", pr_number=3, resolved=False)
        git.commit("m1", parent, subject="chore: tidy (#9)")
        git.head = "m1"
        git.commit("f1", "m1")

        resolution = baseline_resolution.resolve_ledger_baseline(_run(repo, "f1"), {"Button": "b0"})

        assert (resolution.record.position, resolution.record.clamped_to_seed) == (expected_position, False)
        ancestry.assert_not_called()
        assert git.priorities
        assert set(git.priorities) == {Priority.CRITICAL}

    def test_merge_base_older_than_the_seed_reads_position_zero(self, repo, git) -> None:
        git.parents[SEED] = ("old",)
        git.commit("old")
        git.commit("f1", "old")

        resolution = baseline_resolution.resolve_ledger_baseline(_run(repo, "f1"), {"Button": "b0"})

        assert (resolution.record.position, resolution.record.clamped_to_seed) == (0, True)

    @pytest.mark.parametrize(
        ("mode", "break_github", "message", "cursor"),
        [
            pytest.param(BaselineMode.LEDGER, _nothing, "Rebase", "d1", id="ledger_unknown_after_advance"),
            pytest.param(BaselineMode.LEDGER, _head_unreadable, "catch up", SEED, id="ledger_advance_fails"),
            pytest.param(BaselineMode.LEDGER, _ancestry_unknown, "could not tell", "d1", id="ledger_ancestry_unknown"),
            pytest.param(BaselineMode.SHADOW, _nothing, "has not reached", SEED, id="shadow_unknown_without_advance"),
            pytest.param(BaselineMode.SHADOW, _ancestry_unknown, "could not tell", SEED, id="shadow_ancestry_unknown"),
        ],
    )
    def test_a_merge_base_the_ledger_cannot_place_fails_with_a_message(
        self, repo, git, mocker, mode, break_github, message, cursor
    ) -> None:
        set_baseline_mode(repo, mode)
        # The default branch moved past the cursor, and GitHub names a merge-base that the branch does not reach.
        git.head = git.commit("d1", SEED, subject="chore: direct push")
        git.commit("m1", SEED)
        git.commit("f1", "m1")
        compare = git.compare_commits

        def merge_base_off_the_branch(repo, base, head, priority=Priority.CRITICAL):
            if base == DEFAULT_BRANCH:
                return github_api.Comparison(merge_base_sha="m1", commits=(), complete=True)
            return compare(repo, base, head, priority)

        mocker.patch.object(github_api, "compare_commits", side_effect=merge_base_off_the_branch)
        break_github(mocker)

        with pytest.raises(errors.BaselineResolutionError, match=message):
            baseline_resolution.resolve_ledger_baseline(_run(repo, "f1"), {"Button": "b0"})

        head = ledger.cursor(repo.id)
        assert head is not None and head.commit_sha == cursor

    @pytest.mark.parametrize(
        ("name", "pr_number", "commit_sha", "carried_commit_sha", "ledger_base_hash", "newest_run_commit", "applies"),
        [
            ("own_pull_request", 8, "elsewhere", "", "b0", None, True),
            ("commit_in_the_tree", 7, "a1", "", "b0", None, True),
            ("carried_commit_in_the_tree", 7, "rebased-away", "a1", "b0", None, True),
            ("newest_run_commit_in_the_tree", 9, "elsewhere", "", "b0", "a1", True),
            ("later_commit_of_the_branch_it_was_cut_from", 7, "a2", "", "b0", "a2", False),
        ],
    )
    def test_candidates(
        self, repo, git, name, pr_number, commit_sha, carried_commit_sha, ledger_base_hash, newest_run_commit, applies
    ) -> None:
        git.commit("a1", SEED)
        git.commit("a2", "a1")
        git.commit("b1", "a1")
        if newest_run_commit is not None:
            _run(repo, newest_run_commit, branch=f"pr-{pr_number}", pr_number=pr_number)
        approval = approve(
            repo,
            pr_number,
            "Button",
            "b1",
            commit_sha=commit_sha,
            carried_commit_sha=carried_commit_sha,
            ledger_base_hash=ledger_base_hash,
        )

        record = baseline_resolution.resolve_ledger_baseline(_run(repo, "b1"), {"Button": "b1"}).record

        assert (approval.id in record.candidate_approval_ids) is applies
        assert ("Button" in record.overlay) is applies

    def test_incomplete_commit_list_counts_only_the_own_pull_request(self, repo, git) -> None:
        git.commit("a1", SEED)
        git.commit("b1", "a1")
        git.compare_complete = False
        other = approve(repo, 7, "Button", "b1", commit_sha="a1")
        own = approve(repo, 8, "Card", "c1", commit_sha="b1", ledger_base_hash="c0")

        record = baseline_resolution.resolve_ledger_baseline(_run(repo, "b1"), {"Button": "b1", "Card": "c1"}).record

        assert record.candidate_approval_ids == (own.id,)
        assert record.containment_complete is False
        assert other.id not in record.candidate_approval_ids

    @pytest.mark.parametrize(
        ("name", "identifier", "render_hash", "expected_baseline", "expected_second"),
        [
            ("render_tolerated_against_the_overlay_hash", "Button", "tolerated-b1", "b1", None),
            ("anything_else_keeps_the_overlay_as_second_candidate", "Button", "x", "b0", "b1"),
            ("no_ledger_hash_takes_the_overlay", "Fresh", "x", "f1", None),
        ],
    )
    def test_the_pick_reads_the_overlay_and_the_tolerations(
        self, repo, git, name, identifier, render_hash, expected_baseline, expected_second
    ) -> None:
        git.commit("b1", SEED)
        approve(repo, 8, "Button", "b1", commit_sha="b1")
        approve(repo, 8, "Fresh", "f1", commit_sha="b1", ledger_base_hash="")
        for baseline_hash in ("b0", "b1"):
            ToleratedHash.objects.create(
                repo=repo,
                team_id=repo.team_id,
                identifier="Button",
                baseline_hash=baseline_hash,
                alternate_hash=f"tolerated-{baseline_hash}",
            )

        resolution = baseline_resolution.resolve_ledger_baseline(_run(repo, "b1"), {identifier: render_hash})

        assert resolution.baseline.get(identifier) == expected_baseline
        assert resolution.record.second_candidates.get(identifier) == expected_second

    def test_approved_removal_leaves_the_identifier_out_of_a_full_run(self, repo, git) -> None:
        git.commit("b1", SEED)
        approve(repo, 8, "Card", "", commit_sha="b1", ledger_base_hash="c0")

        resolution = baseline_resolution.resolve_ledger_baseline(_run(repo, "b1"), {"Button": "b0"})

        assert resolution.baseline == {"Button": "b0"}


def _tolerated(*pairs: tuple[str, str]) -> dict[ToleratedKey, ToleratedHash]:
    return {
        ToleratedKey(identifier="Button", baseline_hash=baseline_hash, current_hash=render_hash): ToleratedHash()
        for baseline_hash, render_hash in pairs
    }


TOLERATED = _tolerated(("b0", "tolerated-b0"), ("b1", "tolerated-b1"))


class TestPickBaseline:
    @pytest.mark.parametrize(
        ("render_hash", "ledger_hash", "overlay_hash", "expected"),
        [
            pytest.param("b0", "b0", "b1", BaselinePick(baseline_hash="b0"), id="render_is_the_ledger_hash"),
            pytest.param("b1", "b0", "b1", BaselinePick(baseline_hash="b1"), id="render_is_the_overlay_hash"),
            pytest.param(
                "tolerated-b0", "b0", "b1", BaselinePick(baseline_hash="b0"), id="render_tolerated_against_the_ledger"
            ),
            pytest.param(
                "tolerated-b1", "b0", "b1", BaselinePick(baseline_hash="b1"), id="render_tolerated_against_the_overlay"
            ),
            pytest.param(
                "x",
                "b0",
                "b1",
                BaselinePick(baseline_hash="b0", second_candidate="b1"),
                id="anything_else_keeps_the_overlay_as_second_candidate",
            ),
            pytest.param("x", "b0", "", BaselinePick(baseline_hash="b0"), id="no_overlay_takes_the_ledger"),
            pytest.param("x", "b0", "b0", BaselinePick(baseline_hash="b0"), id="an_overlay_equal_to_the_ledger"),
            pytest.param("x", "", "f1", BaselinePick(baseline_hash="f1"), id="no_ledger_hash_takes_the_overlay"),
            pytest.param("x", "", "", BaselinePick(baseline_hash=""), id="no_ledger_hash_and_no_overlay_is_new"),
        ],
    )
    def test_pick_order(self, render_hash, ledger_hash, overlay_hash, expected) -> None:
        assert (
            baseline_resolution.pick_baseline("Button", render_hash, ledger_hash, overlay_hash, TOLERATED) == expected
        )

    @pytest.mark.parametrize(
        ("render_hash", "ledger_hash", "expected"),
        [
            pytest.param("x", "", baseline_resolution.LEDGER_NEW, id="no_ledger_hash_is_new"),
            pytest.param("b0", "b0", baseline_resolution.LEDGER_UNCHANGED, id="same_hash"),
            pytest.param("tolerated-b0", "b0", baseline_resolution.LEDGER_UNCHANGED, id="tolerated_render"),
            pytest.param("x", "b0", baseline_resolution.LEDGER_UNDETERMINED, id="only_a_pixel_diff_could_tell"),
        ],
    )
    def test_shadow_ledger_verdict(self, render_hash, ledger_hash, expected) -> None:
        assert baseline_resolution.shadow_ledger_verdict("Button", render_hash, ledger_hash, TOLERATED) == expected
