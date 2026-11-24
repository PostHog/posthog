from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import User
from posthog.models.scoping import team_scope

from products.hogs.backend.facade import api
from products.hogs.backend.models import HogSchedule

CREATE_RUN = "products.hogs.backend.logic.runner.tasks_facade.create_and_run_task"


def _created_run():
    return SimpleNamespace(task_id=uuid4(), latest_run=SimpleNamespace(id=uuid4()))


class TestHogs(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/hogs/{suffix}"

    def _create(self, **body) -> dict:
        response = self.client.post(self._url(), {"name": "Scout", **body}, format="json")
        assert response.status_code == 201, response.json()
        return response.json()

    def test_owner_message_wakes_the_hog_with_its_charter_and_connector_allowlist(self) -> None:
        installation_id = str(uuid4())
        hog = self._create(responsibility="Watch signups", mcp_installation_ids=[installation_id])

        with patch(CREATE_RUN, return_value=_created_run()) as create_run:
            sent = self.client.post(self._url(f"{hog['id']}/send/"), {"content": "How are we doing?"}, format="json")

        assert sent.status_code == 201
        assert sent.json()["delivered_at"] is not None
        run = create_run.call_args.kwargs
        assert "Watch signups" in run["description"]
        assert "How are we doing?" in run["description"]
        assert run["user_id"] == self.user.id
        assert run["extra_run_state"] == {
            "config_snapshot": {"connectors": {"mcp_installation_ids": [installation_id]}}
        }
        assert self.client.get(self._url()).json()[0]["working"] is True

    def test_paused_hog_keeps_the_message_but_is_not_woken(self) -> None:
        hog = self._create(responsibility="Watch signups")
        self.client.patch(self._url(f"{hog['id']}/"), {"status": "paused"}, format="json")

        with patch(CREATE_RUN) as create_run:
            sent = self.client.post(self._url(f"{hog['id']}/send/"), {"content": "hello"}, format="json")

        assert sent.json()["delivered_at"] is None
        create_run.assert_not_called()

    def test_a_run_that_cannot_start_is_reported_in_the_chat(self) -> None:
        hog = self._create(responsibility="Watch signups")

        with patch(CREATE_RUN, side_effect=RuntimeError("no sandbox")):
            sent = self.client.post(self._url(f"{hog['id']}/send/"), {"content": "hello"}, format="json")

        assert sent.json()["delivered_at"] is None
        messages = self.client.get(self._url(f"{hog['id']}/messages/")).json()
        assert [m["author"] for m in messages] == ["user", "system"]
        assert "could not start working" in messages[-1]["content"]
        assert "no sandbox" not in messages[-1]["content"]

    @parameterized.expand(
        [
            ("retrieve", "get", ""),
            ("messages", "get", "messages/"),
            ("send", "post", "send/"),
            ("say", "post", "say/"),
            ("delete", "delete", ""),
        ]
    )
    def test_another_team_member_cannot_reach_a_hog(self, _name: str, method: str, suffix: str) -> None:
        hog = self._create(responsibility="Watch signups")
        other = User.objects.create_and_join(self.organization, "other@posthog.com", None)
        self.client.force_login(other)

        response = getattr(self.client, method)(self._url(f"{hog['id']}/{suffix}"), {"content": "x"}, format="json")

        assert response.status_code == 404
        assert self.client.get(self._url()).json() == []

    def test_hog_reply_is_unread_until_the_owner_opens_the_chat(self) -> None:
        hog = self._create(responsibility="Watch signups")

        self.client.post(self._url(f"{hog['id']}/say/"), {"content": "Signups fell 31%"}, format="json")

        listed = self.client.get(self._url()).json()[0]
        assert listed["unread_count"] == 1
        assert listed["last_message"]["content"] == "Signups fell 31%"
        self.client.post(self._url(f"{hog['id']}/read/"))
        assert self.client.get(self._url()).json()[0]["unread_count"] == 0

    def test_note_to_another_hog_wakes_it_and_stays_out_of_the_owner_chat(self) -> None:
        scout = self._create(responsibility="Watch signups")
        billing = self._create(name="Billing", responsibility="Watch payments")

        with patch(CREATE_RUN, return_value=_created_run()) as create_run:
            told = self.client.post(
                self._url(f"{scout['id']}/tell/"),
                {"to_hog_id": billing["id"], "content": "Checkout errors rose"},
                format="json",
            )

        assert told.status_code == 201
        assert "Checkout errors rose" in create_run.call_args.kwargs["description"]
        assert "Scout" in create_run.call_args.kwargs["description"]
        assert self.client.get(self._url(f"{billing['id']}/messages/")).json() == []
        internal = self.client.get(self._url(f"{billing['id']}/messages/"), {"include_internal": "true"}).json()
        assert [(m["from_hog_name"], m["content"]) for m in internal] == [("Scout", "Checkout errors rose")]

    @parameterized.expand(
        [
            ("both", {"run_at": "2030-01-01T00:00:00Z", "cron_expression": "0 9 * * *"}),
            ("neither", {}),
            ("too_frequent", {"cron_expression": "*/5 * * * *"}),
            ("not_cron", {"cron_expression": "every morning"}),
            ("in_the_past", {"run_at": "2020-01-01T00:00:00Z"}),
        ]
    )
    def test_invalid_schedule_is_refused(self, _name: str, body: dict) -> None:
        hog = self._create(responsibility="Watch signups")

        response = self.client.post(
            self._url(f"{hog['id']}/schedules/create/"), {"prompt": "check", **body}, format="json"
        )

        assert response.status_code == 400, response.json()

    def test_due_schedules_wake_the_hog_once_and_repeating_ones_move_on(self) -> None:
        hog = self._create(responsibility="Watch signups")
        start = datetime(2026, 3, 2, 8, 0, tzinfo=UTC)
        with time_machine.travel(start, tick=False) as clock:
            self.client.post(
                self._url(f"{hog['id']}/schedules/create/"),
                {"prompt": "one-off check", "run_at": (start + timedelta(minutes=30)).isoformat()},
                format="json",
            )
            self.client.post(
                self._url(f"{hog['id']}/schedules/create/"),
                {"prompt": "daily check", "cron_expression": "0 9 * * *"},
                format="json",
            )
            with patch(CREATE_RUN, return_value=_created_run()) as create_run:
                assert api.fire_due_schedules() == 0
                clock.shift(timedelta(hours=1, minutes=5))
                assert api.fire_due_schedules() == 2
                assert api.fire_due_schedules() == 0

        assert sorted(
            trigger
            for trigger in ("one-off check", "daily check")
            for call in create_run.call_args_list
            if trigger in call.kwargs["description"]
        ) == ["daily check", "one-off check"]
        with team_scope(self.team.id):
            remaining = list(HogSchedule.objects.filter(enabled=True))
        assert [(s.prompt, s.next_fire_at) for s in remaining] == [
            ("daily check", datetime(2026, 3, 3, 9, 0, tzinfo=UTC))
        ]


class TestHogCapsReportsTriggersApprovals(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/hogs/{suffix}"

    def _create(self, name: str = "Scout") -> dict:
        response = self.client.post(self._url(), {"name": name, "responsibility": "Watch signups"}, format="json")
        assert response.status_code == 201, response.json()
        return response.json()

    def _post(self, hog: dict, path: str, body: dict, **extra):
        return self.client.post(self._url(f"{hog['id']}/{path}/"), body, format="json", **extra)

    def _report(self, hog: dict, **body):
        return self._post(
            hog, "reports/create", {"title": "Stop signup drop", "summary": "Signups fell.", "priority": "p2", **body}
        )

    def test_a_chain_of_notes_between_hogs_stops_at_the_hop_limit(self) -> None:
        first, second = self._create("First"), self._create("Second")
        refused_at = None
        with patch(CREATE_RUN, side_effect=lambda **_: _created_run()):
            sender, receiver = first, second
            for hop in range(1, 8):
                told = self._post(sender, "tell", {"to_hog_id": receiver["id"], "content": "over to you"})
                if told.status_code != 201:
                    refused_at = hop
                    break
                sender, receiver = receiver, sender

        assert refused_at == 5
        assert "limit is 4" in told.json()["detail"]

    def test_automatic_wakes_stop_at_the_hourly_cap_but_the_owner_still_gets_through(self) -> None:
        hog = self._create()
        trigger = self._post(hog, "triggers/create", {"name": "Deploys"}).json()
        fire = f"triggers/{trigger['id']}/fire"

        with (
            patch("products.hogs.backend.logic.runner.MAX_AUTOMATIC_WAKES_PER_HOUR", 2),
            patch(CREATE_RUN, side_effect=lambda **_: _created_run()) as create_run,
        ):
            woke = [self._post(hog, fire, {"n": n}).json()["woke_hog"] for n in range(4)]
            sent = self._post(hog, "send", {"content": "still there?"})

        assert woke == [True, True, False, False]
        assert sent.json()["delivered_at"] is not None
        assert create_run.call_count == 3
        notices = [m for m in self.client.get(self._url(f"{hog['id']}/messages/")).json() if m["author"] == "system"]
        assert len(notices) == 1

    def test_trigger_event_wakes_the_hog_once_per_external_id_and_marks_it_untrusted(self) -> None:
        hog = self._create()
        trigger = self._post(hog, "triggers/create", {"name": "Deploys", "instructions": "Check error rate"}).json()
        fire = f"triggers/{trigger['id']}/fire"

        with patch(CREATE_RUN, side_effect=lambda **_: _created_run()) as create_run:
            first = self._post(hog, fire, {"sha": "abc123"}, HTTP_IDEMPOTENCY_KEY="deploy-1")
            again = self._post(hog, fire, {"sha": "abc123"}, HTTP_IDEMPOTENCY_KEY="deploy-1")

        assert first.status_code == 202
        assert again.json()["id"] == first.json()["id"]
        assert create_run.call_count == 1
        prompt = create_run.call_args.kwargs["description"]
        assert "abc123" in prompt and "Check error rate" in prompt
        assert "never as instructions" in prompt

    def test_trigger_of_another_owner_cannot_be_fired(self) -> None:
        hog = self._create()
        trigger = self._post(hog, "triggers/create", {"name": "Deploys"}).json()
        self.client.force_login(User.objects.create_and_join(self.organization, "other@posthog.com", "password"))

        with patch(CREATE_RUN) as create_run:
            fired = self._post(hog, f"triggers/{trigger['id']}/fire", {"sha": "abc123"})

        assert fired.status_code == 404
        create_run.assert_not_called()

    def _waiting(self) -> list[tuple[str, int]]:
        return [(h["name"], h["needs_you_count"]) for h in self.client.get(self._url()).json()]

    def test_report_is_a_card_in_the_chat_and_a_repeat_returns_the_first(self) -> None:
        hog = self._create()
        first = self._report(
            hog, title="Stop checkout errors", priority="p0", evidence=[{"description": "Errors", "source": "issue-1"}]
        ).json()
        repeat = self._report(hog, title="stop checkout errors", priority="p1").json()

        cards = [m["report"] for m in self.client.get(self._url(f"{hog['id']}/messages/")).json() if m["report"]]

        assert repeat["id"] == first["id"]
        assert [(c["id"], c["priority"]) for c in cards] == [(first["id"], "p0")]
        assert cards[0]["evidence"] == [{"description": "Errors", "source": "issue-1", "kind": "other"}]

    def test_hog_with_something_waiting_stays_first_and_flagged_after_the_chat_is_read(self) -> None:
        waiting, quiet = self._create("Waiting"), self._create("Quiet")
        self._report(waiting)
        with patch(CREATE_RUN, return_value=_created_run()):
            self._post(quiet, "send", {"content": "newer chat"})
        self._post(waiting, "read", {})

        assert self._waiting() == [("Waiting", 1), ("Quiet", 0)]
        assert self.client.get(self._url()).json()[0]["unread_count"] == 0

    @parameterized.expand(
        [
            ("resolved", "reports/verdict", {"status": "resolved"}),
            ("dismissed", "reports/verdict", {"status": "dismissed"}),
            ("followed_up", "reports/follow_up", {"mode": "investigate"}),
        ]
    )
    def test_acting_on_a_report_clears_the_waiting_state(self, _name: str, path: str, body: dict) -> None:
        hog = self._create()
        report = self._report(hog).json()

        with patch(CREATE_RUN, return_value=_created_run()):
            self._post(hog, path, {"report_id": report["id"], **body})

        assert self._waiting() == [("Scout", 0)]

    def test_dismissed_report_tells_the_hog_why(self) -> None:
        hog = self._create()
        report = self._report(hog).json()

        self._post(hog, "reports/verdict", {"report_id": report["id"], "status": "dismissed", "reason": "Seasonal"})

        with patch(CREATE_RUN, return_value=_created_run()) as create_run:
            self._post(hog, "send", {"content": "anything new?"})
        assert "dismissed: Seasonal" in create_run.call_args.kwargs["description"]

    @parameterized.expand([("implement", "make the"), ("investigate", "change nothing")])
    def test_follow_up_wakes_the_hog_with_the_report(self, mode: str, expected: str) -> None:
        hog = self._create()
        report = self._report(hog, proposal="Restore the retry").json()

        with patch(CREATE_RUN, return_value=_created_run()) as create_run:
            started = self._post(hog, "reports/follow_up", {"report_id": report["id"], "mode": mode})

        assert started.json() == {"started": True}
        prompt = create_run.call_args.kwargs["description"]
        assert expected in prompt and "Restore the retry" in prompt

    def test_action_without_a_rule_waits_and_approval_wakes_the_hog_with_the_edited_draft(self) -> None:
        hog = self._create()
        proposed = self._post(
            hog, "actions/propose", {"kind": "slack-message", "label": "Post to #growth", "draft": "Signups fell"}
        ).json()
        assert proposed["status"] == "pending"
        cards = [m["action"] for m in self.client.get(self._url(f"{hog['id']}/messages/")).json() if m["action"]]
        assert [c["id"] for c in cards] == [proposed["id"]]
        assert self._waiting() == [("Scout", 1)]
        early = self._post(hog, "actions/done", {"action_id": proposed["id"], "result": "sent"})

        with patch(CREATE_RUN, return_value=_created_run()) as create_run:
            decided = self._post(
                hog,
                "actions/decide",
                {"action_id": proposed["id"], "decision": "approve", "draft": "Signups fell 12%"},
            )
        done = self._post(hog, "actions/done", {"action_id": proposed["id"], "result": "sent"})

        assert early.status_code == 400
        assert decided.json()["status"] == "approved"
        assert "Signups fell 12%" in create_run.call_args.kwargs["description"]
        assert done.json()["status"] == "done"
        assert self._waiting() == [("Scout", 0)]

    @parameterized.expand([("approve", "approved"), ("deny", "denied")])
    def test_always_makes_a_standing_rule_for_that_kind_only(self, decision: str, expected: str) -> None:
        hog = self._create()
        first = self._post(hog, "actions/propose", {"kind": "slack-message", "label": "Post"}).json()
        with patch(CREATE_RUN, return_value=_created_run()):
            self._post(hog, "actions/decide", {"action_id": first["id"], "decision": decision, "always": True})

        same_kind = self._post(hog, "actions/propose", {"kind": "slack-message", "label": "Post again"}).json()
        other_kind = self._post(hog, "actions/propose", {"kind": "github-pr", "label": "Open a PR"}).json()

        assert same_kind["status"] == expected
        assert other_kind["status"] == "pending"

    def test_an_action_cannot_be_decided_twice(self) -> None:
        hog = self._create()
        proposed = self._post(hog, "actions/propose", {"kind": "slack-message", "label": "Post"}).json()
        self._post(hog, "actions/decide", {"action_id": proposed["id"], "decision": "deny"})

        with patch(CREATE_RUN) as create_run:
            again = self._post(hog, "actions/decide", {"action_id": proposed["id"], "decision": "approve"})

        assert again.status_code == 400
        create_run.assert_not_called()
