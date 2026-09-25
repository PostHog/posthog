from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest, NonAtomicAPIBaseTest
from unittest.mock import AsyncMock, patch

from django.test import override_settings
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.llm.gateway_client import GatewayNotConfiguredError
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.temporal.oauth import SIGNALS_APP_CLIENT_ID_DEV, SIGNALS_APP_ID_DEV

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalScratchpad
from products.signals.backend.scout_harness.tools.report import (
    InvalidScoutReportError,
    ReportEvidence,
    ReportLinkInput,
    ReviewerInput,
    edit_report,
    edit_report_sync,
    emit_report_sync,
)
from products.signals.backend.scout_harness.tools.scratchpad import ScratchpadEntry
from products.signals.backend.scout_harness.trial_gateway import create_trial_gateway_token, revoke_trial_gateway_token
from products.signals.backend.scout_harness.trial_state import (
    SCOUT_TRIAL_STATE_KEY,
    ScoutTrialStateError,
    ScoutTrialStore,
    memory_snapshot,
)
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeResponse
from products.signals.backend.test.test_scout_harness_api import _make_run
from products.tasks.backend.models import TaskRun


class TestScoutTrialState(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scout_run = _make_run(self.team, metadata={"scout_trial": {"version": 1, "context_id": str(uuid4())}})
        self.sibling = _make_run(self.team, metadata={"scout_trial": {"version": 1, "context_id": str(uuid4())}})

    def test_memory_changes_are_private_and_start_from_saved_content(self) -> None:
        original = SignalScratchpad.objects.create(team=self.team, key="finding:checkout", content="Saved observation")
        snapshot = memory_snapshot(
            [
                ScratchpadEntry(
                    key=original.key,
                    content=original.content,
                    created_at=original.created_at.isoformat(),
                    updated_at=original.updated_at.isoformat(),
                )
            ]
        )
        own = ScoutTrialStore(self.scout_run, initial_memory=snapshot)
        sibling = ScoutTrialStore(self.sibling, initial_memory=snapshot)
        original.content = "Production changed after capture"
        original.save()

        own.remember(key=original.key, content="First candidate")
        sibling.remember(key=original.key, content="Second candidate")
        own.remember(key="finding:new", content="Only the first run knows this")

        assert own.search_memory(key=original.key)[0].content == "First candidate"
        assert sibling.search_memory(key=original.key)[0].content == "Second candidate"
        assert sibling.search_memory(key="finding:new") == []
        original.refresh_from_db()
        assert original.content == "Production changed after capture"
        assert SignalScratchpad.objects.filter(team=self.team).count() == 1
        assert own.forget(key=original.key)
        assert not own.forget(key=original.key)
        assert own.search_memory(key=original.key) == []
        assert sibling.search_memory(key=original.key)[0].content == "Second candidate"

    def test_stale_store_instances_preserve_other_writes_and_task_state(self) -> None:
        first = ScoutTrialStore(self.scout_run, initial_memory=[])
        second = ScoutTrialStore(self.scout_run, initial_memory=[])
        first.remember(key="first", content="First value")
        TaskRun.update_state_atomic(self.scout_run.task_run_id, updates={"sandbox_id": "existing-sandbox"})
        second.remember(key="second", content="Second value")

        assert {entry.key for entry in first.search_memory()} == {"first", "second"}
        self.scout_run.task_run.refresh_from_db()
        assert self.scout_run.task_run.state["sandbox_id"] == "existing-sandbox"

    @parameterized.expand(["completed", "cancelled", "failed"])
    def test_terminal_runs_reject_mutation(self, status: str) -> None:
        store = ScoutTrialStore(self.scout_run, initial_memory=[])
        TaskRun.objects.filter(id=self.scout_run.task_run_id).update(status=status)

        with self.assertRaisesMessage(ScoutTrialStateError, "no longer in progress"):
            store.remember(key="key", content="value")
        self.scout_run.task_run.refresh_from_db()
        assert SCOUT_TRIAL_STATE_KEY not in self.scout_run.task_run.state
        store.invalidate("The runner observed different settings.", allow_terminal=True)
        store.invalidate("Do not replace the first failure.", allow_terminal=True)
        assert store.invalid_reason() == "The runner observed different settings."

    def test_private_state_does_not_enable_trial_permissions(self) -> None:
        ordinary = _make_run(self.team)
        TaskRun.update_state_atomic(ordinary.task_run_id, updates={SCOUT_TRIAL_STATE_KEY: {}})
        with self.assertRaisesMessage(ScoutTrialStateError, "does not have a private context"):
            ScoutTrialStore(ordinary, initial_memory=[])

    def test_limit_invalidates_trial_without_losing_accepted_content(self) -> None:
        store = ScoutTrialStore(self.scout_run, initial_memory=[])
        store.remember(key="accepted", content="Keep this")
        with patch("products.signals.backend.scout_harness.trial_state.MAX_SCOUT_TRIAL_STATE_BYTES", 500):
            with self.assertRaisesMessage(ScoutTrialStateError, "cannot be compared"):
                store.remember(key="oversized", content="x" * 1000)

        assert store.invalid_reason() is not None
        assert store.search_memory(key="accepted")[0].content == "Keep this"
        assert store.search_memory(key="oversized") == []
        with self.assertRaisesMessage(ScoutTrialStateError, "cannot be compared"):
            store.remember(key="small", content="Also rejected")

    @time_machine.travel("2026-08-01T12:00:00Z", tick=False)
    def test_memory_search_keeps_expiry_dates_and_projections(self) -> None:
        now = datetime(2026, 8, 1, 12, tzinfo=UTC)
        store = ScoutTrialStore(
            self.scout_run,
            initial_memory=memory_snapshot(
                [
                    ScratchpadEntry(
                        key="old", content="Checkout detail", updated_at=(now - timedelta(days=2)).isoformat()
                    ),
                    ScratchpadEntry(
                        key="expired",
                        content="Checkout stale detail",
                        updated_at=now.isoformat(),
                        expires_at=(now - timedelta(seconds=1)).isoformat(),
                    ),
                ]
            ),
        )
        store.remember(key="new", content="Checkout current detail")

        assert [entry.key for entry in store.search_memory(text="CHECKOUT")] == ["new", "old"]
        assert [entry.key for entry in store.search_memory(date_from=now)] == ["new"]
        assert [entry.key for entry in store.search_memory(date_to=now)] == ["old"]
        assert len(store.search_memory(include_expired=True)) == 3
        assert store.search_memory(key="new", keys_only=True)[0].content == ""
        assert store.search_memory(key="new", content_max_chars=8)[0].content == "Checkout"


@override_settings(SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=True, LLM_GATEWAY_URL="https://gateway.example")
class TestScoutTrialReportCapture(NonAtomicAPIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        marker = {"version": 1, "context_id": str(uuid4()), "launch_id": str(uuid4())}
        self.scout_run = _make_run(self.team, metadata={"scout_trial": marker})
        task = self.scout_run.task_run.task
        task.created_by = self.user
        task.origin_key = f"scout-trial:{marker['launch_id']}"
        task.save(update_fields=["created_by", "origin_key"])
        self.scout_run.task_run.state = {**(self.scout_run.task_run.state or {}), "scout_trial": marker}
        self.scout_run.task_run.save(update_fields=["state"])
        self.signals_app, _ = OAuthApplication.objects.get_or_create(
            client_id=SIGNALS_APP_CLIENT_ID_DEV,
            defaults={
                "id": SIGNALS_APP_ID_DEV,
                "name": "Signals",
                "algorithm": "RS256",
                "client_type": OAuthApplication.CLIENT_PUBLIC,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": "https://example.com/callback",
            },
        )
        region = patch("posthog.temporal.oauth.get_instance_region", return_value=None)
        region.start()
        self.addCleanup(region.stop)
        self.store = ScoutTrialStore(self.scout_run, initial_memory=[])
        judge = patch(
            "products.signals.backend.scout_report.judge.judge_report_safety",
            new_callable=AsyncMock,
            return_value=SafetyJudgeResponse(choice=True, explanation="Safe synthetic evidence"),
        )
        self.judge = judge.start()
        self.addCleanup(judge.stop)
        self.capture = patch("products.signals.backend.scout_harness.tools.report.posthoganalytics.capture").start()
        self.capture_internal = patch("products.signals.backend.scout_harness.tools.report.capture_internal").start()
        self.addCleanup(patch.stopall)

    def _emit(self, *, title: str = "A synthetic checkout issue", key: str = "checkout") -> str:
        result = emit_report_sync(
            team=self.team,
            run=self.scout_run,
            title=title,
            summary="The synthetic checkout handler returns an incorrect total.",
            evidence=[
                ReportEvidence(description="The fixture returns 12 instead of 10.", source_id="synthetic-observation")
            ],
            actionability_explanation="Correct the total calculation.",
            actionability="immediately_actionable",
            priority="P2",
            priority_explanation="The synthetic checkout total is incorrect.",
            repository="NO_REPO",
            idempotency_key=key,
        )
        assert result.report_id is not None
        assert result.emitted
        assert not OAuthAccessToken.objects.filter(sandbox_task_id=self.scout_run.task_run.task_id).exists()
        return result.report_id

    @time_machine.travel("2026-09-01T12:00:00Z", tick=False)
    def test_gateway_credential_is_narrow_and_revoked_after_safety_failure(self) -> None:
        token = create_trial_gateway_token(self.scout_run)
        credential = OAuthAccessToken.objects.get(token=token)
        assert credential.application_id == self.signals_app.id
        assert credential.user_id == self.user.id
        assert credential.sandbox_task_id == self.scout_run.task_run.task_id
        assert credential.scoped_teams == [self.team.id]
        assert set(credential.scope.split()) == {
            "llm_gateway:read",
            "internal_run:read",
            "scout_experiment_internal:read",
        }
        assert credential.expires == timezone.now() + timedelta(minutes=10)
        revoke_trial_gateway_token(token)

        self.judge.side_effect = RuntimeError("Synthetic safety failure")
        with self.assertRaisesRegex(RuntimeError, "Synthetic safety failure"):
            self._emit()
        assert not OAuthAccessToken.objects.filter(sandbox_task_id=self.scout_run.task_run.task_id).exists()

    @parameterized.expand(["missing_app", "untrusted_run", "revoked_actor"])
    def test_gateway_credential_rejects_invalid_trial_identity(self, condition: str) -> None:
        if condition == "missing_app":
            self.signals_app.delete()
        elif condition == "untrusted_run":
            self.scout_run.task_run.state = {}
            self.scout_run.task_run.save(update_fields=["state"])
        else:
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])
        with self.assertRaises(GatewayNotConfiguredError):
            create_trial_gateway_token(self.scout_run)
        assert not OAuthAccessToken.objects.filter(sandbox_task_id=self.scout_run.task_run.task_id).exists()

    @parameterized.expand([True, False])
    def test_creation_retries_and_edits_remain_private(self, emit: bool) -> None:
        assert self.scout_run.scout_config is not None
        self.scout_run.scout_config.emit = emit
        self.scout_run.scout_config.save(update_fields=["emit"])
        report_id = self._emit()
        assert self._emit(title="Retried wording") == report_id
        assert self.judge.call_count == 1
        result = edit_report_sync(
            team=self.team,
            run=self.scout_run,
            report_id=report_id,
            summary="A revised synthetic explanation.",
            append_note="A second fixture confirms it.",
            append_evidence=[
                ReportEvidence(description="The second fixture also returns 12.", source_id="second-observation")
            ],
        )

        assert result.updated_fields == ["summary"]
        assert result.evidence_appended == 1
        draft = self.store.get_report(report_id)
        assert draft is not None
        assert draft.document["summary"] == "A revised synthetic explanation."
        assert draft.document["priority"] == "P2"
        assert draft.document["signal_count"] == 2
        assert draft.payload["repository"] == "NO_REPO"
        assert draft.edits[0]["append_note"] == "A second fixture confirms it."
        assert len(draft.evidence) == 2
        assert not SignalReport.objects.filter(team=self.team).exists()
        assert not SignalReportArtefact.objects.filter(team=self.team).exists()
        self.capture.assert_not_called()
        self.capture_internal.assert_not_called()
        calls_before_replay = self.judge.call_count
        self.scout_run.task_run.status = "completed"
        self.scout_run.task_run.save(update_fields=["status"])
        assert self._emit() == report_id
        assert self.judge.call_count == calls_before_replay

    def test_editing_production_report_does_not_change_original(self) -> None:
        original = SignalReport.objects.create(
            team=self.team,
            title="Existing synthetic report",
            summary="Existing synthetic summary",
            status=SignalReport.Status.READY,
            signal_count=1,
            total_weight=1,
        )
        unchanged = edit_report_sync(
            team=self.team,
            run=self.scout_run,
            report_id=str(original.id),
            title=original.title,
        )
        assert not unchanged.changed
        unchanged_draft = self.store.get_report(str(original.id))
        assert unchanged_draft is not None
        assert unchanged_draft.artefacts == []
        edit_report_sync(
            team=self.team,
            run=self.scout_run,
            report_id=str(original.id),
            title="Privately revised title",
            append_note="Private supporting note",
        )

        original.refresh_from_db()
        assert original.title == "Existing synthetic report"
        assert not original.artefacts.exists()
        draft = self.store.get_report(str(original.id))
        assert draft is not None
        assert draft.document["title"] == "Privately revised title"
        assert draft.source_report_id == str(original.id)
        sibling = _make_run(self.team, metadata={"scout_trial": {"version": 1, "context_id": str(uuid4())}})
        assert ScoutTrialStore(sibling).get_report(str(original.id)) is None

    def test_capture_does_not_start_downstream_repository_agent(self) -> None:
        with patch(
            "products.signals.backend.report_generation.select_repo.select_repository_for_team", new_callable=AsyncMock
        ) as select_repository:
            result = emit_report_sync(
                team=self.team,
                run=self.scout_run,
                title="Synthetic checkout issue",
                summary="The fixture produces an incorrect total.",
                evidence=[
                    ReportEvidence(description="The fixture returns 12 instead of 10.", source_id="fixture-total")
                ],
                actionability_explanation="Correct the total calculation.",
                actionability="immediately_actionable",
                priority="P2",
                priority_explanation="Checkout totals are incorrect.",
                suggested_reviewers=[ReviewerInput(github_login="synthetic-reviewer", reason="Maintains checkout")],
            )
        select_repository.assert_not_called()
        assert result.report_id is not None
        report = self.store.get_report(result.report_id)
        assert report is not None
        assert report.operator_metadata["skipped_automatic_repository_selection"] is True

    @parameterized.expand([("title", " "), ("summary", ""), ("append_note", " ")])
    def test_invalid_edits_fail_before_judging(self, field: str, value: str) -> None:
        report_id = self._emit()
        with self.assertRaises(InvalidScoutReportError):
            edit_report_sync(
                team=self.team,
                run=self.scout_run,
                report_id=report_id,
                title=value if field == "title" else None,
                summary=value if field == "summary" else None,
                append_note=value if field == "append_note" else None,
            )
        assert self.judge.call_count == 1

    def test_unsafe_edit_leaves_accepted_draft_unchanged(self) -> None:
        report_id = self._emit()
        self.judge.return_value = SafetyJudgeResponse(choice=False, explanation="Rejected synthetic instruction")

        with self.assertRaisesMessage(InvalidScoutReportError, "rejected by the safety judge"):
            edit_report_sync(team=self.team, run=self.scout_run, report_id=report_id, summary="Rejected replacement")
        draft = self.store.get_report(report_id)
        assert draft is not None
        assert draft.document["summary"] == "The synthetic checkout handler returns an incorrect total."

    @parameterized.expand([("summary", " "), ("evidence", " ")])
    def test_private_creation_keeps_production_required_text_validation(self, field: str, value: str) -> None:
        with self.assertRaises(InvalidScoutReportError):
            emit_report_sync(
                team=self.team,
                run=self.scout_run,
                title="Synthetic title",
                summary=value if field == "summary" else "Synthetic summary",
                evidence=[
                    ReportEvidence(description=value if field == "evidence" else "Evidence", source_id="fixture")
                ],
                actionability_explanation="Correct the fixture.",
                actionability="immediately_actionable",
            )
        self.judge.assert_not_called()
        assert self.store.reports() == []

    @parameterized.expand([False, True])
    def test_unsupported_report_links_invalidate_comparison(self, asynchronous: bool) -> None:
        report_id = self._emit()
        edit = async_to_sync(edit_report) if asynchronous else edit_report_sync
        with self.assertRaisesMessage(InvalidScoutReportError, "Report links are not supported"):
            edit(
                team=self.team,
                run=self.scout_run,
                report_id=report_id,
                links=[ReportLinkInput(kind="depends_on", report_id=str(uuid4()))],
            )
        assert self.store.invalid_reason() is not None
        assert self.judge.call_count == 1

    def test_inbox_reads_private_report_evidence_and_artefacts_only_for_its_run(self) -> None:
        report_id = self._emit()
        base = f"/api/projects/{self.team.id}/signals/reports/"
        with patch("products.signals.backend.views.trial_store_for_request", return_value=self.store):
            detail = self.client.get(f"{base}{report_id}/")
            assert detail.status_code == 200
            assert detail.json()["title"] == "A synthetic checkout issue"
            assert "operator_metadata" not in detail.json()
            evidence = self.client.get(f"{base}{report_id}/signals/")
            assert evidence.status_code == 200
            assert evidence.json()["signals"][0]["source_id"] == "synthetic-observation"
            artefacts = self.client.get(f"{base}{report_id}/artefacts/")
            assert artefacts.status_code == 200
            assert artefacts.json()["count"] == detail.json()["artefact_count"]
            artefact_id = artefacts.json()["results"][0]["id"]
            assert self.client.get(f"{base}{report_id}/artefacts/{artefact_id}/").status_code == 200
            listed = self.client.get(base, {"search": "checkout", "limit": "1"})
            assert listed.status_code == 200
            assert [row["id"] for row in listed.json()["results"]] == [report_id]

        sibling = _make_run(self.team, metadata={"scout_trial": {"version": 1, "context_id": str(uuid4())}})
        with patch("products.signals.backend.views.trial_store_for_request", return_value=ScoutTrialStore(sibling)):
            assert self.client.get(f"{base}{report_id}/").status_code == 404
            assert self.client.get(f"{base}{report_id}/artefacts/{artefact_id}/").status_code == 404
            assert self.client.get(base).json()["count"] == 0
        assert self.client.get(f"{base}{report_id}/").status_code == 404

    def test_inbox_search_and_pagination_merge_private_edits_without_duplicates(self) -> None:
        first = SignalReport.objects.create(team=self.team, title="Earlier report", summary="Original", status="ready")
        second = SignalReport.objects.create(team=self.team, title="Second report", summary="Original", status="ready")
        private_id = self._emit()
        edit_report_sync(
            team=self.team, run=self.scout_run, report_id=str(first.id), title="A synthetic checkout revision"
        )
        base = f"/api/projects/{self.team.id}/signals/reports/"
        with (
            patch("products.signals.backend.views.trial_store_for_request", return_value=self.store),
            patch("products.signals.backend.views.fetch_source_products_for_reports", return_value={}),
            patch("products.signals.backend.views.fetch_implementation_prs_for_reports", return_value={}),
        ):
            results = []
            for offset in range(3):
                response = self.client.get(base, {"sort": "oldest", "offset": str(offset), "limit": "1"})
                assert response.status_code == 200
                assert response.json()["count"] == 3
                results.extend(response.json()["results"])
            assert [row["id"] for row in results] == [str(first.id), str(second.id), private_id]
            search = self.client.get(base, {"search": "checkout", "sort": "oldest"})
            assert [row["id"] for row in search.json()["results"]] == [str(first.id), private_id]
            detail = self.client.get(f"{base}{first.id}/")
            assert detail.json()["title"] == "A synthetic checkout revision"
            count = self.client.get(base, {"search": "checkout", "count_only": "true"})
            assert count.json()["count"] == 2
        first.refresh_from_db()
        assert first.title == "Earlier report"

    @parameterized.expand(
        [("source_product", "signals_scout"), ("source_id", "synthetic-observation"), ("scout_prefix", "test")]
    )
    def test_inbox_source_filters_find_private_evidence(self, field: str, value: str) -> None:
        report_id = self._emit()
        query = {field: value, "source_product": "signals_scout"}
        if field == "scout_prefix":
            query[field] = self.scout_run.skill_name[:4]
        with (
            patch("products.signals.backend.views.trial_store_for_request", return_value=self.store),
            patch("products.signals.backend.views.fetch_report_ids_for_source_products", return_value=[]),
            patch("products.signals.backend.views.fetch_live_report_ids_for_source_ids", return_value={}),
            patch("products.signals.backend.views.fetch_report_ids_for_scout_prefix", return_value=[]),
        ):
            result = self.client.get(f"/api/projects/{self.team.id}/signals/reports/", query)
        assert result.status_code == 200
        assert [row["id"] for row in result.json()["results"]] == [report_id]

    def test_unsupported_inbox_filter_invalidates_comparison(self) -> None:
        with patch("products.signals.backend.views.trial_store_for_request", return_value=self.store):
            result = self.client.get(f"/api/projects/{self.team.id}/signals/reports/", {"view": "actionable"})
        assert result.status_code == 400
        assert self.store.invalid_reason() is not None
