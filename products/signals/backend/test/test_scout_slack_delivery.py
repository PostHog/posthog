import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

from celery.exceptions import Retry
from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models import Team
from posthog.models.integration import Integration
from posthog.redis import get_client

from products.signals.backend.models import SignalReport, SignalScoutEmission, SignalScoutRun
from products.signals.backend.scout_harness.slack_charts import CHART_BLOCK_ID_PREFIX as PREFIX
from products.signals.backend.scout_harness.slack_delivery import (
    ScoutSlackPermanentDeliveryError,
    _latest_report_delivery_key,
    get_scout_slack_destination,
    mark_latest_scout_report_delivery,
    post_scout_emission_to_slack,
)
from products.signals.backend.scout_harness.slack_delivery_queue import queue_configured_scout_slack_delivery
from products.signals.backend.tasks import deliver_scout_slack_output, enqueue_scout_slack_delivery


class TestGetScoutSlackDestination(SimpleTestCase):
    @parameterized.expand(
        [
            ("explicit_true", {"thread_reports": True}, True),
            ("omitted_defaults_off", {}, False),
            ("explicit_false", {"thread_reports": False}, False),
            # Only a real boolean True turns threading on; a truthy non-bool stays off.
            ("truthy_non_bool_stays_off", {"thread_reports": "yes"}, False),
        ]
    )
    def test_parses_thread_reports(self, _name: str, extra: dict, expected: bool) -> None:
        destination = get_scout_slack_destination({"slack": {"integration_id": 7, "channel": "C1|#x", **extra}})

        assert destination is not None
        assert destination.thread_reports is expected


class FakeSlackResponse(dict):
    def __init__(self, data: dict, headers: dict | None = None) -> None:
        super().__init__(data)
        self.headers = headers or {}


