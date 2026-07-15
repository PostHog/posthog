import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.persistence import upsert_review_report
from products.review_hog.backend.temporal.activities import FetchPRDataInput, ReviewMeta, _fetch_and_persist
from products.review_hog.backend.temporal.client import _build_inputs

_MODULE = "products.review_hog.backend.temporal.activities"


def _pr_metadata(number: int, head_sha: str = "sha1") -> PRMetadata:
    return PRMetadata(
        number=number,
        title="t",
        state="open",
        draft=False,
        created_at="",
        updated_at="",
        author="octocat" if number else "",
        base_branch="main",
        head_branch="feat",
        head_sha=head_sha,
        commits=1,
        additions=1,
        deletions=0,
        changed_files=1,
    )


class TestBuildInputs(BaseTest):
    def _build(self, **target: object):
        kwargs: dict = {"pr_url": None, "repository": None, "head_branch": None, **target}
        return _build_inputs(
            team_id=self.team.id,
            user_id=1,
            publish=False,
            acting_user_id=None,
            trigger_source="manual",
            signal_report_id=None,
            **kwargs,
        )

    @parameterized.expand(
        [
            ("no_target", {}),
            ("both_targets", {"pr_url": "https://github.com/o/r/pull/1", "repository": "o/r", "head_branch": "b"}),
        ]
    )
    def test_rejects_anything_but_exactly_one_target_shape(self, _name, target) -> None:
        # A caller passing both (or neither) target shapes must fail loudly at the trigger, not start
        # a workflow that fetches an ambiguous target.
        with pytest.raises(ValueError, match="Exactly one review target"):
            self._build(**target)

    @parameterized.expand([("bare_name", "posthog"), ("nested_path", "a/b/c")])
    def test_branch_target_rejects_a_malformed_repository(self, _name, repository) -> None:
        with pytest.raises(ValueError, match="owner/repo"):
            self._build(repository=repository, head_branch="feat")

    def test_branch_target_builds_the_branch_workflow_id(self) -> None:
        # The per-target deterministic id is the duplicate-trigger collapse mechanism; a branch
        # target colliding with (or drifting from) the PR id shape breaks that dedupe.
        inputs, workflow_id = self._build(repository="o/r", head_branch="feat")

        assert workflow_id == f"review-branch:{self.team.id}:o/r:feat"
        assert (inputs.owner, inputs.repo) == ("o", "r")
        assert inputs.pr_number is None
        assert inputs.pr_url is None
        assert inputs.head_branch == "feat"

    def test_workflow_id_lowercases_a_mixed_case_repository(self) -> None:
        # The id (and every sandbox workflow id prefixed with it) must search as one casing in the
        # Temporal UI; GitHub owner/repo are case-insensitive, so lowercasing loses nothing.
        _inputs, workflow_id = self._build(repository="PostHog/PostHog.com", head_branch="Feat")

        assert workflow_id == f"review-branch:{self.team.id}:posthog/posthog.com:feat"


class TestFetchBranchTarget(BaseTest):
    def _fetch(self) -> ReviewMeta:
        return _fetch_and_persist(
            FetchPRDataInput(
                team_id=self.team.id,
                user_id=1,
                repository="o/r",
                owner="o",
                repo="r",
                head_branch="feat",
            )
        )

    @patch(f"{_MODULE}._installation_auth", return_value=("tok", "9876543"))
    @patch(f"{_MODULE}.fetch_branch_compare")
    @patch(f"{_MODULE}.find_open_pr_for_branch", return_value=None)
    def test_branch_with_no_pr_stores_branch_keyed_and_flags_an_empty_diff(self, _find, mock_compare, _auth) -> None:
        # No open PR and nothing reviewable in the compare: the report row is branch-keyed
        # (pr_number NULL) and the meta tells the workflow to self-skip before any sandbox spend.
        mock_compare.return_value = (_pr_metadata(0), [], [], "")

        meta = self._fetch()

        assert meta.pr_number is None
        assert meta.pr_url is None
        assert meta.empty_diff is True
        # The resolved installation id must reach the compare fetch — dropping it silently turns the
        # calls identity-blind (no egress budget accounting).
        mock_compare.assert_called_once_with(
            token="tok", repository="o/r", head_branch="feat", installation_id="9876543"
        )
        row = ReviewReport.objects.for_team(self.team.id).get(id=meta.report_id)
        assert row.pr_number is None
        assert row.head_branch == "feat"

    @patch(f"{_MODULE}._installation_auth", return_value=("tok", "9876543"))
    @patch(f"{_MODULE}.PRFetcher")
    @patch(f"{_MODULE}.find_open_pr_for_branch", return_value=(9, "https://github.com/o/r/pull/9"))
    def test_branch_with_an_open_pr_reviews_via_the_pr_path_and_upgrades_the_stored_row(
        self, _find, mock_fetcher, _auth
    ) -> None:
        # The publishable-turn upgrade: a branch target whose PR now exists must reuse the stored
        # branch-keyed report (watermarks and prior findings carry over), backfill its number/url,
        # and hand the workflow a publish destination.
        pr_files = [PRFile(filename="a.py", status="modified", additions=1, deletions=0)]
        mock_fetcher.return_value.fetch_pr_data.return_value = (_pr_metadata(9), [], pr_files, "diff")
        stored_id = upsert_review_report(team_id=self.team.id, repository="o/r", pr_url="", pr_metadata=_pr_metadata(0))

        meta = self._fetch()

        assert meta.report_id == stored_id
        assert meta.pr_number == 9
        assert meta.pr_url == "https://github.com/o/r/pull/9"
        assert meta.empty_diff is False
        mock_fetcher.assert_called_once_with(owner="o", repo="r", pr_number=9, token="tok", installation_id="9876543")
        row = ReviewReport.objects.for_team(self.team.id).get(id=stored_id)
        assert row.pr_number == 9
        assert row.pr_url == "https://github.com/o/r/pull/9"
