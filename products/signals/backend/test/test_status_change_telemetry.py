import json
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction
from django.utils import timezone

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.models import User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import WorkClaim
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest
from products.signals.backend.pull_requests import apply_report_completion
from products.tasks.backend.models import Task


class TestCaptureStatusChangeAnalytics(BaseTest):
    """The post_save receiver is the server-side label stream for the inbox ranking model:
    it must fire exactly once per real status transition, from any surface, and never on
    creations or unrelated edits."""

    def _create_report(self, report_status=SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=report_status,
            title="Test report",
            summary="Test summary",
            signal_count=3,
            total_weight=2.5,
        )

    @parameterized.expand(
        [
            ("dismiss", SignalReport.Status.READY, SignalReport.Status.SUPPRESSED, {}),
            ("resolve_without_feedback", SignalReport.Status.READY, SignalReport.Status.RESOLVED, {}),
            ("snooze", SignalReport.Status.READY, SignalReport.Status.POTENTIAL, {"snooze_for": 5}),
        ]
    )
    def test_transition_emits_label_event_with_previous_and_new_status(
        self, _name, source_status, new_status, transition_kwargs
    ):
        report = self._create_report(report_status=source_status)
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                updated = report.transition_to(new_status, **transition_kwargs)
                report.save(update_fields=updated)
        assert mock_capture.call_count == 1
        kwargs = mock_capture.call_args.kwargs
        assert kwargs["event"] == "signal_report_status_changed"
        assert kwargs["distinct_id"] == str(self.team.uuid)
        assert kwargs["properties"]["report_id"] == str(report.id)
        assert kwargs["properties"]["previous_status"] == source_status
        assert kwargs["properties"]["status"] == new_status
        assert kwargs["properties"]["signal_count"] == 3
        assert kwargs["properties"]["total_weight"] == 2.5
        assert kwargs["properties"].get("resolution_reason") is None
        assert kwargs["properties"].get("dismissal_cause") is None

    @parameterized.expand([("earliest_visible", 0, True), ("later_visible", 1, False), ("never_visible", 2, False)])
    def test_label_marks_the_projects_first_visible_report(self, _name, index, expected):
        now = timezone.now()
        reports = [self._create_report() for _ in range(3)]
        SignalReport.objects.filter(id=reports[0].id).update(first_visible_at=now - timedelta(hours=2))
        SignalReport.objects.filter(id=reports[1].id).update(first_visible_at=now - timedelta(hours=1))
        SignalReport.objects.filter(id=reports[2].id).update(first_visible_at=None)
        report = SignalReport.objects.get(id=reports[index].id)
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                report.save(update_fields=report.transition_to(SignalReport.Status.RESOLVED))
        assert mock_capture.call_args.kwargs["properties"]["is_first_report"] is expected

    @parameterized.expand(
        [
            ("pipeline_without_actor", None, "system", None, None),
            ("user", "user", "user", "request", None),
            ("external_agent", "agent", "agent", "request", "codex"),
            ("task_with_no_creator", "orphan_task", "task", None, None),
            ("task_called_by_its_creator", "own_task", "task", "task_creator", None),
            ("task_named_by_another_caller", "borrowed_task", "task", None, None),
        ]
    )
    def test_label_carries_transition_actor(self, _name, actor_key, expected_kind, expected_source, expected_agent):
        task = Task.objects.create(
            team=self.team, title="Fix", description="", origin_product="signals", created_by=self.user
        )
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        actors = {
            None: None,
            "user": ArtefactAttribution.from_user(self.user.id),
            "agent": ArtefactAttribution.from_agent(self.user.id, "codex"),
            "orphan_task": ArtefactAttribution.from_task("11111111-1111-1111-1111-111111111111"),
            "own_task": ArtefactAttribution.from_task(str(task.id), request_user_id=self.user.id),
            "borrowed_task": ArtefactAttribution.from_task(str(task.id), request_user_id=other.id),
        }
        actor = actors[actor_key]
        report = self._create_report()
        if actor is not None:
            report._transition_actor = actor  # type: ignore[attr-defined]
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                report.save(update_fields=report.transition_to(SignalReport.Status.SUPPRESSED))
        kwargs = mock_capture.call_args.kwargs
        names_user = expected_source is not None
        assert kwargs["distinct_id"] == (self.user.distinct_id if names_user else str(self.team.uuid))
        actor_properties = {key: value for key, value in kwargs["properties"].items() if key.startswith("actor_")}
        assert actor_properties == {
            "actor_kind": expected_kind,
            "actor_user_uuid": str(self.user.uuid) if names_user else None,
            "actor_distinct_id": self.user.distinct_id if names_user else None,
            "actor_user_source": expected_source,
            "actor_agent": expected_agent,
            "actor_task_id": actor.task_id if actor is not None else None,
        }

    @parameterized.expand(
        [
            ("merge_credits_claim_holder", "merged", "claimer", "attacher", None, None, "claimer", "claim"),
            ("merge_credits_pr_attacher", "merged", None, "attacher", None, None, "attacher", "pr_attacher"),
            ("merge_credits_task_creator", "merged", None, None, "attacher", None, "attacher", "task_creator"),
            (
                "merge_credits_task_claim_as_task_creator",
                "merged",
                "task",
                None,
                "attacher",
                None,
                "attacher",
                "task_creator",
            ),
            ("merge_without_owner_names_nobody", "merged", None, None, None, None, None, None),
            ("close_credits_claim_holder", "closed", "claimer", None, None, None, "claimer", "claim"),
            (
                "merge_credits_merger_over_task_creator",
                "merged",
                None,
                None,
                "attacher",
                "linked",
                "merger",
                "pr_merger",
            ),
            (
                "merge_credits_merger_over_task_claim",
                "merged",
                "task",
                None,
                "attacher",
                "linked",
                "merger",
                "pr_merger",
            ),
            ("merge_credits_claim_holder_over_merger", "merged", "claimer", None, None, "linked", "claimer", "claim"),
            (
                "merge_credits_pr_attacher_over_merger",
                "merged",
                None,
                "attacher",
                None,
                "linked",
                "attacher",
                "pr_attacher",
            ),
            ("merge_ignores_a_login_another_account_holds", "merged", None, None, None, "other_account", None, None),
            ("merge_ignores_a_merger_with_no_github_id", "merged", None, None, None, "no_id", None, None),
        ]
    )
    def test_pr_state_transition_credits_work_owner_as_system_actor(
        self, _name, pr_state, claimer, attacher, task_creator, merged_by, expected, expected_source
    ):
        merger = User.objects.create_and_join(self.organization, "merger@example.com", None)
        UserSocialAuth.objects.create(user=merger, provider="github", uid="4242", extra_data={"login": "octo-merger"})
        users = {
            "claimer": User.objects.create_and_join(self.organization, "claimer@example.com", None),
            "attacher": self.user,
            "merger": merger,
            None: None,
        }
        report = self._create_report()
        task = (
            Task.objects.create(
                team=self.team, title="Fix", description="", origin_product="signals", created_by=users[task_creator]
            )
            if task_creator
            else None
        )
        if claimer == "task":
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type="work_claim",
                content=WorkClaim(display_name="Task").model_dump_json(),
                actor_kind="task",
                task_id=task.id if task else None,
            )
        elif claimer:
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type="work_claim",
                content=WorkClaim(display_name="Claimer").model_dump_json(),
                actor_kind="user",
                created_by=users[claimer],
            )
        pr = SignalReportPullRequest.objects.create(
            team=self.team,
            repository="example/app",
            number=1,
            url="https://github.com/example/app/pull/1",
            state=pr_state,
            merged_by_login="Octo-Merger" if merged_by else None,
            merged_by_github_id={"linked": 4242, "other_account": 9999}.get(merged_by),
        )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.PULL_REQUEST,
            pull_request=pr,
            created_by=users[attacher],
            task_id=task.id if task else None,
        )
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                apply_report_completion(report)
        [status_change] = [
            call.kwargs
            for call in mock_capture.call_args_list
            if call.kwargs["event"] == "signal_report_status_changed"
        ]
        properties = status_change["properties"]
        credited = users[expected]
        assert status_change["distinct_id"] == (credited.distinct_id if credited else str(self.team.uuid))
        assert properties["actor_kind"] == "system"
        assert properties["actor_user_uuid"] == (str(credited.uuid) if credited else None)
        assert properties["actor_distinct_id"] == (credited.distinct_id if credited else None)
        assert properties["actor_user_source"] == expected_source
        if pr_state == "merged":
            assert properties["resolution_reason"] == "pr_merged"
        else:
            assert properties["dismissal_cause"] == "pr_closed_without_merge"

    @parameterized.expand(
        [
            ("dismissal_includes_fresh_reason", SignalReport.Status.SUPPRESSED, False, "wontfix_irrelevant"),
            # A resolve that wrote no feedback of its own — the PR-merge webhook path — must not
            # adopt an unrelated earlier reason just because it landed inside the freshness window.
            # Resolve-with-feedback goes through the state API and is covered separately.
            ("webhook_resolve_excludes_fresh_reason", SignalReport.Status.RESOLVED, False, None),
            # Dismissal artefacts are append-only, so an old reason must not leak onto a later
            # transition — neither a resolve...
            ("stale_reason_excluded_from_resolve", SignalReport.Status.RESOLVED, True, None),
            # ...nor a later feedback-less dismissal (the state API only writes a new dismissal
            # artefact when the user actually gave a reason or note).
            ("stale_reason_excluded_from_new_dismissal", SignalReport.Status.SUPPRESSED, True, None),
            # A pipeline transition never carries dismissal feedback, however fresh the artefact.
            ("pipeline_transition_excludes_reason", SignalReport.Status.CANDIDATE, False, None),
        ]
    )
    def test_label_snapshots_latest_classification_artefacts(
        self, _name, new_status, backdate_dismissal, expected_dismissal_reason
    ):
        report = self._create_report()
        for artefact_type, content in [
            (SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT, {"priority": "P1"}),
            (SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT, {"actionability": "immediately_actionable"}),
            (SignalReportArtefact.ArtefactType.DISMISSAL, {"reason": "wontfix_irrelevant"}),
        ]:
            SignalReportArtefact.objects.create(
                team=self.team, report=report, type=artefact_type, content=json.dumps(content)
            )
        if backdate_dismissal:
            SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.DISMISSAL).update(
                created_at=timezone.now() - timedelta(hours=1)
            )
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                updated = report.transition_to(new_status)
                report.save(update_fields=updated)
        props = mock_capture.call_args.kwargs["properties"]
        assert props["priority"] == "P1"
        assert props["actionability"] == "immediately_actionable"
        assert props["dismissal_reason"] == expected_dismissal_reason

    def test_transient_intermediate_transition_in_one_transaction_is_collapsed(self):
        report = self._create_report(report_status=SignalReport.Status.IN_PROGRESS)
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    report.save(update_fields=report.transition_to(SignalReport.Status.READY, title="t", summary="s"))
                    report.save(update_fields=report.transition_to(SignalReport.Status.CANDIDATE))
        assert mock_capture.call_count == 1
        props = mock_capture.call_args.kwargs["properties"]
        # The committed transition, not a phantom hop through the never-committed READY state.
        assert props["previous_status"] == SignalReport.Status.IN_PROGRESS
        assert props["status"] == SignalReport.Status.CANDIDATE

    @parameterized.expand(
        [
            ("full_save_without_status_change", SignalReport.Status.READY, None),
            ("update_fields_without_status", SignalReport.Status.READY, ["title"]),
        ]
    )
    def test_non_transition_save_does_not_emit(self, _name, report_status, update_fields):
        report = self._create_report(report_status=report_status)
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                report.title = "edited"
                report.save(update_fields=update_fields)
        mock_capture.assert_not_called()

    def test_report_creation_does_not_emit(self):
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                self._create_report()
        mock_capture.assert_not_called()