class TestScoutSlackDelivery(BaseTest):
    def _make_emission(self, description: str = "**Checkout** failures") -> SignalScoutEmission:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team,
            title="scout run",
            description="scout run",
            origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        )
        task_run = TaskRun.objects.create(task=task, team=self.team)
        run = SignalScoutRun.all_teams.create(
            task_run=task_run,
            team=self.team,
            skill_name="signals-scout-error-tracking",
            skill_version=1,
        )
        return SignalScoutEmission.all_teams.create(
            team=self.team,
            scout_run=run,
            finding_id="checkout/500s",
            description=description,
            weight=1.0,
            confidence=0.84,
            severity="P1",
            tags=["checkout", "regression"],
            source_id=f"run:{run.id}:finding:checkout-500s",
        )

    def test_posts_safe_mrkdwn_but_does_not_invite_followup_for_child_environment(self) -> None:
        emission = self._make_emission(
            "**Checkout** failures [trace](https://example.com/trace) <!channel> [ping](!here)"
        )
        child_team = Team.objects.create(
            organization=self.organization,
            project=self.team.project,
            parent_team=self.team,
            name="Child environment",
        )
        integration = Integration.objects.create(team=child_team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = {"ts": "1785418710.000100"}

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            post_scout_emission_to_slack(
                emission,
                integration_id=integration.id,
                channel="CSCOUTS|#scout-findings",
            )

        call = fake_client.chat_postMessage.call_args_list[0].kwargs
        assert call["channel"] == "CSCOUTS"
        assert call["client_msg_id"] == str(emission.id)
        assert "thread_ts" not in call
        section = call["blocks"][1]["text"]["text"]
        assert "*Checkout*" in section
        assert "<https://example.com/trace|trace>" in section
        assert "<!channel>" not in section
        assert "<!here>" not in section
        assert "&lt;!channel&gt;" in section
        assert call["blocks"][-1]["elements"][0]["url"] == (
            f"{settings.SITE_URL}/project/{self.team.id}/inbox/scouts/signals-scout-error-tracking/checkout%2F500s"
        )
        assert fake_client.chat_postMessage.call_count == 1

    def test_posts_report_with_safe_markdown_and_delivery_id(self) -> None:
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="**Checkout** failed for <!channel> [trace](https://example.com/trace)",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = {"ts": "1785418710.000200"}
        delivery_id = "01864f4c-6957-7d3f-8d85-1d775e527265"

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                delivery_id,
                integration.id,
                "CSCOUTS|#scout-findings",
            )

        call = fake_client.chat_postMessage.call_args_list[0].kwargs
        assert call["channel"] == "CSCOUTS"
        assert call["client_msg_id"] == delivery_id
        assert "thread_ts" not in call
        section = call["blocks"][2]["text"]["text"]
        assert "*Checkout*" in section
        assert "<!channel>" not in section
        assert "&lt;!channel&gt;" in section
        assert "<https://example.com/trace|trace>" in section
        assert call["blocks"][-1]["elements"][0]["url"] == (
            f"{settings.SITE_URL}/project/{self.team.id}/inbox/reports/{report.id}"
        )
        reply = fake_client.chat_postMessage.call_args_list[1].kwargs
        assert reply["thread_ts"] == "1785418710.000200"
        assert reply["blocks"][0]["type"] == "context"

    def test_note_only_edit_delivers_the_note_instead_of_the_report(self) -> None:
        # Without the edit_note branch a note-only edit re-posts the full report message, which is
        # byte-identical to the one already in the channel and reads as a duplicate.
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="**Checkout** failed for many users",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = {"ts": "1785418710.000300"}
        delivery_id = "0198f2a1-4c31-7a52-9f1e-3c5d6e7f8a9b"

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                delivery_id,
                integration.id,
                "CSCOUTS|#scout-findings",
                "Re-checked after the fix: **error rate** is back to baseline <!channel>",
            )

        call = fake_client.chat_postMessage.call_args_list[0].kwargs
        assert call["client_msg_id"] == delivery_id
        context = call["blocks"][0]["elements"][0]["text"]
        assert "added a note to an existing report" in context
        assert call["blocks"][1]["text"]["text"] == "Checkout failures"
        section = call["blocks"][2]["text"]["text"]
        assert "*error rate*" in section
        assert "<!channel>" not in section
        assert "&lt;!channel&gt;" in section
        assert "failed for many users" not in section
        assert call["blocks"][-1]["elements"][0]["url"] == (
            f"{settings.SITE_URL}/project/{self.team.id}/inbox/reports/{report.id}"
        )

    def test_enqueue_omits_edit_note_kwarg_when_unset(self) -> None:
        # A worker still running the previous task signature rejects an unknown kwarg, so every
        # delivery without a note must keep the exact payload shape it had before edit_note existed.
        with patch.object(deliver_scout_slack_output, "delay") as delay:
            enqueue_scout_slack_delivery(
                team_id=self.team.id,
                output_type="report",
                output_id="ddab8ee5-2bb8-4226-b145-6732d31dc344",
                run_id="e3865391-bc89-44e6-86f7-2d4405627daf",
                delivery_id="b316c1d1-6901-49eb-8223-96d4df69f67f",
                integration_id=9,
                channel="CSCOUTS|#scout-findings",
            )
            enqueue_scout_slack_delivery(
                team_id=self.team.id,
                output_type="report",
                output_id="ddab8ee5-2bb8-4226-b145-6732d31dc344",
                run_id="e3865391-bc89-44e6-86f7-2d4405627daf",
                delivery_id="c4f7d2e2-7012-4afc-9334-a7e5df70a80a",
                integration_id=9,
                channel="CSCOUTS|#scout-findings",
                edit_note="Re-validated on the next run",
            )

        assert delay.call_args_list[0].kwargs == {}
        assert delay.call_args_list[1].kwargs == {"edit_note": "Re-validated on the next run"}

    @parameterized.expand(
        [
            ("full_report", "report", None, "b316c1d1-6901-49eb-8223-96d4df69f67f"),
            # A note-only update must not supersede the delivery still building the report message.
            ("note_only", "report", "Re-validated on the next run", None),
            ("finding", "finding", None, None),
        ]
    )
    def test_enqueue_marks_only_a_full_report_delivery_as_the_latest(
        self, _name, output_type, edit_note, expected_marker
    ) -> None:
        get_client().flushdb()
        with patch.object(deliver_scout_slack_output, "delay"):
            enqueue_scout_slack_delivery(
                team_id=self.team.id,
                output_type=output_type,
                output_id="ddab8ee5-2bb8-4226-b145-6732d31dc344",
                run_id="e3865391-bc89-44e6-86f7-2d4405627daf",
                delivery_id="b316c1d1-6901-49eb-8223-96d4df69f67f",
                integration_id=9,
                channel="CSCOUTS|#scout-findings",
                edit_note=edit_note,
            )

        marker = get_client().get(
            _latest_report_delivery_key("ddab8ee5-2bb8-4226-b145-6732d31dc344", 9, "CSCOUTS|#scout-findings")
        )
        assert (marker.decode() if marker is not None else None) == expected_marker

    def test_enqueue_omits_thread_reports_kwarg_when_off(self) -> None:
        # Same backward-compat contract as edit_note: the flag rides as a kwarg only when on, so a
        # worker on the previous task signature never sees an unknown keyword for a default delivery.
        with patch.object(deliver_scout_slack_output, "delay") as delay:
            enqueue_scout_slack_delivery(
                team_id=self.team.id,
                output_type="report",
                output_id="ddab8ee5-2bb8-4226-b145-6732d31dc344",
                run_id="e3865391-bc89-44e6-86f7-2d4405627daf",
                delivery_id="b316c1d1-6901-49eb-8223-96d4df69f67f",
                integration_id=9,
                channel="CSCOUTS|#scout-findings",
            )
            enqueue_scout_slack_delivery(
                team_id=self.team.id,
                output_type="report",
                output_id="ddab8ee5-2bb8-4226-b145-6732d31dc344",
                run_id="e3865391-bc89-44e6-86f7-2d4405627daf",
                delivery_id="c4f7d2e2-7012-4afc-9334-a7e5df70a80a",
                integration_id=9,
                channel="CSCOUTS|#scout-findings",
                thread_reports=True,
            )

        assert delay.call_args_list[0].kwargs == {}
        assert delay.call_args_list[1].kwargs == {"thread_reports": True}

    def test_threaded_report_posts_lead_and_delivers_the_full_tail(self) -> None:
        # The bug: a summary past the section cap was truncated with an ellipsis, so the tail never
        # reached the channel. With thread_reports on, the lead posts to the channel and the rest
        # rides as threaded replies, so a distinctive tail marker still arrives.
        emission = self._make_emission()
        tail_marker = "TAIL_MARKER_9137"
        summary = (
            "Lead paragraph before any heading.\n\n"
            "## First finding\n" + ("First body line.\n" * 400) + "\n"
            "## Second finding\n" + ("Second body line.\n" * 400) + f"\nClosing note {tail_marker}."
        )
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary=summary,
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = {"ts": "1785418710.000500"}

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                "CSCOUTS|#scout-findings",
                thread_reports=True,
            )

        calls = fake_client.chat_postMessage.call_args_list
        lead = calls[0].kwargs
        assert "thread_ts" not in lead
        assert lead["blocks"][1]["text"]["text"] == "Checkout failures"
        replies = calls[1:]
        assert len(replies) > 1
        assert all(reply.kwargs["thread_ts"] == "1785418710.000500" for reply in replies)
        # Every posted section stays within the cap, and nothing is ellipsis-truncated.
        section_texts = [
            block["text"]["text"] for call in calls for block in call.kwargs["blocks"] if block["type"] == "section"
        ]
        assert all(len(text) <= 2900 for text in section_texts)
        assert not any(text.endswith("…") for text in section_texts)
        assert any(tail_marker in text for text in section_texts)

    def test_threaded_short_report_posts_one_reply_per_heading_section(self) -> None:
        # The bug: threading only kicked in past the section cap, so a typical digest that fits one
        # section posted as one wall of text. A report with headings now threads at any length, and
        # a sub-heading rides in its parent's reply instead of opening one of its own.
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="Lead line.\n\n## First\nshort body\n\n### Detail\ndeeper body\n\n## Second\nshort body",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = {"ts": "1785418710.000600"}

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                "CSCOUTS|#scout-findings",
                thread_reports=True,
            )

        # The lead, one reply per top-level section, then the unconditional @PostHog follow-up.
        calls = fake_client.chat_postMessage.call_args_list
        assert len(calls) == 4
        assert "thread_ts" not in calls[0].kwargs
        lead_sections = [block["text"]["text"] for block in calls[0].kwargs["blocks"] if block["type"] == "section"]
        assert lead_sections == ["Lead line."]
        first_reply, second_reply = calls[1].kwargs, calls[2].kwargs
        assert first_reply["thread_ts"] == "1785418710.000600"
        assert "First" in first_reply["blocks"][0]["text"]["text"]
        assert "Detail" in first_reply["blocks"][0]["text"]["text"]
        assert "Second" not in first_reply["blocks"][0]["text"]["text"]
        assert "Second" in second_reply["blocks"][0]["text"]["text"]
        assert calls[3].kwargs["blocks"][0]["type"] == "context"

    def test_threaded_report_without_headings_posts_a_single_message(self) -> None:
        # Headings are the seams threading splits on. A summary with none has nothing to split, so it
        # stays one channel message rather than being cut mid-prose.
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="One paragraph of prose.\n\nAnd a second one, still without a heading.",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = {"ts": "1785418710.000700"}

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                "CSCOUTS|#scout-findings",
                thread_reports=True,
            )

        # Only the lead message and the unconditional @PostHog follow-up reply.
        calls = fake_client.chat_postMessage.call_args_list
        assert len(calls) == 2
        assert "thread_ts" not in calls[0].kwargs
        section_texts = [block["text"]["text"] for block in calls[0].kwargs["blocks"] if block["type"] == "section"]
        assert len(section_texts) == 1
        assert "second one" in section_texts[0]
        assert calls[1].kwargs["blocks"][0]["type"] == "context"

    def test_reply_posted_regardless_of_ai_approval(self) -> None:
        # The Slack follow-up invite is unconditional — no AI-approval gate on scout output.
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="Checkout failed",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = {"ts": "1785418710.000400"}

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                "CSCOUTS|#scout-findings",
            )

        assert fake_client.chat_postMessage.call_count == 2
        reply = fake_client.chat_postMessage.call_args_list[1].kwargs
        assert reply["thread_ts"] == "1785418710.000400"

    def test_reply_transport_failure_does_not_fail_delivery(self) -> None:
        # The parent message already landed, so a failing follow-up reply — even a non-SlackApiError
        # transport error — must be swallowed rather than fail the task and retry the whole delivery.
        emission = self._make_emission()
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.side_effect = [{"ts": "1785418710.000500"}, ConnectionError("boom")]

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            post_scout_emission_to_slack(
                emission,
                integration_id=integration.id,
                channel="CSCOUTS|#scout-findings",
            )

        assert fake_client.chat_postMessage.call_count == 2

    def test_task_skips_report_suppressed_before_delivery(self) -> None:
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.SUPPRESSED,
            title="Unsafe report",
            summary="This report must not leave PostHog.",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                "CSCOUTS|#scout-findings",
            )

        fake_client.chat_postMessage.assert_not_called()

    def test_task_skips_report_suppressed_during_render(self) -> None:
        # The task's pre-render status check passes, but chart rendering can hold the worker for the
        # render budget. A report suppressed in that window must not be posted with its freshly minted
        # image URLs — post_scout_report_to_slack re-reads the status after building the blocks.
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="Checkout failed",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()

        def _suppress_mid_render(report_arg, run_arg, *, delivery_id=None, render_budget=None):
            SignalReport.objects.filter(id=report_arg.id).update(status=SignalReport.Status.SUPPRESSED)
            return [{"type": "header", "text": {"type": "plain_text", "text": "x"}}], "x"

        with (
            patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration,
            patch(
                "products.signals.backend.scout_harness.slack_delivery.build_scout_report_slack_message",
                side_effect=_suppress_mid_render,
            ),
        ):
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                "CSCOUTS|#scout-findings",
            )

        fake_client.chat_postMessage.assert_not_called()

    def test_task_rebuilds_report_whose_content_changed_during_render(self) -> None:
        # An edit that changes content during the render window leaves the report deliverable but the
        # built blocks stale. Not every edit path enqueues a replacement (the inbox PATCH doesn't), so
        # the delivery must rebuild from the current report and post that, never drop it or post stale.
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="Checkout failed",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = {"ts": "1785418710.000900"}
        builds = {"n": 0}

        def _build(report_arg, run_arg, *, delivery_id=None, render_budget=None):
            builds["n"] += 1
            if builds["n"] == 1:
                # A real edit save() bumps updated_at (auto_now); QuerySet.update() would not.
                edited = SignalReport.objects.get(id=report_arg.id)
                edited.title = "Checkout failures (edited)"
                edited.save()
                return [{"type": "header", "text": {"type": "plain_text", "text": "stale"}}], "stale"
            return [{"type": "header", "text": {"type": "plain_text", "text": "fresh"}}], "fresh"

        with (
            patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration,
            patch(
                "products.signals.backend.scout_harness.slack_delivery.build_scout_report_slack_message",
                side_effect=_build,
            ),
        ):
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                "CSCOUTS|#scout-findings",
            )

        # Rebuilt once, and the posted message carries the rebuilt (fresh) blocks, not the stale ones.
        assert builds["n"] == 2
        posted = fake_client.chat_postMessage.call_args_list[0].kwargs
        assert posted["blocks"][0]["text"]["text"] == "fresh"

    @parameterized.expand(["edit_during_the_build", "edit_before_the_build"])
    def test_delivery_yields_to_a_newer_delivery_of_the_same_report(self, edit_timing) -> None:
        # A scout edit that changes content enqueues its own full delivery, which is marked as the
        # report's latest. This delivery must post nothing either way, so the channel gets the edited
        # report once rather than from both. An edit landing before this delivery even starts leaves
        # its build nothing to rebuild, so the yield cannot be conditional on having rebuilt.
        get_client().flushdb()
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="Checkout failed",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        delivery_id = "01864f4c-6957-7d3f-8d85-1d775e527265"
        newer_delivery_id = "0d1b6f3a-1d3f-4a6f-9d2c-7b3e2f1a9c44"
        channel = "CSCOUTS|#scout-findings"
        mark_latest_scout_report_delivery(str(report.id), delivery_id, integration.id, channel)

        def _edit_and_supersede() -> None:
            edited = SignalReport.objects.get(id=report.id)
            edited.title = "Checkout failures (edited)"
            edited.save()
            mark_latest_scout_report_delivery(str(report.id), newer_delivery_id, integration.id, channel)

        if edit_timing == "edit_before_the_build":
            _edit_and_supersede()

        def _build(report_arg, run_arg, *, delivery_id=None, render_budget=None):
            if edit_timing == "edit_during_the_build":
                _edit_and_supersede()
            return [{"type": "header", "text": {"type": "plain_text", "text": "stale"}}], "stale"

        with (
            patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration,
            patch(
                "products.signals.backend.scout_harness.slack_delivery.build_scout_report_slack_message",
                side_effect=_build,
            ),
        ):
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                delivery_id,
                integration.id,
                channel,
            )

        fake_client.chat_postMessage.assert_not_called()

    @parameterized.expand(
        [
            # A note carries its own content and is never marked as a latest delivery, so a newer
            # full delivery of the report is not a replacement for it.
            ("note_only", "Re-validated on the next run", "same_channel", "01234567-89ab-cdef-0123-456789abcdef"),
            # Another channel's delivery is not competing for this one's channel.
            ("other_destination", None, "other_channel", "01234567-89ab-cdef-0123-456789abcdef"),
            # A marker that cannot be decoded reads as absent rather than raising into the task,
            # which would retry and then drop the report.
            ("unreadable_marker", None, "same_channel", b"\xff\xfe not utf-8"),
        ]
    )
    def test_delivery_posts_when_the_marker_is_not_a_claim_over_it(
        self, _name, edit_note, marker_channel, marker_value
    ) -> None:
        get_client().flushdb()
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="Checkout failed",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = FakeSlackResponse({"ts": "1785418710.000700"})
        channel = "CSCOUTS|#scout-findings"
        marked_channel = channel if marker_channel == "same_channel" else "CELSEWHERE|#other"
        get_client().set(
            _latest_report_delivery_key(str(report.id), integration.id, marked_channel),
            marker_value,
        )

        with patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration:
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                channel,
                edit_note,
            )

        assert fake_client.chat_postMessage.call_args_list[0].kwargs["channel"] == "CSCOUTS"

    def test_delivery_posts_with_the_token_stored_after_the_render(self) -> None:
        # The chart build can hold the worker for minutes, long enough for the workspace to be
        # reconnected. That writes a new token to the same integration row and revokes the old one,
        # and a post with the old token fails as permanent, so the row is read again before the post.
        get_client().flushdb()
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="Checkout failed",
        )
        integration = Integration.objects.create(
            team=self.team, kind=Integration.IntegrationKind.SLACK, sensitive_config={"access_token": "xoxb-old"}
        )
        fake_client = MagicMock()
        fake_client.chat_postMessage.return_value = FakeSlackResponse({"ts": "1785418710.000700"})

        def _build(report_arg, run_arg, *, delivery_id=None, render_budget=None):
            Integration.objects.filter(id=integration.id).update(sensitive_config={"access_token": "xoxb-new"})
            return [{"type": "header", "text": {"type": "plain_text", "text": "Checkout failures"}}], "fallback"

        with (
            patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration,
            patch(
                "products.signals.backend.scout_harness.slack_delivery.build_scout_report_slack_message",
                side_effect=_build,
            ),
        ):
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                "CSCOUTS|#scout-findings",
            )

        posted_with = slack_integration.call_args_list[-1].args[0]
        assert posted_with.sensitive_config == {"access_token": "xoxb-new"}
        assert fake_client.chat_postMessage.call_args_list[0].kwargs["channel"] == "CSCOUTS"

    @parameterized.expand(
        [
            # Nothing else claimed the report, so the claim this enqueue made goes down with it.
            ("own_claim_is_released", None, None),
            # A newer delivery claimed the report between the mark and the failure. That claim names
            # a task that really is queued, so it has to survive this one's cleanup.
            ("newer_claim_survives", "0d1b6f3a-1d3f-4a6f-9d2c-7b3e2f1a9c44", "0d1b6f3a-1d3f-4a6f-9d2c-7b3e2f1a9c44"),
        ]
    )
    def test_enqueue_claims_the_report_before_publishing_and_releases_it_on_failure(
        self, _name, racing_claim, expected_marker
    ) -> None:
        # The claim has to be in place before the broker call: an earlier delivery reading the marker
        # in the gap would see none and post the report this one is about to post again. A publish
        # that then fails has to take the claim back down, since it names a task that will never run
        # and would otherwise silence the report for the marker's whole TTL.
        get_client().flushdb()
        report_id = "ddab8ee5-2bb8-4226-b145-6732d31dc344"
        channel = "CSCOUTS|#scout-findings"
        delivery_id = "b316c1d1-6901-49eb-8223-96d4df69f67f"
        key = _latest_report_delivery_key(report_id, 9, channel)
        observed: dict[str, bytes | None] = {}

        def _fail_to_publish(*args, **kwargs):
            observed["claim_at_publish"] = get_client().get(key)
            if racing_claim is not None:
                mark_latest_scout_report_delivery(report_id, racing_claim, 9, channel)
            raise RuntimeError("broker down")

        with (
            patch.object(deliver_scout_slack_output, "delay", side_effect=_fail_to_publish),
            patch("products.signals.backend.tasks.capture_exception"),
        ):
            enqueue_scout_slack_delivery(
                team_id=self.team.id,
                output_type="report",
                output_id=report_id,
                run_id="e3865391-bc89-44e6-86f7-2d4405627daf",
                delivery_id=delivery_id,
                integration_id=9,
                channel=channel,
            )

        claim_at_publish = observed["claim_at_publish"]
        assert claim_at_publish is not None and claim_at_publish.decode() == delivery_id
        marker = get_client().get(key)
        assert (marker.decode() if marker is not None else None) == expected_marker

    def test_task_skips_report_suppressed_during_rebuild(self) -> None:
        # A content edit triggers a rebuild, and the report is then suppressed during that second
        # render. The status recheck runs after every build, so the now-undeliverable report (and its
        # freshly minted image URLs) is skipped rather than posted.
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="Checkout failed",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        builds = {"n": 0}

        def _build(report_arg, run_arg, *, delivery_id=None, render_budget=None):
            builds["n"] += 1
            if builds["n"] == 1:
                # Bump updated_at so the first build is treated as stale and a rebuild is triggered.
                edited = SignalReport.objects.get(id=report_arg.id)
                edited.title = "Checkout failures (edited)"
                edited.save()
            else:
                # The report is suppressed while the rebuild renders.
                SignalReport.objects.filter(id=report_arg.id).update(status=SignalReport.Status.SUPPRESSED)
            return [{"type": "header", "text": {"type": "plain_text", "text": "x"}}], "x"

        with (
            patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration,
            patch(
                "products.signals.backend.scout_harness.slack_delivery.build_scout_report_slack_message",
                side_effect=_build,
            ),
        ):
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                "CSCOUTS|#scout-findings",
            )

        assert builds["n"] == 2
        fake_client.chat_postMessage.assert_not_called()

    @parameterized.expand(["invalid_blocks", "invalid_blocks_format"])
    def test_report_posts_without_its_charts_when_slack_rejects_them(self, error_code) -> None:
        # Slack fetches every image URL itself, so a chart it cannot reach takes the whole message
        # down with a code that is not permanent — the delivery would retry and then drop a report
        # that used to post as text. The prose and the report link go out instead.
        emission = self._make_emission()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failures",
            summary="Checkout failed",
        )
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        fake_client = MagicMock()
        fake_client.chat_postMessage.side_effect = [
            SlackApiError(message="rejected", response=FakeSlackResponse({"error": error_code})),
            FakeSlackResponse({"ts": "1785418710.000500"}),
            FakeSlackResponse({"ts": "1785418710.000600"}),
        ]
        chart_blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "*Signups*"}, "block_id": f"{PREFIX}1:0"},
            {"type": "image", "image_url": "https://img/1", "alt_text": "Signups", "block_id": f"{PREFIX}1:1"},
        ]

        with (
            patch("products.signals.backend.scout_harness.slack_delivery.SlackIntegration") as slack_integration,
            patch(
                "products.signals.backend.scout_harness.slack_delivery.build_scout_report_chart_blocks",
                return_value=chart_blocks,
            ),
        ):
            slack_integration.return_value.client = fake_client
            deliver_scout_slack_output.run(
                self.team.id,
                "report",
                str(report.id),
                str(emission.scout_run_id),
                "01864f4c-6957-7d3f-8d85-1d775e527265",
                integration.id,
                "CSCOUTS|#scout-findings",
            )

        rejected, resent = (call.kwargs["blocks"] for call in fake_client.chat_postMessage.call_args_list[:2])
        assert [b["type"] for b in rejected] == ["context", "header", "section", "section", "image", "actions"]
        assert [b["type"] for b in resent] == ["context", "header", "section", "actions"]

    def test_task_retries_transient_delivery_failure(self) -> None:
        emission = self._make_emission()
        error = SlackApiError(
            message="rate limited",
            response=FakeSlackResponse({"error": "ratelimited"}, headers={"retry-after": "120"}),
        )

        with patch(
            "products.signals.backend.tasks.post_scout_emission_to_slack",
            side_effect=error,
        ):
            with pytest.raises(Retry) as retry:
                deliver_scout_slack_output.apply(
                    args=(
                        self.team.id,
                        "finding",
                        str(emission.id),
                        str(emission.scout_run_id),
                        str(emission.id),
                        1,
                        "CSCOUTS|#scout-findings",
                    ),
                    throw=True,
                )

        assert retry.value.when == 120

    def test_task_captures_known_permanent_failure_without_retry(self) -> None:
        emission = self._make_emission()
        error = ScoutSlackPermanentDeliveryError("channel unavailable", error_code="channel_not_found")

        with (
            patch("products.signals.backend.tasks.post_scout_emission_to_slack", side_effect=error),
            patch("products.signals.backend.tasks.capture_exception") as capture,
        ):
            deliver_scout_slack_output.run(
                self.team.id,
                "finding",
                str(emission.id),
                str(emission.scout_run_id),
                str(emission.id),
                9,
                "CMISSING|#missing",
            )

        capture.assert_called_once_with(
            error,
            {
                "team_id": self.team.id,
                "output_type": "finding",
                "output_id": str(emission.id),
                "run_id": str(emission.scout_run_id),
                "integration_id": 9,
                "error_code": "channel_not_found",
            },
        )

    def test_task_captures_transient_failure_after_retries_are_exhausted(self) -> None:
        emission = self._make_emission()
        error = ConnectionError("Slack unavailable")

        with (
            patch("products.signals.backend.tasks.post_scout_emission_to_slack", side_effect=error),
            patch("products.signals.backend.tasks.capture_exception") as capture,
        ):
            result = deliver_scout_slack_output.apply(
                args=(
                    self.team.id,
                    "finding",
                    str(emission.id),
                    str(emission.scout_run_id),
                    str(emission.id),
                    9,
                    "CSCOUTS|#scout-findings",
                ),
                retries=5,
                throw=True,
            )

        assert result.successful()
        capture.assert_called_once_with(
            error,
            {
                "team_id": self.team.id,
                "output_type": "finding",
                "output_id": str(emission.id),
                "run_id": str(emission.scout_run_id),
                "integration_id": 9,
                "error_code": None,
                "attempts": 6,
            },
        )

    def test_enqueue_captures_broker_failure(self) -> None:
        error = ConnectionError("broker unavailable")

        with (
            patch.object(deliver_scout_slack_output, "delay", side_effect=error),
            patch("products.signals.backend.tasks.capture_exception") as capture,
        ):
            enqueue_scout_slack_delivery(
                team_id=self.team.id,
                output_type="report",
                output_id="ddab8ee5-2bb8-4226-b145-6732d31dc344",
                run_id="e3865391-bc89-44e6-86f7-2d4405627daf",
                delivery_id="b316c1d1-6901-49eb-8223-96d4df69f67f",
                integration_id=9,
                channel="CSCOUTS|#scout-findings",
            )

        capture.assert_called_once_with(
            error,
            {
                "team_id": self.team.id,
                "output_type": "report",
                "output_id": "ddab8ee5-2bb8-4226-b145-6732d31dc344",
                "run_id": "e3865391-bc89-44e6-86f7-2d4405627daf",
                "integration_id": 9,
            },
        )

    def test_queue_captures_failure_before_enqueue(self) -> None:
        error = ConnectionError("database unavailable")
        run_id = "e3865391-bc89-44e6-86f7-2d4405627daf"

        with (
            patch.object(SignalScoutRun.all_teams, "select_related", side_effect=error),
            patch("products.signals.backend.scout_harness.slack_delivery_queue.capture_exception") as capture,
        ):
            queue_configured_scout_slack_delivery(
                run_id=run_id,
                output_type="report",
                output_id="ddab8ee5-2bb8-4226-b145-6732d31dc344",
            )

        capture.assert_called_once_with(
            error,
            {
                "run_id": run_id,
                "output_type": "report",
                "output_id": "ddab8ee5-2bb8-4226-b145-6732d31dc344",
            },
        )
