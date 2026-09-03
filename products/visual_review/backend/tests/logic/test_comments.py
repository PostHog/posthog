"""Unit tests for logic/comments.py — The visual-review PR comment."""

import pytest

from parameterized import parameterized

from products.visual_review.backend.facade.enums import ReviewDecision, ReviewState, SnapshotResult
from products.visual_review.backend.logic import comment_markdown, comments, github_api
from products.visual_review.backend.models import Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestApprovalComment:
    """Tests for the post-approval PR comment summary."""

    @pytest.fixture
    def repo(self, team):
        return Repo.objects.create(
            team_id=team.id,
            repo_external_id=66666,
            repo_full_name="test-org/approval-repo",
            enable_pr_comments=True,
        )

    @pytest.fixture
    def run_with_snapshots(self, repo):
        from products.visual_review.backend.facade.enums import ReviewDecision

        run = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            commit_sha="deadbeef",
            branch="feature",
            pr_number=42,
            review_decision=ReviewDecision.HUMAN_APPROVED,
            metadata={"github_comment_id": 9001, "baseline_commit_sha": "abc1234567"},
        )

        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Login/Form",
            current_hash="curr_a",
            baseline_hash="base_a",
            result=SnapshotResult.CHANGED,
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Settings/Tab",
            current_hash="curr_b",
            baseline_hash="",
            result=SnapshotResult.NEW,
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Old/Component",
            current_hash="",
            baseline_hash="base_c",
            result=SnapshotResult.REMOVED,
        )

        return run

    def test_build_approval_comment_body_summarizes_changes(self, repo, run_with_snapshots):
        approver = comment_markdown._Approver(label="alice", is_github_login=True)
        body = comment_markdown._build_approval_comment_body(run_with_snapshots, repo, approver)

        assert "✅ **Visual changes approved** by @alice" in body
        assert "abc1234" in body  # baseline SHA prefix
        assert f"/visual_review/runs/{run_with_snapshots.id}" in body
        assert "1 changed, 1 new, 1 removed." in body
        assert "<img" not in body
        assert "<table" not in body
        assert "/api/visual_review/public/" not in body

    def test_build_approval_comment_body_falls_back_to_a_reviewer(self, repo, run_with_snapshots):
        body = comment_markdown._build_approval_comment_body(run_with_snapshots, repo, None)

        assert "by a reviewer" in body

    def test_build_approval_comment_body_escapes_non_github_approver(self, repo, run_with_snapshots):
        # email local-part / first_name fallbacks are user-controlled — must be escaped
        approver = comment_markdown._Approver(label="alice[evil](http://attacker)", is_github_login=False)
        body = comment_markdown._build_approval_comment_body(run_with_snapshots, repo, approver)

        # No raw `@` mention (which would render as a GitHub user link)
        assert "by @alice" not in body
        # Markdown control chars in the label must be backslash-escaped
        assert "\\[evil\\]" in body
        assert "\\(http://attacker\\)" in body

    def test_build_approval_comment_body_no_actionable_snapshots(self, repo):
        from products.visual_review.backend.facade.enums import ReviewDecision

        run = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            commit_sha="empty",
            branch="feature",
            pr_number=42,
            review_decision=ReviewDecision.HUMAN_APPROVED,
        )
        approver = comment_markdown._Approver(label="bob", is_github_login=True)
        body = comment_markdown._build_approval_comment_body(run, repo, approver)
        assert "✅ **Visual changes approved**" in body
        # No counts line when there's nothing to summarize
        assert "changed" not in body
        assert "new" not in body
        assert "removed" not in body
        # A genuinely empty run stays silent — the suppressed-only note must not fire
        assert "quarantined or tolerated" not in body

    def test_build_approval_comment_body_excludes_quarantined_and_tolerated(self, repo):
        run = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            commit_sha="mixed",
            branch="feature",
            pr_number=42,
            review_decision=ReviewDecision.HUMAN_APPROVED,
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id, run=run, identifier="Real/Change", result=SnapshotResult.CHANGED
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Flaky/Quarantined",
            result=SnapshotResult.CHANGED,
            is_quarantined=True,
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Known/Tolerated",
            result=SnapshotResult.NEW,
            review_state=ReviewState.TOLERATED,
        )

        body = comment_markdown._build_approval_comment_body(
            run, repo, comment_markdown._Approver(label="bob", is_github_login=True)
        )

        assert "1 changed." in body
        assert "new" not in body
        assert "quarantined or tolerated" not in body

    def test_build_approval_comment_body_notes_when_only_quarantined_and_tolerated(self, repo):
        run = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            commit_sha="suppressed",
            branch="feature",
            pr_number=42,
            review_decision=ReviewDecision.HUMAN_APPROVED,
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Flaky/Quarantined",
            result=SnapshotResult.CHANGED,
            is_quarantined=True,
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Known/Tolerated",
            result=SnapshotResult.NEW,
            review_state=ReviewState.TOLERATED,
        )

        body = comment_markdown._build_approval_comment_body(
            run, repo, comment_markdown._Approver(label="bob", is_github_login=True)
        )

        assert "All visual changes in this run were quarantined or tolerated." in body
        assert "1 changed" not in body

    def test_post_approval_comment_skips_when_pr_comments_disabled(self, repo, run_with_snapshots, mocker):
        repo.enable_pr_comments = False
        repo.save(update_fields=["enable_pr_comments"])

        spy = mocker.patch.object(github_api, "_github_api_request")
        comments._post_approval_comment(run_with_snapshots, repo)
        spy.assert_not_called()

    def test_post_approval_comment_skips_when_no_pr_number(self, repo, run_with_snapshots, mocker):
        run_with_snapshots.pr_number = None
        run_with_snapshots.save(update_fields=["pr_number"])

        spy = mocker.patch.object(github_api, "_github_api_request")
        comments._post_approval_comment(run_with_snapshots, repo)
        spy.assert_not_called()

    def test_post_approval_comment_skips_for_non_human_decision(self, repo, run_with_snapshots, mocker):
        from products.visual_review.backend.facade.enums import ReviewDecision

        run_with_snapshots.review_decision = ReviewDecision.AUTO_APPROVED
        run_with_snapshots.save(update_fields=["review_decision"])

        spy = mocker.patch.object(github_api, "_github_api_request")
        comments._post_approval_comment(run_with_snapshots, repo)
        spy.assert_not_called()

    def test_post_approval_comment_skips_when_no_existing_comment_id(self, repo, run_with_snapshots, mocker):
        run_with_snapshots.metadata = {}
        run_with_snapshots.save(update_fields=["metadata"])

        spy = mocker.patch.object(github_api, "_github_api_request")
        comments._post_approval_comment(run_with_snapshots, repo)
        spy.assert_not_called()

    def test_post_approval_comment_patches_existing_comment(self, repo, run_with_snapshots, mocker):
        class FakeResp:
            status_code = 200
            text = ""

        spy = mocker.patch.object(github_api, "_github_api_request", return_value=FakeResp())

        comments._post_approval_comment(run_with_snapshots, repo)

        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        assert kwargs["method"] == "PATCH"
        assert kwargs["path"] == "issues/comments/9001"
        assert "✅ **Visual changes approved**" in kwargs["json"]["body"]

    def test_post_approval_comment_falls_back_to_post_on_404(self, repo, run_with_snapshots, mocker):
        class PatchResp:
            status_code = 404
            text = "Not Found"

        class PostResp:
            status_code = 201
            text = ""

            @staticmethod
            def json():
                return {"id": 9999}

        spy = mocker.patch.object(github_api, "_github_api_request", side_effect=[PatchResp(), PostResp()])

        comments._post_approval_comment(run_with_snapshots, repo)

        assert spy.call_count == 2
        first_call = spy.call_args_list[0].kwargs
        second_call = spy.call_args_list[1].kwargs
        assert first_call["method"] == "PATCH"
        assert second_call["method"] == "POST"
        assert second_call["path"] == "issues/42/comments"

        run_with_snapshots.refresh_from_db()
        assert run_with_snapshots.metadata["github_comment_id"] == 9999

    def test_post_approval_comment_swallows_exceptions(self, repo, run_with_snapshots, mocker):
        mocker.patch.object(github_api, "_github_api_request", side_effect=RuntimeError("boom"))
        # Must not raise
        comments._post_approval_comment(run_with_snapshots, repo)

    @staticmethod
    def _mk_artifact(repo, content_hash, *, with_thumbnail=None):
        from products.visual_review.backend.models import Artifact

        artifact = Artifact.objects.create(
            repo=repo,
            team_id=repo.team_id,
            content_hash=content_hash,
            storage_path=f"path/{content_hash}",
            width=320,
            height=200,
        )
        if with_thumbnail:
            thumb = Artifact.objects.create(
                repo=repo,
                team_id=repo.team_id,
                content_hash=with_thumbnail,
                storage_path=f"thumb/{with_thumbnail}",
            )
            artifact.thumbnail = thumb
            artifact.save(update_fields=["thumbnail"])
        return artifact

    @staticmethod
    def _fake_storage(returns_url=True):
        class _FakeStorage:
            def __init__(self, repo_id):
                self.repo_id = repo_id

            def get_presigned_download_url(self, content_hash, expiration=3600):
                return f"https://cdn.example/{content_hash}?exp={expiration}" if returns_url else None

        return _FakeStorage

    @pytest.fixture
    def run_with_artifacts(self, repo):
        run = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            commit_sha="cafef00d",
            branch="feature",
            pr_number=42,
            review_decision=ReviewDecision.HUMAN_APPROVED,
            metadata={"github_comment_id": 9001},
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Login/Form",
            result=SnapshotResult.CHANGED,
            baseline_artifact=self._mk_artifact(repo, "base_a", with_thumbnail="thumb_a"),
            current_artifact=self._mk_artifact(repo, "curr_a"),
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Settings/Tab",
            result=SnapshotResult.NEW,
            current_artifact=self._mk_artifact(repo, "curr_b"),
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Old/Component",
            result=SnapshotResult.REMOVED,
            baseline_artifact=self._mk_artifact(repo, "base_c"),
        )
        return run

    def test_build_approval_comment_body_includes_before_after_tables(self, repo, run_with_artifacts, mocker):
        mocker.patch.object(comment_markdown, "ArtifactStorage", self._fake_storage())

        body = comment_markdown._build_approval_comment_body(run_with_artifacts, repo, None, add_images=True)

        # Changed table: baseline before, current after — full-resolution originals,
        # not thumbnails, so clicking opens the image at full size
        assert "**Changed**" in body
        assert "| Snapshot | Before | After |" in body
        assert "https://cdn.example/base_a" in body  # full-res original, not thumb_a
        assert "https://cdn.example/thumb_a" not in body
        assert "https://cdn.example/curr_a" in body
        # Removed snapshot lives in the changed table with an empty after cell
        assert "_(removed)_" in body
        assert "https://cdn.example/base_c" in body
        # New table: empty before cell, current after
        assert "**New**" in body
        assert "https://cdn.example/curr_b" in body
        assert "_(none)_" in body
        # Long-lived URL so GitHub's image proxy can still fetch it later
        assert f"exp={comment_markdown._COMMENT_IMAGE_URL_EXPIRATION}" in body

    def test_build_snapshot_image_tables_excludes_quarantined_and_tolerated(self, repo, run_with_artifacts, mocker):
        mocker.patch.object(comment_markdown, "ArtifactStorage", self._fake_storage())
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run_with_artifacts,
            identifier="Flaky/Quarantined",
            result=SnapshotResult.CHANGED,
            is_quarantined=True,
            baseline_artifact=self._mk_artifact(repo, "base_q"),
            current_artifact=self._mk_artifact(repo, "curr_q"),
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run_with_artifacts,
            identifier="Known/Tolerated",
            result=SnapshotResult.CHANGED,
            review_state=ReviewState.TOLERATED,
            baseline_artifact=self._mk_artifact(repo, "base_t"),
            current_artifact=self._mk_artifact(repo, "curr_t"),
        )

        body = comment_markdown._build_snapshot_image_tables(run_with_artifacts, repo)

        assert "Flaky/Quarantined" not in body
        assert "Known/Tolerated" not in body
        assert "curr_q" not in body
        assert "curr_t" not in body
        assert "Login/Form" in body

    def test_build_approval_comment_body_deep_links_each_snapshot(self, repo, run_with_artifacts, mocker):
        mocker.patch.object(comment_markdown, "ArtifactStorage", self._fake_storage())

        body = comment_markdown._build_approval_comment_body(run_with_artifacts, repo, None, add_images=True)

        # Each snapshot name links straight to its deep link on the run page
        changed = run_with_artifacts.snapshots.get(identifier="Login/Form")
        assert f"[`Login/Form`]({comment_markdown._run_url(run_with_artifacts, repo)}?snapshot={changed.id})" in body

    def test_build_approval_comment_body_caps_at_eight_and_links_out(self, repo, mocker):
        mocker.patch.object(comment_markdown, "ArtifactStorage", self._fake_storage())

        run = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            commit_sha="manysnaps",
            branch="feature",
            pr_number=42,
            review_decision=ReviewDecision.HUMAN_APPROVED,
        )
        for i in range(11):
            RunSnapshot.objects.create(
                team_id=repo.team_id,
                run=run,
                identifier=f"Story/{i:02d}",
                result=SnapshotResult.CHANGED,
                baseline_artifact=self._mk_artifact(repo, f"base_{i}"),
                current_artifact=self._mk_artifact(repo, f"curr_{i}"),
            )

        body = comment_markdown._build_approval_comment_body(run, repo, None, add_images=True)

        # 8 of 11 rows rendered, the rest linked out
        assert body.count("<img") == 8 * 2  # before + after per shown row
        assert "…and 3 more" in body
        assert f"/visual_review/runs/{run.id})" in body

    def test_build_approval_comment_body_falls_back_to_text_without_storage(self, repo, run_with_artifacts, mocker):
        # Images requested, but storage yields no URL — fall back to the text summary.
        mocker.patch.object(comment_markdown, "ArtifactStorage", self._fake_storage(returns_url=False))

        body = comment_markdown._build_approval_comment_body(run_with_artifacts, repo, None, add_images=True)

        assert "<img" not in body
        assert "**Changed**" not in body
        # Still carries the textual summary
        assert "1 changed, 1 new, 1 removed." in body

    def test_build_approval_comment_body_omits_images_unless_opted_in(self, repo, run_with_artifacts, mocker):
        # add_images defaults false: the comment is always posted but stays a text summary.
        mocker.patch.object(comment_markdown, "ArtifactStorage", self._fake_storage())

        body = comment_markdown._build_approval_comment_body(run_with_artifacts, repo, None)

        assert "<img" not in body
        assert "**Changed**" not in body
        # The comment still summarizes what changed and links to the run
        assert "1 changed, 1 new, 1 removed." in body
        assert f"/visual_review/runs/{run_with_artifacts.id}" in body

    def test_image_cell_escapes_alt_and_src(self):
        # Both attributes are escaped so a quote in either can't break out of the tag
        cell = comment_markdown._image_cell('https://cdn.example/x?a="b', 'a"b')
        assert 'alt="a&quot;b"' in cell
        assert 'src="https://cdn.example/x?a=&quot;b"' in cell

    def test_image_cell_constrains_width_but_serves_full_resolution(self):
        # The cell shows a width-constrained image whose src is the full-resolution
        # original, so GitHub opens it at full size when clicked — no <a> wrapper needed.
        cell = comment_markdown._image_cell("https://cdn.example/full", "after")
        assert (
            cell == f'<img src="https://cdn.example/full" width="{comment_markdown._COMMENT_IMAGE_WIDTH}" alt="after">'
        )

    @parameterized.expand(
        [
            ("pipe", "a|b", "`a\\|b`"),  # pipes escaped so the cell stays intact
            ("backtick", "a`b", "`ab`"),  # backticks stripped so the code span isn't closed early
        ],
    )
    def test_snapshot_name_cell_escapes_markdown(self, _name, identifier, expected):
        assert comment_markdown._snapshot_name_cell(identifier) == expected

    def test_snapshot_name_cell_collapses_control_characters(self):
        # Newlines/tabs/carriage returns would otherwise break out of the table row
        cell = comment_markdown._snapshot_name_cell("a\nb\tc\rd")
        assert "\n" not in cell
        assert "\r" not in cell
        assert "\t" not in cell
        assert cell == "`a b c d`"

    def test_snapshot_name_cell_newline_cannot_inject_table_rows(self):
        # A pipe-laden payload across a newline stays a single escaped cell
        cell = comment_markdown._snapshot_name_cell("x\n| --- |")
        assert "\n" not in cell
        assert cell == "`x \\| --- \\|`"

    def test_comment_image_url_requests_seven_day_expiry(self, repo, mocker):
        # The 7-day expiry is load-bearing: GitHub's image proxy may fetch the URL
        # long after the comment is posted, so lock the behaviour with a test.
        captured = {}

        class _RecordingStorage:
            def __init__(self, repo_id):
                pass

            def get_presigned_download_url(self, content_hash, expiration=3600):
                captured["content_hash"] = content_hash
                captured["expiration"] = expiration
                return "https://cdn.example/x"

        mocker.patch.object(comment_markdown, "ArtifactStorage", _RecordingStorage)

        artifact = self._mk_artifact(repo, "h1")
        url = comment_markdown._comment_image_url(repo, artifact)

        assert url == "https://cdn.example/x"
        assert captured["content_hash"] == "h1"
        assert captured["expiration"] == 60 * 60 * 24 * 7 == 604800

    def test_comment_image_url_serves_full_resolution_not_thumbnail(self, repo, mocker):
        # Serve the original artifact, not the thumbnail, so clicking opens it full-size
        mocker.patch.object(comment_markdown, "ArtifactStorage", self._fake_storage())

        artifact = self._mk_artifact(repo, "full_h", with_thumbnail="thumb_h")
        url = comment_markdown._comment_image_url(repo, artifact)

        assert url is not None
        assert "full_h" in url
        assert "thumb_h" not in url
