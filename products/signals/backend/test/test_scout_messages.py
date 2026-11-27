from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import AsyncMock, patch

from django.apps import apps
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.team.team import Team

from products.signals.backend.artefact_schemas import SafetyJudgment
from products.signals.backend.models import (
    SignalReport,
    SignalScoutConfig,
    SignalScoutMessage,
    SignalScoutMessageDelivery,
    SignalScoutRun,
)
from products.signals.backend.scout_harness.limits import STALE_RUN_CUTOFF_S
from products.signals.backend.scout_harness.message_routes import MAX_MESSAGE_BODY_LENGTH, MAX_MESSAGE_TITLE_LENGTH
from products.signals.backend.scout_harness.message_send import DELIVERY_REPUBLISH_AFTER, send_queued_scout_messages
from products.signals.backend.scout_harness.runner import _message_routes_for_run, _self_heal_stale_runs
from products.signals.backend.scout_harness.slack_delivery import (
    ScoutSlackPermanentDeliveryError,
    post_scout_message_to_slack,
)
from products.signals.backend.scout_harness.tools.messages import MESSAGE_REFUSALS_METADATA_KEY
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run
from products.skills.backend.models.skills import LLMSkill

_SKILL = "signals-scout-general"
_FLAG_CHECKS = (
    "products.signals.backend.scout_harness.views.scout_send_message_enabled",
    "products.signals.backend.scout_harness.tools.messages.scout_send_message_enabled",
    "products.signals.backend.scout_harness.message_send.scout_send_message_enabled",
    "products.signals.backend.scout_harness.slack_delivery.scout_send_message_enabled",
)
_ENQUEUE = "products.signals.backend.scout_harness.message_send.enqueue_scout_slack_delivery"
_CAPTURE = "products.signals.backend.scout_harness.message_send.capture_batch_internal"
_JUDGE = "products.signals.backend.scout_harness.tools.messages.judge_edited_report_content"


@contextmanager
def _messaging(enabled: bool = True):
    with (
        patch(_FLAG_CHECKS[0], return_value=enabled),
        patch(_FLAG_CHECKS[1], return_value=enabled),
        patch(_FLAG_CHECKS[2], return_value=enabled),
        patch(_FLAG_CHECKS[3], return_value=enabled),
    ):
        yield


def _route(key: str, *targets: dict) -> dict:
    return {"key": key, "when": f"When {key} happens", "to": list(targets)}


_DM = {"type": "slack_dm", "user": "U0123ABC456"}
_CHANNEL = {"type": "slack_channel", "channel": "C0456DEF789|#alerts"}


class _MessagesFixture:
    team: Team
    organization: Any

    def _set_routes(self, config: SignalScoutConfig, *routes: dict, integration_id: int | None = None) -> None:
        config.output_destinations = {
            "slack": {"integration_id": integration_id or self.integration.id},
            "messages": list(routes),
        }
        config.save(update_fields=["output_destinations"])

    def _run(self, *, task_run_status: str | None = None, **overrides: Any) -> SignalScoutRun:
        run = _make_run(self.team, task_run_status=task_run_status, **overrides)
        assert run.scout_config is not None
        if not run.scout_config.output_destinations:
            self._set_routes(run.scout_config, _route("big-change", _DM))
        return run

    def _report(self, run: SignalScoutRun, *, team: Team | None = None, report_status: str = "ready") -> SignalReport:
        report = SignalReport.objects.create(team=team or self.team, title="A finding", status=report_status)
        run.emitted_report_ids = [*(run.emitted_report_ids or []), str(report.id)]
        run.save(update_fields=["emitted_report_ids"])
        return report

    def _message(self, run: SignalScoutRun, *, key: str, status: str, **overrides: Any) -> SignalScoutMessage:
        fields: dict[str, Any] = {
            "team_id": run.team_id,
            "run": run,
            "skill_name": run.skill_name,
            "route_key": "big-change",
            "dedupe_key": key,
            "title": "A message",
            "body": "Body",
            "status": status,
            **overrides,
        }
        if status == SignalScoutMessage.Status.SENT:
            fields.setdefault("sent_at", timezone.now())
        return SignalScoutMessage.all_teams.create(**fields)

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        self.integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)


