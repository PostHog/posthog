import json
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.apps import apps
from django.test import SimpleTestCase

from asgiref.sync import async_to_sync, sync_to_async
from parameterized import parameterized
from rest_framework import status
from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership

from products.signals.backend.artefact_schemas import Priority, PriorityAssessment, SuggestedReviewers, TaskRunArtefact
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalSourceConfig
from products.signals.backend.scout_harness.tools.report import (
    MAX_SUGGESTED_REVIEWERS,
    REPORT_KIND_FINDING,
    REPORT_KIND_SELF_IMPROVEMENT,
    EditReportResult,
    InvalidScoutReportError,
    ReportChartInput,
    ReportEvidence,
    ReviewerInput,
    _build_suggested_reviewers,
    _capture_report_edited,
    _extract_linked_repository,
    _report_classification_props,
    _resolve_report_repository,
    _wants_repo_selection,
)
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeResponse
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run
from products.skills.backend.models.skills import LLMSkill, LLMSkillOwner
from products.tasks.backend.facade.repo_selection import RepoSelectionResult

JUDGE_PATH = "products.signals.backend.scout_report.judge.judge_report_safety"
EMBED_PATH = "products.signals.backend.scout_report.persistence.emit_embedding_request"
# Patched at its source module so the lazy import inside `_maybe_autostart_report` picks up the mock.
AUTOSTART_PATH = "products.signals.backend.auto_start.maybe_autostart_from_report_artefacts"
CAPTURE_PATH = "products.signals.backend.scout_harness.tools.report.posthoganalytics.capture"
# The customer-facing copy lands in the scout's own team project via capture_internal (a network boundary).
CAPTURE_INTERNAL_PATH = "products.signals.backend.scout_harness.tools.report.capture_internal"
CONNECTED_REPOS_PATH = "products.signals.backend.scout_harness.tools.report._connected_repositories"
_CONNECTED_REPOS = ["acme/widgets", "acme/gadgets"]
REPORT_TOOLS = ["emit_report", "edit_report"]


def _safe_judge(choice: bool = True, explanation: str = ""):
    return patch(JUDGE_PATH, new=AsyncMock(return_value=SafetyJudgeResponse(choice=choice, explanation=explanation)))


class TestScoutReportAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        SignalSourceConfig.objects.get_or_create(
            team=self.team,
            source_product="signals_scout",
            source_type="cross_source_issue",
            defaults={"enabled": True},
        )
        # The report channel is opt-in: `_make_run` defaults to skill `signals-scout-general` v1, so the
        # gate needs a matching LLMSkill row that lists the report tools in `allowed_tools`.
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-general",
            description="opted-in scout",
            body="# scout",
            allowed_tools=REPORT_TOOLS,
        )
        # The report channel requires `signal_scout_report:write`, granted only by the
        # `signals_scout_reports` posture (mirrors the runner's opt-in posture selection).
        _authenticate_as_scout(self, scopes="signals_scout_reports")
        # The customer-facing event fans out through capture_internal (a network call to capture-rs).
        # Keep it inert by default so emit/edit tests don't hit the network; the two dedicated tests
        # assert against this mock.
        self.capture_internal_mock = patch(CAPTURE_INTERNAL_PATH).start()
        self.addCleanup(patch.stopall)

    def _emit_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/emit-report/"

    def _edit_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/edit-report/"

    def _payload(self, **overrides) -> dict:
        body: dict = {
            "title": "Checkout p99 regressed after 4.2",
            "summary": "The /checkout endpoint p99 doubled after the 4.2 deploy.",
            "evidence": [{"description": "p99 doubled on /checkout", "source_id": "obs-1"}],
            "actionability_explanation": "clear fix in the checkout handler",
            "actionability": "immediately_actionable",
        }
        body.update(overrides)
        return body

    def _seed_skill_owner(self, login: str, skill_name: str = "signals-scout-general") -> User:
        user = User.objects.create(email=f"{login}@example.com")
        OrganizationMembership.objects.create(user=user, organization=self.organization)
        UserSocialAuth.objects.create(user=user, provider="github", uid=f"gh-{login}", extra_data={"login": login})
        LLMSkillOwner.objects.for_team(self.team.id).create(team=self.team, skill_name=skill_name, user=user)
        return user

    def _reviewer_logins(self, report_id: str) -> list[str]:
        artefact = self._latest_artefact(report_id, SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS)
        assert artefact is not None
        return [entry["github_login"] for entry in json.loads(artefact.content)]

    def test_emit_report_authors_ready_report(self) -> None:
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH) as embed_mock:
            response = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["emitted"] is True
        assert body["report_status"] == SignalReport.Status.READY
        assert body["skipped_reason"] is None
        assert SignalReport.objects.filter(id=body["report_id"], team=self.team).exists()
        embed_mock.assert_called_once()

    def test_report_emit_and_edit_enqueue_configured_slack_destination_after_commit(self) -> None:
        run = _make_run(self.team)
        config = run.scout_config
        assert config is not None
        config.output_destinations = {"slack": {"integration_id": 17, "channel": "CSCOUTS|#scout-findings"}}
        config.save(update_fields=["output_destinations"])

        with (
            _safe_judge(),
            patch(EMBED_PATH),
            patch(
                "products.signals.backend.scout_harness.slack_delivery_queue.enqueue_scout_slack_delivery"
            ) as enqueue,
            self.captureOnCommitCallbacks(execute=True),
        ):
            emitted = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
            report_id = emitted.json()["report_id"]
            edited = self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": report_id, "append_note": "Re-validated on the next run"},
                format="json",
            )
            rewritten = self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": report_id, "summary": "Rewritten summary", "append_note": "And a note"},
                format="json",
            )
            prompted = self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": report_id, "suggested_prompts": ["Which teams are affected?"]},
                format="json",
            )

        assert emitted.status_code == status.HTTP_200_OK, emitted.json()
        assert edited.status_code == status.HTTP_200_OK, edited.json()
        assert rewritten.status_code == status.HTTP_200_OK, rewritten.json()
        assert prompted.status_code == status.HTTP_200_OK, prompted.json()
        # The prompt-only edit delivers nothing: the questions render in the inbox and nowhere in the
        # Slack message, so posting it would repeat the report the channel already has, byte for byte.
        assert enqueue.call_count == 3
        for call in enqueue.call_args_list:
            assert call.kwargs["team_id"] == self.team.id
            assert call.kwargs["output_type"] == "report"
            assert call.kwargs["output_id"] == report_id
            assert call.kwargs["run_id"] == str(run.id)
            assert call.kwargs["integration_id"] == 17
            assert call.kwargs["channel"] == "CSCOUTS|#scout-findings"
        # Emit deliveries are keyed on the report id (idempotent); each edit gets its own id.
        assert enqueue.call_args_list[0].kwargs["delivery_id"] == report_id
        assert enqueue.call_args_list[1].kwargs["delivery_id"] != report_id
        # Only the note-only edit delivers as a note; an emit and a content rewrite post the report
        # message, even when the rewrite also appended a note.
        assert enqueue.call_args_list[0].kwargs["edit_note"] is None
        assert enqueue.call_args_list[1].kwargs["edit_note"] == "Re-validated on the next run"
        assert enqueue.call_args_list[2].kwargs["edit_note"] is None

    def test_emit_report_unsafe_suppresses_but_returns_id(self) -> None:
        run = _make_run(self.team)
        config = run.scout_config
        assert config is not None
        config.output_destinations = {"slack": {"integration_id": 17, "channel": "CSCOUTS|#scout-findings"}}
        config.save(update_fields=["output_destinations"])
        with (
            _safe_judge(choice=False, explanation="prompt injection"),
            patch(EMBED_PATH),
            patch("products.signals.backend.scout_harness.tools.report.queue_configured_scout_slack_delivery") as queue,
        ):
            response = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["emitted"] is False
        assert body["report_status"] == SignalReport.Status.SUPPRESSED
        assert body["safety_explanation"] == "prompt injection"
        assert body["report_id"] is not None
        queue.assert_not_called()

    def test_edit_of_suppressed_report_does_not_enqueue_slack_delivery(self) -> None:
        run = _make_run(self.team)
        config = run.scout_config
        assert config is not None
        config.output_destinations = {"slack": {"integration_id": 17, "channel": "CSCOUTS|#scout-findings"}}
        config.save(update_fields=["output_destinations"])
        with (
            _safe_judge(choice=False, explanation="prompt injection"),
            patch(EMBED_PATH),
            patch("products.signals.backend.scout_harness.tools.report.queue_configured_scout_slack_delivery") as queue,
        ):
            emitted = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
            report_id = emitted.json()["report_id"]
            edited = self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": report_id, "append_note": "note on a suppressed report"},
                format="json",
            )
        assert emitted.status_code == status.HTTP_200_OK, emitted.json()
        assert edited.status_code == status.HTTP_200_OK, edited.json()
        queue.assert_not_called()

    def test_emit_report_skips_when_ai_not_approved(self) -> None:
        # Preflight gate: a report is never authored for an org that hasn't approved AI processing.
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        run = _make_run(self.team)
        with _safe_judge() as judge_mock, patch(EMBED_PATH) as embed_mock:
            response = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["skipped_reason"] == "ai_processing_not_approved"
        assert body["report_id"] is None
        # A gate-skipped report must hand back an actionable next step, not a bare reason code —
        # otherwise the scout is blocked with a dead end and loses the whole run's work.
        assert body["remediation"] and "AI data processing" in body["remediation"]
        # Gate stops before judging or persisting.
        judge_mock.assert_not_awaited()
        embed_mock.assert_not_called()
        assert SignalReport.objects.filter(team=self.team).count() == 0

    def test_emit_report_rejects_non_in_progress_run(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = _make_run(self.team, task_run_status=TaskRun.Status.COMPLETED)
        response = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_emit_report_denied_when_skill_not_opted_in(self) -> None:
        # Opt-in is enforced server-side: a run whose skill omits `emit_report` from allowed_tools is
        # rejected even though the MCP token's scope can reach the endpoint.
        LLMSkill.objects.create(
            team=self.team, name="signals-scout-noreport", description="not opted in", body="# x", allowed_tools=[]
        )
        run = _make_run(self.team, skill_name="signals-scout-noreport")
        with _safe_judge(), patch(EMBED_PATH) as embed_mock:
            response = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        embed_mock.assert_not_called()
        assert SignalReport.objects.filter(team=self.team).count() == 0

    def test_emit_report_rejects_invalid_actionability(self) -> None:
        run = _make_run(self.team)
        response = self.client.post(
            self._emit_url(str(run.id)), data=self._payload(actionability="made_up"), format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_edit_report_updates_title_and_appends_note(self) -> None:
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH):
            created = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json").json()
        response = self.client.post(
            self._edit_url(str(run.id)),
            data={"report_id": created["report_id"], "title": "new title", "append_note": "re-validated"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert "title" in response.json()["updated_fields"]
        assert response.json()["note_appended"] is True
        assert SignalReport.objects.get(id=created["report_id"]).title == "new title"
        # The run records which report it edited so "which reports did this run touch?" is a column lookup.
        run.refresh_from_db()
        assert run.edited_report_ids == [created["report_id"]]

    def test_edit_report_records_edited_report_once_across_repeated_edits(self) -> None:
        # The edited tally is set-membership, not a per-edit log: a run editing the same report twice
        # records it once (the per-edit detail lives in the report's artefact log).
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH):
            created = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json").json()
        report_id = created["report_id"]
        for title in ("first edit", "second edit"):
            response = self.client.post(
                self._edit_url(str(run.id)), data={"report_id": report_id, "title": title}, format="json"
            )
            assert response.status_code == status.HTTP_200_OK, response.json()
        run.refresh_from_db()
        assert run.edited_report_ids == [report_id]
        # The run link on the report's work log dedupes the same way: emit linked the run once, and
        # the two edits must not append duplicate `task_run` rows for it.
        assert (
            SignalReportArtefact.objects.filter(
                report_id=report_id, type=SignalReportArtefact.ArtefactType.TASK_RUN
            ).count()
            == 1
        )

    def test_edit_report_links_editing_run_to_report_it_did_not_author(self) -> None:
        # `edit_report` can target any inbox report (pipeline-authored included) — the edit must link
        # the editing scout run on the report's work log so its transcript is reachable from the
        # report, not just from the run-side `edited_report_ids` tally. Per-task dedupe: a second
        # run editing the same report gets its own link.
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="pipeline report")
        first_run = _make_run(self.team)
        second_run = _make_run(self.team)
        for i, run in enumerate((first_run, second_run)):
            response = self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": str(report.id), "append_note": f"scout context {i}"},
                format="json",
            )
            assert response.status_code == status.HTTP_200_OK, response.json()
        artefacts = SignalReportArtefact.objects.filter(
            report_id=report.id, type=SignalReportArtefact.ArtefactType.TASK_RUN
        ).order_by("created_at")
        contents = [TaskRunArtefact.model_validate_json(a.content) for a in artefacts]
        assert [(c.task_id, c.run_id) for c in contents] == [
            (str(run.task_run.task_id), str(run.task_run_id)) for run in (first_run, second_run)
        ]
        assert all(c.product == "signals" and c.type == "scout" for c in contents)

    def test_edit_report_fails_closed_on_cross_team_report(self) -> None:
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        other_report = SignalReport.objects.create(team=other_team, status=SignalReport.Status.READY, title="theirs")
        run = _make_run(self.team)
        response = self.client.post(
            self._edit_url(str(run.id)),
            data={"report_id": str(other_report.id), "title": "hijacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert SignalReport.objects.get(id=other_report.id).title == "theirs"

    def _latest_artefact(self, report_id: str, artefact_type: str) -> SignalReportArtefact | None:
        return (
            SignalReportArtefact.objects.filter(report_id=report_id, type=artefact_type).order_by("-created_at").first()
        )

    @parameterized.expand(
        [
            ("inferred_target_follows_the_rewrite", None, "acme/gadgets"),
            # A repo the scout named is a decision, not a reading of the prose, so a rewrite never moves it.
            ("scout_named_target_is_not_overturned", "acme/widgets", "acme/widgets"),
        ]
    )
    def test_content_rewrite_refreshes_only_an_inferred_repository(
        self, _name: str, repository: str | None, expected: str
    ) -> None:
        run = _make_run(self.team)
        payload = self._payload(summary="Traced to https://github.com/acme/widgets/pull/7")
        if repository is not None:
            payload["repository"] = repository
        with (
            _safe_judge(),
            patch(EMBED_PATH),
            patch(CONNECTED_REPOS_PATH, return_value=_CONNECTED_REPOS),
        ):
            created = self.client.post(self._emit_url(str(run.id)), data=payload, format="json").json()
            response = self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": created["report_id"], "summary": "Actually https://github.com/acme/gadgets/pull/2"},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        artefact = self._latest_artefact(created["report_id"], SignalReportArtefact.ArtefactType.REPO_SELECTION)
        assert artefact is not None
        assert json.loads(artefact.content)["repository"] == expected

    def test_combined_rewrite_and_reviewer_edit_autostarts_on_the_refreshed_repository(self) -> None:
        # One edit can both move the report onto a new repository and add the reviewer that lets an
        # inferred target autostart. Autostart reads the selection as it stands and is idempotent, so
        # refreshing after it would open the implementation task against the repository the same edit
        # just replaced, with no second chance to correct it.
        run = _make_run(self.team)
        payload = self._payload(summary="Traced to https://github.com/acme/widgets/pull/7")
        with (
            _safe_judge(),
            patch(EMBED_PATH),
            patch(CONNECTED_REPOS_PATH, return_value=_CONNECTED_REPOS),
        ):
            created = self.client.post(self._emit_url(str(run.id)), data=payload, format="json").json()
            repository_at_autostart: list[str | None] = []

            async def _capture(**kwargs) -> None:
                artefact = await sync_to_async(self._latest_artefact)(
                    created["report_id"], SignalReportArtefact.ArtefactType.REPO_SELECTION
                )
                repository_at_autostart.append(json.loads(artefact.content)["repository"] if artefact else None)

            with patch(AUTOSTART_PATH, new=AsyncMock(side_effect=_capture)) as autostart:
                response = self.client.post(
                    self._edit_url(str(run.id)),
                    data={
                        "report_id": created["report_id"],
                        "summary": "Actually https://github.com/acme/gadgets/pull/2",
                        "suggested_reviewers": [{"github_login": "octocat"}],
                    },
                    format="json",
                )
        assert response.status_code == status.HTTP_200_OK, response.json()
        autostart.assert_awaited_once()
        assert repository_at_autostart == ["acme/gadgets"]

    def test_emit_report_writes_autostart_artefacts(self) -> None:
        # The autostart inputs the scout supplies become the same artefacts a pipeline report carries,
        # which is what `maybe_autostart_from_report_artefacts` reads to open a draft PR. Repo is normalized.
        run = _make_run(self.team)
        payload = self._payload(
            repository="PostHog/PostHog",
            priority="P1",
            priority_explanation="429 users hit this in 2h",
            suggested_reviewers=[{"github_login": "octocat"}, {"github_login": "hubot"}],
        )
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()):
            response = self.client.post(self._emit_url(str(run.id)), data=payload, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        report_id = response.json()["report_id"]
        repo = self._latest_artefact(report_id, SignalReportArtefact.ArtefactType.REPO_SELECTION)
        assert repo is not None and '"posthog/posthog"' in repo.content
        assert self._latest_artefact(report_id, SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT) is not None
        reviewers = self._latest_artefact(report_id, SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS)
        assert reviewers is not None and "octocat" in reviewers.content

    def test_emit_report_fires_autostart_when_surfaced(self) -> None:
        run = _make_run(self.team)
        payload = self._payload(repository="PostHog/PostHog", priority="P1", priority_explanation="big blast radius")
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()) as autostart:
            response = self.client.post(self._emit_url(str(run.id)), data=payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        autostart.assert_awaited_once()
        assert autostart.await_args is not None
        assert autostart.await_args.kwargs["report_id"] == response.json()["report_id"]

    def test_edit_report_sets_reviewers_and_reruns_autostart(self) -> None:
        # The routing rescue: a report that surfaced with no reviewer can have one set via edit_report,
        # which writes the suggested_reviewers artefact and re-fires autostart (so a report that already
        # has a repo + priority but lacked a qualifying reviewer can now open a draft PR).
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()):
            created = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json").json()
        report_id = created["report_id"]
        with patch(AUTOSTART_PATH, new=AsyncMock()) as autostart:
            response = self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": report_id, "suggested_reviewers": [{"github_login": "OctoCat"}]},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["reviewers_set"] is True
        reviewers = self._latest_artefact(report_id, SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS)
        assert reviewers is not None and "octocat" in reviewers.content  # canonicalized lowercase
        autostart.assert_awaited_once()
        run.refresh_from_db()
        assert run.edited_report_ids == [report_id]

    def test_edit_report_reason_only_reroute_keeps_commit_evidence(self) -> None:
        # A scout re-route rebuilds entries from logins, so without merge-forward a reason-only edit
        # would wipe the pipeline-derived relevant_commits (and prior name) the precedent-weighing
        # guidance runs on. Kept logins must keep their evidence; new logins start clean.
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()):
            created = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json").json()
        report_id = created["report_id"]
        commit = {"sha": "abc123f", "url": "https://example.com/c/abc123f", "reason": "touched the hot path"}
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=report_id,
            content=SuggestedReviewers.model_validate(
                [{"github_login": "alice", "github_name": "Alice A.", "relevant_commits": [commit]}]
            ),
            attribution=ArtefactAttribution.system(),
            reevaluate_autostart=False,
        )
        with patch(AUTOSTART_PATH, new=AsyncMock()):
            response = self.client.post(
                self._edit_url(str(run.id)),
                data={
                    "report_id": report_id,
                    "suggested_reviewers": [
                        {"github_login": "alice", "reason": "confirmed owner via human correction"},
                        {"github_login": "dave"},
                    ],
                },
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        artefact = self._latest_artefact(report_id, SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS)
        assert artefact is not None
        stored = {entry["github_login"]: entry for entry in json.loads(artefact.content)}
        assert stored["alice"]["relevant_commits"] == [commit]
        assert stored["alice"]["github_name"] == "Alice A."
        assert stored["alice"]["reason"] == "confirmed owner via human correction"
        assert stored["dave"]["relevant_commits"] == []

    def test_edit_uses_scout_picks_verbatim_and_stamps_owners_on_any_report(self) -> None:
        # No injection: an edit replaces reviewers with the scout's picks in order, even on a report
        # the skill didn't author. But a picked *owner* is stamped `is_skill_owner=True` on any report
        # the scout edits, so a steered scout can't launder autostart identity through a foreign one.
        self._seed_skill_owner("scoutowner")
        run = _make_run(self.team)
        foreign = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="pipeline report")
        with patch(AUTOSTART_PATH, new=AsyncMock()):
            response = self.client.post(
                self._edit_url(str(run.id)),
                data={
                    "report_id": str(foreign.id),
                    "suggested_reviewers": [{"github_login": "scoutowner"}, {"github_login": "picked"}],
                },
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        artefact = self._latest_artefact(str(foreign.id), SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS)
        assert artefact is not None
        stored = {e["github_login"]: e for e in json.loads(artefact.content)}
        assert self._reviewer_logins(str(foreign.id)) == ["scoutowner", "picked"]
        assert stored["scoutowner"]["is_skill_owner"] is True
        assert stored["picked"]["is_skill_owner"] is False

    def test_edit_readding_former_owner_clears_owner_provenance(self) -> None:
        # A former owner re-added as a normal reviewer must lose `is_skill_owner`: provenance is
        # recomputed from the live owner set on every reviewers-setting edit, and carrying the stale
        # flag forward would keep excluding them from autostart identity selection.
        self._seed_skill_owner("formerowner")
        run = _make_run(self.team)
        # The scout picks the (then-)owner as reviewer; the pick is stamped as owner provenance.
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()):
            created = self.client.post(
                self._emit_url(str(run.id)),
                data=self._payload(suggested_reviewers=[{"github_login": "formerowner"}]),
                format="json",
            ).json()
        report_id = created["report_id"]
        artefact = self._latest_artefact(report_id, SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS)
        assert artefact is not None
        seeded_entry = json.loads(artefact.content)[0]
        assert (seeded_entry["github_login"], seeded_entry["is_skill_owner"]) == ("formerowner", True)

        LLMSkillOwner.objects.for_team(self.team.id).filter(skill_name="signals-scout-general").delete()
        with patch(AUTOSTART_PATH, new=AsyncMock()):
            response = self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": report_id, "suggested_reviewers": [{"github_login": "formerowner"}]},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        artefact = self._latest_artefact(report_id, SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS)
        assert artefact is not None
        stored = {entry["github_login"]: entry for entry in json.loads(artefact.content)}
        assert stored["formerowner"]["is_skill_owner"] is False

    def test_scout_token_skill_fetch_hides_owners_off_the_report_channel(self) -> None:
        # The run prompt gates its owners line on the report channel because owner identities are
        # member PII a signal-channel scout has no routing use for — but the sandbox token could
        # still read them straight off skill-get. The skills serializer applies the same gate to
        # scout callers; a report-channel skill keeps its owners since they route its reports.
        owner = self._seed_skill_owner("reportowner")
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-quiet",
            description="signal-channel scout",
            body="# scout",
            allowed_tools=["emit_signal"],
        )
        self._seed_skill_owner("quietowner", skill_name="signals-scout-quiet")

        quiet = self.client.get(f"/api/projects/{self.team.id}/llm_skills/name/signals-scout-quiet/")
        assert quiet.status_code == status.HTTP_200_OK, quiet.json()
        assert quiet.json()["owners"] == []

        report_channel = self.client.get(f"/api/projects/{self.team.id}/llm_skills/name/signals-scout-general/")
        assert report_channel.status_code == status.HTTP_200_OK, report_channel.json()
        assert [entry["email"] for entry in report_channel.json()["owners"]] == [owner.email]

    def test_edit_report_unresolvable_reviewer_does_not_partially_mutate(self) -> None:
        # A combined edit (title + a bad reviewer) must fail atomically: reviewers resolve before any
        # write, so an unresolvable user_uuid 400s without the title change leaking through.
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH):
            created = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json").json()
        report_id = created["report_id"]
        original_title = SignalReport.objects.get(id=report_id).title
        response = self.client.post(
            self._edit_url(str(run.id)),
            data={
                "report_id": report_id,
                "title": "should not stick",
                "suggested_reviewers": [{"user_uuid": str(uuid4())}],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert SignalReport.objects.get(id=report_id).title == original_title

    def test_emit_report_skips_autostart_and_artefacts_when_suppressed(self) -> None:
        # An unsafe report is suppressed — it must not write autostart inputs or try to open a PR.
        run = _make_run(self.team)
        payload = self._payload(repository="PostHog/PostHog", priority="P1", priority_explanation="x")
        with (
            _safe_judge(choice=False, explanation="unsafe"),
            patch(EMBED_PATH),
            patch(AUTOSTART_PATH, new=AsyncMock()) as autostart,
        ):
            response = self.client.post(self._emit_url(str(run.id)), data=payload, format="json")
        assert response.json()["emitted"] is False
        autostart.assert_not_awaited()
        assert (
            self._latest_artefact(response.json()["report_id"], SignalReportArtefact.ArtefactType.REPO_SELECTION)
            is None
        )

    @parameterized.expand(
        [
            ("surfaced", True, True, "surfaced"),
            ("suppressed", False, True, "suppressed"),
            ("gate_skipped", True, False, "gate_skipped"),
        ]
    )
    def test_emit_report_captures_lifecycle_event(
        self, _name: str, safe: bool, ai_approved: bool, expected_outcome: str
    ) -> None:
        # The `signals_scout_report_emitted` event is the report channel's observability funnel — its
        # `outcome` must classify every terminal path (surfaced / suppressed / gate_skipped) correctly,
        # carry the run/report ids that join it to the run lifecycle events, and (parity with the signal
        # channel's `signal_emitted`) carry the report's content on every outcome so internal consumers can
        # act on the report's substance, not just its ids.
        if not ai_approved:
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        run = _make_run(self.team)
        with (
            _safe_judge(choice=safe, explanation="" if safe else "unsafe"),
            patch(EMBED_PATH),
            patch(AUTOSTART_PATH, new=AsyncMock()),
            patch(CAPTURE_PATH) as capture,
        ):
            body = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json").json()
        event = next(c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_report_emitted")
        props = event.kwargs["properties"]
        assert props["outcome"] == expected_outcome
        assert props["run_id"] == str(run.id)
        assert props["report_id"] == body["report_id"]
        assert props["evidence_count"] == 1
        # Content parity with `signal_emitted` — present on every outcome, including gate_skipped.
        assert props["title"] == "Checkout p99 regressed after 4.2"
        assert props["summary"] == "The /checkout endpoint p99 doubled after the 4.2 deploy."
        assert props["actionability"] == "immediately_actionable"
        # A regular finding classifies as such (the self-improvement path has its own test below).
        assert props["report_kind"] == REPORT_KIND_FINDING
        assert props["is_self_improvement_report"] is False
        # The customer-facing copy must land in the team's *own* project (their token), never create a
        # person (it's the scout's output, not a user action), and carry a report deep link when a report
        # exists — that link is what a CDP Slack destination templates the message from.
        forward = next(
            c for c in self.capture_internal_mock.call_args_list if c.kwargs["event_name"] == "$scout_report_emitted"
        )
        assert forward.kwargs["token"] == self.team.api_token
        assert forward.kwargs["process_person_profile"] is False
        expected_url = None if expected_outcome == "gate_skipped" else f"/inbox/reports/{body['report_id']}"
        if expected_url is None:
            assert forward.kwargs["properties"]["report_url"] is None
        else:
            assert forward.kwargs["properties"]["report_url"].endswith(expected_url)

    def test_edit_report_captures_edited_event(self) -> None:
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH), patch(CAPTURE_PATH) as capture:
            created = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json").json()
            self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": created["report_id"], "title": "new title", "append_note": "re-validated"},
                format="json",
            )
        event = next(c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_report_edited")
        props = event.kwargs["properties"]
        assert props["report_id"] == created["report_id"]
        assert "title" in props["updated_fields"]
        assert props["note_appended"] is True
        # The edit event carries the content the edit applied; an untouched field (summary) stays None.
        assert props["title"] == "new title"
        assert props["note"] == "re-validated"
        assert props["summary"] is None
        assert props["is_self_improvement_report"] is False
        # The edit also fans out to the team's own project, deep-linking the edited report.
        forward = next(
            c for c in self.capture_internal_mock.call_args_list if c.kwargs["event_name"] == "$scout_report_edited"
        )
        assert forward.kwargs["token"] == self.team.api_token
        assert forward.kwargs["process_person_profile"] is False
        assert forward.kwargs["properties"]["report_url"].endswith(f"/inbox/reports/{created['report_id']}")

    def test_self_improvement_report_classified_on_emit_and_edit(self) -> None:
        # Classification must ride both lifecycle events: stamped from the authored title on emit, and
        # resolved from the *stored* report title on a note-only edit (the payload carries no title) —
        # the path that breaks if `_do_edit_report` stops resolving the report's effective title.
        run = _make_run(self.team)
        title = "Scout self-improvement: signals-scout-general – dead quick-close trigger"
        with _safe_judge(), patch(EMBED_PATH), patch(CAPTURE_PATH) as capture:
            created = self.client.post(self._emit_url(str(run.id)), data=self._payload(title=title), format="json")
            self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": created.json()["report_id"], "append_note": "re-confirmed on this run"},
                format="json",
            )
        emitted = next(c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_report_emitted")
        edited = next(c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_report_edited")
        for props in (emitted.kwargs["properties"], edited.kwargs["properties"]):
            assert props["report_kind"] == REPORT_KIND_SELF_IMPROVEMENT
            assert props["is_self_improvement_report"] is True

    def test_reviewer_edit_event_uuid_keys_on_reviewers(self) -> None:
        # A reviewer-only edit carries no `updated_fields` and no title/summary/note, so two distinct
        # reviewer corrections to the same report in one run would hash to one `event_uuid` and ingestion
        # would collapse the later routing change. The uuid must key on the reviewer identity too — while
        # an identical retried reviewer edit still stays one event (idempotent).
        run = _make_run(self.team)
        result = EditReportResult(report_id=str(uuid4()), updated_fields=[], note_appended=False, reviewers_set=True)

        def forward(reviewers: list[ReviewerInput]) -> str:
            with patch(CAPTURE_PATH):
                captured = _capture_report_edited(
                    team=self.team,
                    run=run,
                    result=result,
                    title=None,
                    summary=None,
                    note=None,
                    suggested_reviewers=reviewers,
                )
            assert captured is not None
            return captured.event_uuid

        alice = forward([ReviewerInput(github_login="alice")])
        bob = forward([ReviewerInput(github_login="bob")])
        assert alice != bob
        assert alice == forward([ReviewerInput(github_login="alice")])

    def test_chart_edit_event_uuid_keys_on_charts(self) -> None:
        # Same collision class as the reviewer case above: charts are a valid sole input to an edit, so
        # two chart-only edits to one report in a run carry no `updated_fields` and no title/summary/note.
        # Without keying on the chart ids they hash to one `event_uuid` and ingestion drops the second —
        # the team never sees that chart land. An identical retried chart edit must still stay one event.
        run = _make_run(self.team)
        result = EditReportResult(report_id=str(uuid4()), updated_fields=[], note_appended=False, charts_set=1)

        def forward(charts: list[ReportChartInput]) -> str:
            with patch(CAPTURE_PATH):
                captured = _capture_report_edited(
                    team=self.team,
                    run=run,
                    result=result,
                    title=None,
                    summary=None,
                    note=None,
                    charts=charts,
                )
            assert captured is not None
            return captured.event_uuid

        def chart(chart_id: str) -> ReportChartInput:
            return ReportChartInput(chart_id=chart_id, title="Daily signups", query={"kind": "InsightVizNode"})

        signups = forward([chart("signups-drop")])
        churn = forward([chart("churn-spike")])
        assert signups != churn
        assert signups == forward([chart("signups-drop")])
        # Re-supplying an id is how a scout refreshes a chart to a newer window, so the key has to cover
        # content too — on ids alone the refresh collapses into the original and the team never hears it.
        refreshed = ReportChartInput(
            chart_id="signups-drop", title="Daily signups", query={"kind": "InsightVizNode", "full": True}
        )
        assert forward([refreshed]) != signups
        # Title and caption are scout-authored free text, so a key that joins them on a separator lets
        # a colon move across the boundary and hash the same — a real refresh silently deduped away.
        node = {"kind": "InsightVizNode"}
        title_carries_it = ReportChartInput(chart_id="signups-drop", title="Signups: daily", caption="EU", query=node)
        caption_carries_it = ReportChartInput(chart_id="signups-drop", title="Signups", caption="daily: EU", query=node)
        assert forward([title_carries_it]) != forward([caption_carries_it])
        # Charts render in the order they were sent, so an edit that only reorders them changes what a
        # reader sees. Sorting the keys hashes that edit the same as the one before it and ingestion
        # drops it — unlike reviewers, where order carries nothing and sorting is what makes a retry key.
        signups_chart, churn_chart = chart("signups-drop"), chart("churn-spike")
        assert forward([signups_chart, churn_chart]) != forward([churn_chart, signups_chart])

    @parameterized.expand(
        [
            ("omitted", {}, 1, None),
            ("null", {"charts": None}, 1, None),
            ("empty_list", {"charts": []}, 0, 0),
        ]
    )
    def test_edit_charts_distinguishes_untouched_from_cleared(
        self, _name: str, chart_field: dict, expected_stored: int, expected_charts_set: int | None
    ) -> None:
        # A scout that no longer stands behind a chart has to be able to take it down, and the only
        # way it can say so is an empty list. Treating that as "didn't mention charts" leaves the
        # stale chart on the report with no way to retract it short of replacing it with a decoy.
        run = _make_run(self.team)
        charts = [{"chart_id": "signups-drop", "title": "Daily signups", "query": {"kind": "InsightVizNode"}}]
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()), patch(CAPTURE_PATH):
            created = self.client.post(
                self._emit_url(str(run.id)), data={**self._payload(), "charts": charts}, format="json"
            ).json()
            response = self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": created["report_id"], "append_note": "checked", **chart_field},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["charts_set"] == expected_charts_set
        assert len(SignalReport.objects.get(id=created["report_id"]).charts) == expected_stored

    def test_clearing_charts_is_a_valid_sole_edit(self) -> None:
        # `charts: []` is the whole instruction on a retraction, so the "needs at least one input"
        # guard has to count it as an input — checking it for falsiness rejects the retraction as an
        # empty edit and leaves the chart up.
        run = _make_run(self.team)
        charts = [{"chart_id": "signups-drop", "title": "Daily signups", "query": {"kind": "InsightVizNode"}}]
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()), patch(CAPTURE_PATH):
            created = self.client.post(
                self._emit_url(str(run.id)), data={**self._payload(), "charts": charts}, format="json"
            ).json()
            response = self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": created["report_id"], "charts": []},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert SignalReport.objects.get(id=created["report_id"]).charts == []

    def test_suggested_prompt_edit_event_uuid_keys_on_the_prompts(self) -> None:
        # Same collision class as the chart case above: suggested prompts are a valid sole input to an
        # edit, so two prompt-only edits to one report in a run share every other part of the key.
        # Without keying on them the second hashes identically and ingestion drops it, so the team
        # never hears the questions changed. An identical retried edit must still stay one event.
        run = _make_run(self.team)
        result = EditReportResult(
            report_id=str(uuid4()), updated_fields=[], note_appended=False, suggested_prompts_set=1
        )

        def forward(prompts: list[str]) -> str:
            with patch(CAPTURE_PATH):
                captured = _capture_report_edited(
                    team=self.team,
                    run=run,
                    result=result,
                    title=None,
                    summary=None,
                    note=None,
                    suggested_prompts=prompts,
                )
            assert captured is not None
            return captured.event_uuid

        teams = forward(["Which teams are affected?"])
        deploy = forward(["Did the 18 June deploy do this?"])
        assert teams != deploy
        assert teams == forward(["Which teams are affected?"])
        # The rows render in the order they were sent, so a reorder changes what the reader sees.
        assert forward(["a?", "b?"]) != forward(["b?", "a?"])
        # A chart clear and a prompt clear both encode to `[]`, so on an untagged key one run's two
        # clears hash the same and ingestion drops whichever landed second — the report keeps
        # whichever set that call was meant to take down.
        with patch(CAPTURE_PATH):
            chart_clear = _capture_report_edited(
                team=self.team,
                run=run,
                result=EditReportResult(
                    report_id=result.report_id, updated_fields=[], note_appended=False, charts_set=0
                ),
                title=None,
                summary=None,
                note=None,
                charts=[],
            )
        assert chart_clear is not None
        assert chart_clear.event_uuid != forward([])

    @parameterized.expand(
        [
            ("omitted", {}, 1, None),
            ("null", {"suggested_prompts": None}, 1, None),
            ("empty_list", {"suggested_prompts": []}, 0, 0),
        ]
    )
    def test_edit_suggested_prompts_distinguishes_untouched_from_cleared(
        self, _name: str, prompt_field: dict, expected_stored: int, expected_set: int | None
    ) -> None:
        # A rewrite can leave a question answering the old report, and the only way a scout can say
        # so is an empty list. Treating that as "didn't mention them" leaves the stale question up
        # with no way to retract it short of replacing it with a decoy.
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()), patch(CAPTURE_PATH):
            created = self.client.post(
                self._emit_url(str(run.id)),
                data={**self._payload(), "suggested_prompts": ["Which teams are affected?"]},
                format="json",
            ).json()
            response = self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": created["report_id"], "append_note": "checked", **prompt_field},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["suggested_prompts_set"] == expected_set
        assert len(SignalReport.objects.get(id=created["report_id"]).suggested_prompts) == expected_stored

    def test_clearing_suggested_prompts_is_a_valid_sole_edit(self) -> None:
        # `suggested_prompts: []` is the whole instruction on a retraction, so the "needs at least
        # one input" guard has to count it as an input — checking it for falsiness rejects the
        # retraction as an empty edit and leaves the stale question up.
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()), patch(CAPTURE_PATH):
            created = self.client.post(
                self._emit_url(str(run.id)),
                data={**self._payload(), "suggested_prompts": ["Which teams are affected?"]},
                format="json",
            ).json()
            response = self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": created["report_id"], "suggested_prompts": []},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert SignalReport.objects.get(id=created["report_id"]).suggested_prompts == []

    def test_chart_counts_ride_the_lifecycle_events(self) -> None:
        # `charts_set` / `chart_count` are what a dashboard or CDP destination reads to tell a
        # chart-bearing report from a plain one; without them both event streams look identical.
        run = _make_run(self.team)
        charts = [{"chart_id": "signups-drop", "title": "Daily signups", "query": {"kind": "InsightVizNode"}}]
        # The edit refreshes the chart rather than re-sending it verbatim: an edit that restates what
        # the report already holds changes nothing, and the lifecycle events stay quiet for those.
        refreshed = [{**charts[0], "title": "Daily signups (rerun)"}]
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()), patch(CAPTURE_PATH) as capture:
            created = self.client.post(
                self._emit_url(str(run.id)), data={**self._payload(), "charts": charts}, format="json"
            ).json()
            self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": created["report_id"], "charts": refreshed},
                format="json",
            )
        emitted = next(c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_report_emitted")
        edited = next(c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_report_edited")
        assert emitted.kwargs["properties"]["chart_count"] == 1
        assert edited.kwargs["properties"]["charts_set"] == 1

    def test_an_edit_that_changes_nothing_fires_no_lifecycle_event(self) -> None:
        # `edit_report` is non-idempotent, so a retry re-sends the charts the report already holds.
        # Nothing moved, and there is no earlier edit event for ingestion to collapse this into, so
        # firing one hands a CDP destination an edit that never happened.
        run = _make_run(self.team)
        charts = [{"chart_id": "signups-drop", "title": "Daily signups", "query": {"kind": "InsightVizNode"}}]
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()), patch(CAPTURE_PATH) as capture:
            created = self.client.post(
                self._emit_url(str(run.id)), data={**self._payload(), "charts": charts}, format="json"
            ).json()
            self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": created["report_id"], "charts": charts},
                format="json",
            )

        assert not [c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_report_edited"]

    @parameterized.expand(
        [
            ("scout_emit_disabled",),
            ("source_disabled",),
            ("scout_config_missing",),
        ]
    )
    def test_emit_report_inactive_scout_does_not_fan_out(self, reason: str) -> None:
        # An inactive scout produces no side effects: a gate-skip from a deliberate off-toggle
        # (`scout_emit_disabled` / `source_disabled`) or a fail-closed missing config
        # (`scout_config_missing`) still records the attempt on the internal
        # `signals_scout_report_emitted` stream, but must NOT fire a customer-facing, automation-driving
        # event into the team's own project. (A non-inactive gate-skip like `ai_processing_not_approved`
        # still fans out — covered by the lifecycle test above.)
        run = _make_run(self.team)
        config = run.scout_config
        assert config is not None
        if reason == "scout_emit_disabled":
            config.emit = False
            config.save(update_fields=["emit"])
        elif reason == "source_disabled":
            SignalSourceConfig.objects.filter(
                team=self.team, source_product="signals_scout", source_type="cross_source_issue"
            ).update(enabled=False)
        else:
            # Deleting the dispatch-time config nulls the run's FK (SET_NULL) → fail-closed gate-skip.
            config.delete()
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()), patch(CAPTURE_PATH) as capture:
            body = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json").json()
        assert body["skipped_reason"] == reason
        # Internal telemetry still records the inactive attempt...
        event = next(c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_report_emitted")
        assert event.kwargs["properties"]["skipped_reason"] == reason
        # ...but no customer-facing copy is forwarded.
        assert not any(
            c.kwargs.get("event_name") == "$scout_report_emitted" for c in self.capture_internal_mock.call_args_list
        )

    @parameterized.expand(
        [
            ("invalid_priority", {"priority": "P9", "priority_explanation": "x"}),
            ("priority_without_explanation", {"priority": "P1"}),
        ]
    )
    def test_emit_report_rejects_bad_priority(self, _name: str, overrides: dict) -> None:
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()):
            response = self.client.post(self._emit_url(str(run.id)), data=self._payload(**overrides), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


class TestBuildSuggestedReviewers(APIBaseTest):
    """Resolution of scout-supplied reviewer entries (github_login / user_uuid) to canonical logins.

    Tested directly rather than over HTTP — it's the report tools' resolution unit, and the fail-loud
    guarantee (an unresolvable user_uuid is rejected, never silently dropped) is the whole reason the
    user_uuid alias is safe to route on."""

    def _github_member(self, login: str) -> User:
        user = User.objects.create(email=f"{login}@example.com")
        OrganizationMembership.objects.create(user=user, organization=self.organization)
        UserSocialAuth.objects.create(user=user, provider="github", uid=f"gh-{login}", extra_data={"login": login})
        return user

    def test_resolves_github_login_lowercased(self) -> None:
        result = _build_suggested_reviewers(self.team, [ReviewerInput(github_login="OctoCat")])
        assert result is not None
        assert [e.github_login for e in result.root] == ["octocat"]

    def test_reason_persists_on_resolved_entries(self) -> None:
        # The resolver rebuilds entries from resolved logins — a refactor that drops `reason` there
        # silently reverts reviewer routing to unexplained picks. Whitespace-only normalizes to None.
        result = _build_suggested_reviewers(
            self.team,
            [
                ReviewerInput(github_login="alice", reason="Top recent author on the affected surface"),
                ReviewerInput(github_login="bob", reason="   "),
            ],
        )
        assert result is not None
        assert [(e.github_login, e.reason) for e in result.root] == [
            ("alice", "Top recent author on the affected surface"),
            ("bob", None),
        ]

    def test_resolves_user_uuid_to_linked_login(self) -> None:
        member = self._github_member("ghhandle")
        result = _build_suggested_reviewers(self.team, [ReviewerInput(user_uuid=str(member.uuid))])
        assert result is not None
        assert [e.github_login for e in result.root] == ["ghhandle"]

    def test_user_uuid_wins_when_both_supplied(self) -> None:
        # The serializer documents that a supplied user_uuid wins over a github_login on the same entry.
        member = self._github_member("realhandle")
        result = _build_suggested_reviewers(self.team, [ReviewerInput(github_login="typo", user_uuid=str(member.uuid))])
        assert result is not None
        assert [e.github_login for e in result.root] == ["realhandle"]

    def test_dedupes_login_and_uuid_resolving_to_same_person(self) -> None:
        member = self._github_member("dupe")
        result = _build_suggested_reviewers(
            self.team, [ReviewerInput(github_login="dupe"), ReviewerInput(user_uuid=str(member.uuid))]
        )
        assert result is not None
        assert [e.github_login for e in result.root] == ["dupe"]

    @parameterized.expand([("not_an_org_member",), ("member_without_github_identity",)])
    def test_unresolvable_user_uuid_raises(self, case: str) -> None:
        if case == "member_without_github_identity":
            orphan = User.objects.create(email="nogh@example.com")
            OrganizationMembership.objects.create(user=orphan, organization=self.organization)
            target = str(orphan.uuid)
        else:
            target = str(uuid4())
        with pytest.raises(InvalidScoutReportError):
            _build_suggested_reviewers(self.team, [ReviewerInput(user_uuid=target)])

    @parameterized.expand([("none", None), ("empty", [])])
    def test_no_entries_yields_none(self, _name: str, reviewers: list | None) -> None:
        assert _build_suggested_reviewers(self.team, reviewers) is None

    def test_entry_with_neither_identifier_raises(self) -> None:
        # An entry that carries neither a usable login nor a uuid is malformed — fail loud rather than
        # drop it, since a silently-dropped reviewer is exactly what leaves a report routed to no one.
        with pytest.raises(InvalidScoutReportError):
            _build_suggested_reviewers(self.team, [ReviewerInput(github_login="   ")])

    def test_caps_entries_before_resolving_uuids(self) -> None:
        # An over-cap list must be rejected before the UUID resolver runs, so a malformed many-entry
        # call can't fire one unbounded `IN` query just to be rejected afterwards.
        resolver = "products.signals.backend.scout_harness.tools.report.get_org_member_github_logins_by_user_uuid"
        entries = [ReviewerInput(user_uuid=str(uuid4())) for _ in range(MAX_SUGGESTED_REVIEWERS + 1)]
        with patch(resolver) as resolve_mock, pytest.raises(InvalidScoutReportError):
            _build_suggested_reviewers(self.team, entries)
        resolve_mock.assert_not_called()

    def _seed_owner(self, skill_name: str, user: User) -> None:
        LLMSkillOwner.objects.for_team(self.team.id).create(team=self.team, skill_name=skill_name, user=user)

    def test_no_reviewers_yields_none_even_with_owners(self) -> None:
        # The scout owns routing: with no picks the report routes to no one. A regression that
        # re-adds owner injection would route a picked-nobody report to the owner instead.
        self._seed_owner("signals-scout-y", self._github_member("soleowner"))
        assert _build_suggested_reviewers(self.team, None, skill_name="signals-scout-y") is None

    def test_owner_pick_stamped_in_place_without_reordering(self) -> None:
        # A picked reviewer who is a current owner is stamped `is_skill_owner=True` (the autostart
        # identity guardrail) — but stamping must not inject, drop, or reorder: the scout's order is
        # the routing order, and a non-owner pick stays unstamped.
        self._seed_owner("signals-scout-x", self._github_member("ownerlogin"))
        result = _build_suggested_reviewers(
            self.team,
            [ReviewerInput(github_login="other"), ReviewerInput(github_login="ownerlogin")],
            skill_name="signals-scout-x",
        )
        assert result is not None
        assert [(e.github_login, e.is_skill_owner) for e in result.root] == [("other", False), ("ownerlogin", True)]

    def test_scout_picked_owner_keeps_its_reason(self) -> None:
        # Stamping rebuilds the owner entry, so it must carry the scout's reason forward — a report's
        # reviewer routing is only as useful as the reason behind it. This is also the security case:
        # a skill editor could name a privileged member as owner and steer the scout to pick them, so
        # the pick is stamped (kept out of autostart identity) rather than trusted as authorship.
        self._seed_owner("signals-scout-v", self._github_member("pickedowner"))
        result = _build_suggested_reviewers(
            self.team,
            [ReviewerInput(github_login="PickedOwner", reason="top author on the surface")],
            skill_name="signals-scout-v",
        )
        assert result is not None
        assert [(e.github_login, e.is_skill_owner, e.reason) for e in result.root] == [
            ("pickedowner", True, "top author on the surface")
        ]


_P1 = PriorityAssessment(priority=Priority.P1, explanation="big blast radius")
_PICKED_REVIEWER = SuggestedReviewers.model_validate([{"github_login": "picked"}])
# An owner-flagged reviewer only exists because the scout picked an owner, so it carries PR intent
# like any other pick — `is_skill_owner` governs autostart identity, not intent.
_OWNER_FLAGGED_REVIEWER = SuggestedReviewers.model_validate([{"github_login": "owner", "is_skill_owner": True}])


class TestWantsRepoSelection(SimpleTestCase):
    """The PR-intent gate for repo selection. The load-bearing case: an owner-flagged reviewer is a
    scout pick (nothing is injected), so it counts as intent — re-excluding it would skip repo
    selection for a prioritized report whose scout deliberately routed to an owner."""

    @parameterized.expand(
        [
            ("picked_reviewer_with_priority_is_pr_intent", None, _P1, _PICKED_REVIEWER, True),
            ("owner_flagged_reviewer_with_priority_is_pr_intent", None, _P1, _OWNER_FLAGGED_REVIEWER, True),
            ("reviewer_without_priority_is_not_pr_intent", None, None, _PICKED_REVIEWER, False),
            ("explicit_repository_always_selects", "posthog/posthog", None, None, True),
            ("priority_without_reviewers_is_not_pr_intent", None, _P1, None, False),
        ]
    )
    def test_wants_repo_selection(
        self,
        _name: str,
        repository: str | None,
        priority: PriorityAssessment | None,
        reviewers: SuggestedReviewers | None,
        expected: bool,
    ) -> None:
        assert _wants_repo_selection(repository, priority, reviewers) is expected


def _evidence(*descriptions: str) -> list[ReportEvidence]:
    return [ReportEvidence(description=d, source_id=f"s{i}") for i, d in enumerate(descriptions)]


class TestExtractLinkedRepository(SimpleTestCase):
    @parameterized.expand(
        [
            ("root_url", "", "See https://github.com/acme/widgets for context", (), "acme/widgets"),
            ("deep_pull_link", "", "Broke in https://github.com/acme/widgets/pull/12", (), "acme/widgets"),
            ("case_and_git_suffix", "", "https://github.com/Acme/Widgets.git broke", (), "acme/widgets"),
            ("trailing_period", "", "Fixed in https://github.com/acme/widgets.", (), "acme/widgets"),
            ("clone_url_ending_a_sentence", "", "Clone https://github.com/acme/widgets.git.", (), "acme/widgets"),
            ("from_evidence", "", "no link here", ("https://github.com/acme/widgets/blob/main/x.py",), "acme/widgets"),
            # A report summary is markdown, so its links usually arrive labelled rather than bare.
            ("markdown_link", "", "Broke in [PR 12](https://github.com/acme/widgets/pull/12)", (), "acme/widgets"),
            (
                "same_repo_twice",
                "https://github.com/acme/widgets",
                "and https://github.com/acme/widgets/pull/1",
                (),
                "acme/widgets",
            ),
            (
                "two_distinct_repos",
                "https://github.com/acme/widgets",
                "vs https://github.com/acme/gadgets",
                (),
                None,
            ),
            ("no_link", "A plain title", "Users hit read/write errors in acme/widgets", (), None),
            ("unconnected_upstream_repo", "", "Upstream bug: https://github.com/other/sdk/issues/3", (), None),
            ("feature_path_not_repo", "", "Configured at https://github.com/apps/dependabot", (), None),
        ]
    )
    def test_extract_linked_repository(
        self, _name: str, title: str, summary: str, evidence_descriptions: tuple[str, ...], expected: str | None
    ) -> None:
        assert (
            _extract_linked_repository(title, summary, _evidence(*evidence_descriptions), _CONNECTED_REPOS) == expected
        )

    def test_no_connected_repos_resolves_nothing(self) -> None:
        assert _extract_linked_repository("", "https://github.com/acme/widgets", _evidence(), []) is None


class TestResolveReportRepositoryGateSkipped(SimpleTestCase):
    def _resolve(self, summary: str) -> RepoSelectionResult | None:
        with patch(
            "products.signals.backend.scout_harness.tools.report._connected_repositories",
            return_value=_CONNECTED_REPOS,
        ):
            return async_to_sync(_resolve_report_repository)(
                team_id=1,
                repository=None,
                title="Crash on upload",
                summary=summary,
                evidence=_evidence(),
                wants_full_selection=False,
            )

    def test_linked_repo_seeds_a_manual_only_target(self) -> None:
        result = self._resolve("Traced to https://github.com/acme/widgets/pull/7")
        assert result is not None
        assert result.repository == "acme/widgets"
        assert result.autostart_eligible is False

    def test_no_linked_repo_writes_nothing(self) -> None:
        assert self._resolve("No repository named here") is None


class TestReportClassificationProps(SimpleTestCase):
    @parameterized.expand(
        [
            ("exact_prefix", "Scout self-improvement: my-scout – dead trigger", True),
            # LLM-authored titles drift in case/whitespace; the classifier must tolerate that.
            ("case_and_whitespace_drift", "  scout SELF-improvement: my-scout – topic", True),
            ("space_before_colon", "Scout self-improvement : my-scout – topic", True),
            ("hyphen_dropped", "Scout self improvement: my-scout – topic", True),
            ("finding_title", "Checkout p99 regressed after 4.2", False),
            # The phrase mid-title (e.g. a finding *about* the escalation flow) is not a prefix match.
            ("prefix_mid_title", "Fix the Scout self-improvement: escalation flow", False),
            ("no_title", None, False),
        ]
    )
    def test_classifies_by_title_prefix(self, _name: str, title: str | None, is_self_improvement: bool) -> None:
        props = _report_classification_props(title)
        assert props["is_self_improvement_report"] is is_self_improvement
        expected_kind = REPORT_KIND_SELF_IMPROVEMENT if is_self_improvement else REPORT_KIND_FINDING
        assert props["report_kind"] == expected_kind
