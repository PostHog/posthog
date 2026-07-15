from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.apps import apps
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalSourceConfig
from products.signals.backend.scout_harness.tools.report import (
    MAX_SUGGESTED_REVIEWERS,
    REPORT_KIND_FINDING,
    REPORT_KIND_SELF_IMPROVEMENT,
    EditReportResult,
    InvalidScoutReportError,
    ReviewerInput,
    _build_suggested_reviewers,
    _capture_report_edited,
    _report_classification_props,
)
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeResponse
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run
from products.skills.backend.models.skills import LLMSkill

JUDGE_PATH = "products.signals.backend.scout_report.judge.judge_report_safety"
EMBED_PATH = "products.signals.backend.scout_report.persistence.emit_embedding_request"
# Patched at its source module so the lazy import inside `_maybe_autostart_report` picks up the mock.
AUTOSTART_PATH = "products.signals.backend.auto_start.maybe_autostart_from_report_artefacts"
CAPTURE_PATH = "products.signals.backend.scout_harness.tools.report.posthoganalytics.capture"
# The customer-facing copy lands in the scout's own team project via capture_internal (a network boundary).
CAPTURE_INTERNAL_PATH = "products.signals.backend.scout_harness.tools.report.capture_internal"
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

    def test_emit_report_unsafe_suppresses_but_returns_id(self) -> None:
        run = _make_run(self.team)
        with _safe_judge(choice=False, explanation="prompt injection"), patch(EMBED_PATH):
            response = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["emitted"] is False
        assert body["report_status"] == SignalReport.Status.SUPPRESSED
        assert body["safety_explanation"] == "prompt injection"
        assert body["report_id"] is not None

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
                return _capture_report_edited(
                    team=self.team,
                    run=run,
                    result=result,
                    title=None,
                    summary=None,
                    note=None,
                    suggested_reviewers=reviewers,
                ).event_uuid

        alice = forward([ReviewerInput(github_login="alice")])
        bob = forward([ReviewerInput(github_login="bob")])
        assert alice != bob
        assert alice == forward([ReviewerInput(github_login="alice")])

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
        result = _build_suggested_reviewers(self.team.id, [ReviewerInput(github_login="OctoCat")])
        assert result is not None
        assert [e.github_login for e in result.root] == ["octocat"]

    def test_resolves_user_uuid_to_linked_login(self) -> None:
        member = self._github_member("ghhandle")
        result = _build_suggested_reviewers(self.team.id, [ReviewerInput(user_uuid=str(member.uuid))])
        assert result is not None
        assert [e.github_login for e in result.root] == ["ghhandle"]

    def test_user_uuid_wins_when_both_supplied(self) -> None:
        # The serializer documents that a supplied user_uuid wins over a github_login on the same entry.
        member = self._github_member("realhandle")
        result = _build_suggested_reviewers(
            self.team.id, [ReviewerInput(github_login="typo", user_uuid=str(member.uuid))]
        )
        assert result is not None
        assert [e.github_login for e in result.root] == ["realhandle"]

    def test_dedupes_login_and_uuid_resolving_to_same_person(self) -> None:
        member = self._github_member("dupe")
        result = _build_suggested_reviewers(
            self.team.id, [ReviewerInput(github_login="dupe"), ReviewerInput(user_uuid=str(member.uuid))]
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
            _build_suggested_reviewers(self.team.id, [ReviewerInput(user_uuid=target)])

    @parameterized.expand([("none", None), ("empty", [])])
    def test_no_entries_yields_none(self, _name: str, reviewers: list | None) -> None:
        assert _build_suggested_reviewers(self.team.id, reviewers) is None

    def test_entry_with_neither_identifier_raises(self) -> None:
        # An entry that carries neither a usable login nor a uuid is malformed — fail loud rather than
        # drop it, since a silently-dropped reviewer is exactly what leaves a report routed to no one.
        with pytest.raises(InvalidScoutReportError):
            _build_suggested_reviewers(self.team.id, [ReviewerInput(github_login="   ")])

    def test_caps_entries_before_resolving_uuids(self) -> None:
        # An over-cap list must be rejected before the UUID resolver runs, so a malformed many-entry
        # call can't fire one unbounded `IN` query just to be rejected afterwards.
        resolver = "products.signals.backend.scout_harness.tools.report.get_org_member_github_logins_by_user_uuid"
        entries = [ReviewerInput(user_uuid=str(uuid4())) for _ in range(MAX_SUGGESTED_REVIEWERS + 1)]
        with patch(resolver) as resolve_mock, pytest.raises(InvalidScoutReportError):
            _build_suggested_reviewers(self.team.id, entries)
        resolve_mock.assert_not_called()


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