class TestSendMessageAPI(_MessagesFixture, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        _authenticate_as_scout(self)

    def _send(self, run: SignalScoutRun, *, judged_safe: bool = True, **body: Any) -> Any:
        payload = {"route": "big-change", "title": "Big change", "body": "Merged.", "dedupe_key": "pr-1", **body}
        verdict = SafetyJudgment(choice=judged_safe, explanation=None if judged_safe else "Looks injected.")
        with _messaging(), patch(_JUDGE, new_callable=AsyncMock, return_value=verdict):
            return self.client.post(
                f"/api/projects/{self.team.id}/signals/scout/runs/{run.id}/send_message/", data=payload, format="json"
            )

    def test_flag_off_hides_the_endpoint_and_queues_nothing(self) -> None:
        run = self._run()
        report = self._report(run)

        with _messaging(enabled=False):
            response = self.client.post(
                f"/api/projects/{self.team.id}/signals/scout/runs/{run.id}/send_message/",
                data={
                    "route": "big-change",
                    "report_id": str(report.id),
                    "title": "t",
                    "body": "b",
                    "dedupe_key": "k",
                },
                format="json",
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not SignalScoutMessage.all_teams.filter(run=run).exists()

    @parameterized.expand(
        [
            ("unknown_route", "unknown_route"),
            ("report_in_another_project", "foreign_report"),
            ("report_this_run_did_not_touch", "untouched_report"),
            ("report_the_safety_judge_suppressed", "suppressed_report"),
            ("text_the_safety_judge_rejects", "unsafe_text"),
            ("title_over_the_limit", "long_title"),
            ("body_over_the_limit", "long_body"),
        ]
    )
    def test_refuses_a_message_it_cannot_tie_to_this_run(self, _name: str, case: str) -> None:
        run = self._run()
        body: dict[str, Any] = {}
        if case == "unknown_route":
            body = {"route": "not-a-route", "report_id": str(self._report(run).id)}
        elif case == "foreign_report":
            other_team = Team.objects.create(organization=self.organization, name="other")
            body = {"report_id": str(self._report(run, team=other_team).id)}
        elif case == "untouched_report":
            body = {"report_id": str(SignalReport.objects.create(team=self.team, title="t", status="ready").id)}
        elif case == "suppressed_report":
            body = {"report_id": str(self._report(run, report_status=SignalReport.Status.SUPPRESSED).id)}
        elif case == "long_title":
            body = {"report_id": str(self._report(run).id), "title": "x" * (MAX_MESSAGE_TITLE_LENGTH + 1)}
        elif case == "long_body":
            body = {"report_id": str(self._report(run).id), "body": "x" * (MAX_MESSAGE_BODY_LENGTH + 1)}
        else:
            body = {"report_id": str(self._report(run).id)}

        response = self._send(run, judged_safe=case != "unsafe_text", **body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert not SignalScoutMessage.all_teams.filter(run=run).exists()
        if case in ("long_title", "long_body"):
            limit = MAX_MESSAGE_TITLE_LENGTH if case == "long_title" else MAX_MESSAGE_BODY_LENGTH
            assert str(limit) in response.json()["detail"]

    def test_a_second_call_on_the_same_route_and_key_replaces_the_queued_message(self) -> None:
        run = self._run()
        report = self._report(run)

        first = self._send(run, report_id=str(report.id), title="First draft")
        second = self._send(run, report_id=str(report.id), title="Second draft")

        assert first.json()["outcome"] == "queued"
        assert second.json()["outcome"] == "replaced"
        queued = SignalScoutMessage.all_teams.get(run=run)
        assert queued.title == "Second draft"
        assert queued.status == SignalScoutMessage.Status.QUEUED

    def test_the_sixth_message_in_24_hours_is_refused_and_recorded_on_the_run(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        earlier = self._run(task_run_status=TaskRun.Status.COMPLETED)
        for index in range(5):
            self._message(earlier, key=f"pr-{index}", status=SignalScoutMessage.Status.SENT)
        run = self._run()

        response = self._send(run, report_id=str(self._report(run).id), dedupe_key="pr-new")

        assert response.json()["outcome"] == "over_cap"
        assert not SignalScoutMessage.all_teams.filter(run=run).exists()
        run.refresh_from_db()
        assert [refusal["outcome"] for refusal in (run.metadata or {})[MESSAGE_REFUSALS_METADATA_KEY]] == ["over_cap"]

    def test_a_queued_message_left_by_a_failed_send_stops_counting_after_the_window(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        earlier = self._run(task_run_status=TaskRun.Status.FAILED)
        for index in range(5):
            stuck = self._message(earlier, key=f"pr-{index}", status=SignalScoutMessage.Status.QUEUED)
            SignalScoutMessage.all_teams.filter(pk=stuck.pk).update(created_at=timezone.now() - timedelta(days=2))
        run = self._run()

        response = self._send(run, report_id=str(self._report(run).id), dedupe_key="pr-new")

        assert response.json()["outcome"] == "queued"

    @parameterized.expand([("sent", SignalScoutMessage.Status.SENT), ("queued_by_another_run", "queued")])
    def test_a_route_and_key_already_on_its_way_is_refused_with_the_recent_keys(
        self, _name: str, earlier_status: str
    ) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        earlier = self._run(task_run_status=TaskRun.Status.IN_PROGRESS)
        self._message(earlier, key="pr-1", status=earlier_status)
        self._message(earlier, key="pr-2", status=SignalScoutMessage.Status.SENT)
        run = self._run()

        response = self._send(run, report_id=str(self._report(run).id), dedupe_key="pr-1")

        body = response.json()
        assert body["outcome"] == "duplicate"
        assert set(body["recent_dedupe_keys"]) == {"pr-1", "pr-2"}
        assert not SignalScoutMessage.all_teams.filter(run=run).exists()

    def test_a_dry_run_stores_a_dry_run_row_without_a_report_and_posts_nothing(self) -> None:
        run = self._run()
        assert run.scout_config is not None
        run.scout_config.emit = False
        run.scout_config.save(update_fields=["emit"])

        response = self._send(run)
        with _messaging(), patch(_ENQUEUE) as enqueue, self.captureOnCommitCallbacks(execute=True):
            send_queued_scout_messages(team_id=self.team.id, run_id=run.id)

        assert response.json()["outcome"] == "dry_run"
        row = SignalScoutMessage.all_teams.get(run=run)
        assert row.status == SignalScoutMessage.Status.DRY_RUN
        assert row.report_id is None
        enqueue.assert_not_called()

    def test_a_dry_run_message_resent_after_emit_is_turned_on_becomes_a_queued_message(self) -> None:
        run = self._run()
        assert run.scout_config is not None
        SignalScoutConfig.all_teams.filter(pk=run.scout_config.pk).update(emit=False)
        self._send(run)
        SignalScoutConfig.all_teams.filter(pk=run.scout_config.pk).update(emit=True)
        report = self._report(run)

        response = self._send(run, report_id=str(report.id))

        assert response.status_code == status.HTTP_200_OK, response.json()
        row = SignalScoutMessage.all_teams.get(run=run)
        assert (row.status, row.report_id) == (SignalScoutMessage.Status.QUEUED, report.id)


class TestScoutMessageRoutesConfigAPI(_MessagesFixture, APIBaseTest):
    def _patch(self, config: SignalScoutConfig, destinations: dict) -> Any:
        return self.client.patch(
            f"/api/projects/{self.team.id}/signals/scout/configs/{config.id}/",
            data={"output_destinations": destinations},
            format="json",
        )

    def _upsert(self, destinations: dict) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/signals/scout/configs/",
            data={"skill_name": "signals-scout-foo", "output_destinations": destinations},
            format="json",
        )

    def test_an_update_keeps_omitted_routes_and_clears_them_on_an_empty_list(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        self._set_routes(config, _route("big-change", _DM))

        kept = self._patch(config, {"slack": {"integration_id": self.integration.id, "channel": "C0456DEF789"}})
        config.refresh_from_db()
        routes_after_omission = config.output_destinations.get("messages")
        cleared = self._patch(config, {"slack": {"integration_id": self.integration.id}, "messages": []})
        config.refresh_from_db()

        assert kept.status_code == status.HTTP_200_OK, kept.json()
        assert [route["key"] for route in routes_after_omission] == ["big-change"]
        assert cleared.status_code == status.HTTP_200_OK, cleared.json()
        assert not config.output_destinations.get("messages")

    def test_turning_slack_delivery_off_keeps_the_routes_and_their_integration(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        config.output_destinations = {
            "slack": {"integration_id": self.integration.id, "channel": "C0456DEF789"},
            "messages": [_route("big-change", _DM)],
        }
        config.save(update_fields=["output_destinations"])

        response = self._patch(config, {})

        assert response.status_code == status.HTTP_200_OK, response.json()
        config.refresh_from_db()
        assert config.output_destinations["slack"] == {"integration_id": self.integration.id}
        assert [route["key"] for route in config.output_destinations["messages"]] == ["big-change"]

    def test_a_route_the_parser_would_skip_still_needs_skill_editor_access(self) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        numeric_key_route = {"key": 123, "when": "When it happens", "to": [_DM]}

        with patch(
            "products.signals.backend.scout_harness.views.SignalScoutConfigViewSet._has_skill_editor_access",
            return_value=False,
        ):
            response = self._patch(
                config, {"slack": {"integration_id": self.integration.id}, "messages": [numeric_key_route]}
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        config.refresh_from_db()
        assert not config.output_destinations.get("messages")

    def test_an_upsert_with_an_empty_list_clears_the_stored_routes(self) -> None:
        LLMSkill.objects.create(team=self.team, name="signals-scout-foo", description="d", body="watch")
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        self._set_routes(config, _route("big-change", _DM))

        with patch("products.signals.backend.scout_harness.views.SignalScoutConfigViewSet._assert_can_register_scout"):
            response = self._upsert({"slack": {"integration_id": self.integration.id}, "messages": []})

        assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), response.json()
        config.refresh_from_db()
        assert not config.output_destinations.get("messages")

    @parameterized.expand(
        [
            ("no_slack_integration", {"messages": [_route("big-change", _DM)]}),
            (
                "target_without_type",
                {"slack": {"integration_id": 0}, "messages": [_route("k", {"user": "U0123ABC456"})]},
            ),
            ("route_without_key", {"slack": {"integration_id": 0}, "messages": [{"when": "w", "to": [_DM]}]}),
        ]
    )
    def test_malformed_routes_are_rejected_with_a_400(self, _name: str, destinations: dict) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-foo")
        if "slack" in destinations:
            destinations = {**destinations, "slack": {"integration_id": self.integration.id}}

        response = self._patch(config, destinations)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        config.refresh_from_db()
        assert not config.output_destinations.get("messages")


class TestSendQueuedScoutMessages(_MessagesFixture, BaseTest):
    def _send(self, run: SignalScoutRun, *, enabled: bool = True) -> tuple[Any, Any]:
        with (
            _messaging(enabled),
            patch(_ENQUEUE) as enqueue,
            patch(_CAPTURE) as capture,
            self.captureOnCommitCallbacks(execute=True),
        ):
            send_queued_scout_messages(team_id=self.team.id, run_id=run.id)
        return enqueue, capture

    def test_one_event_per_message_and_one_post_per_unique_recipient(self) -> None:
        run = self._run()
        assert run.scout_config is not None
        # The same member twice, once in the picker's `id|@name` form, resolves to one recipient.
        self._set_routes(
            run.scout_config, _route("big-change", _DM, {"type": "slack_dm", "user": "U0123ABC456|@sam"}, _CHANNEL)
        )
        message = self._message(run, key="pr-1", status=SignalScoutMessage.Status.QUEUED, report=self._report(run))

        enqueue, capture = self._send(run)

        message.refresh_from_db()
        assert message.status == SignalScoutMessage.Status.SENT
        assert sorted(call.kwargs["channel"] for call in enqueue.call_args_list) == ["C0456DEF789", "U0123ABC456"]
        assert capture.call_count == 1
        events = capture.call_args.kwargs["events"]
        assert [event["event"] for event in events] == ["$scout_message"]
        assert events[0]["properties"]["dedupe_key"] == "pr-1"
        assert events[0]["properties"]["body"] == "Body"

    @parameterized.expand(
        [
            ("flag_off", "flag_off"),
            ("emit_turned_off_during_the_run", "emit_off"),
            ("route_removed_during_the_run", "route_removed"),
            ("report_deleted_during_the_run", "report_hidden"),
            ("sent_by_an_overlapping_run", "duplicate"),
        ]
    )
    def test_a_queued_message_the_live_config_no_longer_allows_is_dropped(self, _name: str, reason: str) -> None:
        run = self._run()
        assert run.scout_config is not None
        report = self._report(run)
        message = self._message(run, key="pr-1", status=SignalScoutMessage.Status.QUEUED, report=report)
        if reason == "route_removed":
            self._set_routes(run.scout_config, _route("another-route", _DM))
        elif reason == "emit_off":
            SignalScoutConfig.all_teams.filter(pk=run.scout_config.pk).update(emit=False)
        elif reason == "report_hidden":
            SignalReport.objects.filter(pk=report.pk).update(status=SignalReport.Status.DELETED)
        elif reason == "duplicate":
            self._message(self._run(), key="pr-1", status=SignalScoutMessage.Status.SENT)

        enqueue, capture = self._send(run, enabled=reason != "flag_off")

        message.refresh_from_db()
        assert (message.status, message.drop_reason) == (SignalScoutMessage.Status.DROPPED, reason)
        enqueue.assert_not_called()
        capture.assert_not_called()

    def test_a_run_end_recovers_what_earlier_runs_of_the_scout_left_behind(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        earlier = self._run(task_run_status=TaskRun.Status.FAILED)
        stranded = self._message(
            earlier, key="pr-1", status=SignalScoutMessage.Status.QUEUED, report=self._report(earlier)
        )
        sent = self._message(earlier, key="pr-2", status=SignalScoutMessage.Status.SENT, report=self._report(earlier))
        # A daily scout's next run ends more than a day after the failed send.
        a_daily_schedule_later = timezone.now() - timedelta(hours=30)
        SignalScoutMessage.all_teams.filter(pk=stranded.pk).update(created_at=a_daily_schedule_later)
        unpublished = SignalScoutMessageDelivery.all_teams.create(
            team_id=self.team.id,
            message=sent,
            target_type=SignalScoutMessageDelivery.TargetType.SLACK_DM,
            target_id="U0123ABC456",
            integration_id=self.integration.id,
        )
        SignalScoutMessageDelivery.all_teams.filter(pk=unpublished.pk).update(
            created_at=a_daily_schedule_later,
            updated_at=timezone.now() - DELIVERY_REPUBLISH_AFTER - timedelta(minutes=1),
        )

        enqueue, _capture = self._send(self._run())

        stranded.refresh_from_db()
        assert stranded.status == SignalScoutMessage.Status.SENT
        published = {call.kwargs["output_id"] for call in enqueue.call_args_list}
        assert str(unpublished.pk) in published
        assert len(published) == 2


class TestReapedRunSendsQueuedMessages(_MessagesFixture, BaseTest):
    def test_a_run_reaped_after_a_worker_loss_sends_its_queued_messages(self) -> None:
        # A reaped run never reaches the runner's own ending, so the reap is its only send.
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._run()
        TaskRun.objects.filter(id=run.task_run_id).update(
            created_at=timezone.now() - timedelta(seconds=STALE_RUN_CUTOFF_S + 60)
        )
        message = self._message(run, key="pr-1", status=SignalScoutMessage.Status.QUEUED, report=self._report(run))

        with _messaging(), patch(_ENQUEUE) as enqueue, self.captureOnCommitCallbacks(execute=True):
            _self_heal_stale_runs(self.team.id, _SKILL)

        message.refresh_from_db()
        assert message.status == SignalScoutMessage.Status.SENT
        assert enqueue.call_count == 1


class TestMessageRoutesForRun(_MessagesFixture, BaseTest):
    @parameterized.expand(
        [("flag_on", True, False, 1), ("flag_off", False, False, 0), ("private_trial", True, True, 0)]
    )
    def test_the_prompt_lists_routes_only_when_the_run_may_send(
        self, _name: str, enabled: bool, is_private_trial: bool, expected: int
    ) -> None:
        run = self._run()
        assert run.scout_config is not None

        with patch("products.signals.backend.scout_harness.runner.scout_send_message_enabled", return_value=enabled):
            routes = _message_routes_for_run(self.team, run.scout_config, is_private_trial=is_private_trial)

        assert [route.key for route in routes] == ["big-change"] * expected


class TestPostScoutMessageToSlack(_MessagesFixture, BaseTest):
    @parameterized.expand(
        [
            ("recipient_removed", "recipient_removed"),
            ("route_removed", "route_removed"),
            ("flag_turned_off", "flag_off"),
            ("emit_turned_off", "emit_off"),
            ("report_suppressed", "report_hidden"),
        ]
    )
    def test_a_waiting_delivery_is_refused_once_its_route_no_longer_allows_it(self, _name: str, refusal: str) -> None:
        run = self._run()
        assert run.scout_config is not None
        report = self._report(run)
        message = self._message(run, key="pr-1", status=SignalScoutMessage.Status.SENT, report=report)
        delivery = SignalScoutMessageDelivery.all_teams.create(
            team_id=self.team.id,
            message=message,
            target_type=SignalScoutMessageDelivery.TargetType.SLACK_DM,
            target_id="U0123ABC456",
            integration_id=self.integration.id,
        )
        if refusal == "recipient_removed":
            self._set_routes(run.scout_config, _route("big-change", {"type": "slack_dm", "user": "U0999ZZZ999"}))
        elif refusal == "route_removed":
            self._set_routes(run.scout_config, _route("another-route", _DM))
        elif refusal == "emit_off":
            SignalScoutConfig.all_teams.filter(pk=run.scout_config.pk).update(emit=False)
        elif refusal == "report_hidden":
            SignalReport.objects.filter(pk=report.pk).update(status=SignalReport.Status.SUPPRESSED)
        delivery = SignalScoutMessageDelivery.all_teams.select_related(
            "message__run__team", "message__run__scout_config", "message__report"
        ).get(pk=delivery.pk)

        with _messaging(refusal != "flag_off"), self.assertRaises(ScoutSlackPermanentDeliveryError) as raised:
            post_scout_message_to_slack(
                delivery, delivery_id=str(delivery.pk), integration_id=self.integration.id, channel="U0123ABC456"
            )

        assert raised.exception.error_code == refusal
