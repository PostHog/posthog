from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client.execute import default_settings, sync_execute
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.constants import AvailableFeature
from posthog.models import Element, OrganizationMembership, Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.fixtures import create_app_metric2
from posthog.test.persons import create_person
from posthog.uuidt import UUIDT

from products.access_control.backend.facade.testing import (
    PropertyAccess,
    create_access_control,
    set_member_property_access,
)
from products.messaging.backend.facade.contracts import EmailStatsInterval
from products.messaging.backend.models.email_status_sql import EMAIL_STATUS_DATA_TABLE, EMAIL_STATUS_EVENTS_DATA_TABLE
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.transactional_email_key import TransactionalEmailKey
from products.messaging.backend.services.transactional_email_log import _bucket_starts
from products.workflows.backend.facade.testing import create_workflow_for_test
from products.workflows.backend.facade.transactional_emails import create_code_email_workflow
from products.workflows.backend.facade.writes import destroy_workflow

# `run_failed` is the failure the whole run writes, which ranks below the email step's own failure.
RANK = {
    "queued": 0,
    "run_failed": 1,
    "failed": 2,
    "sent": 3,
    "delivered": 5,
    "bounced": 6,
    "complained": 7,
    "opened": 8,
    "clicked": 9,
}
NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
SLOW_SEND_MINUTES_AGO = 12 * 24 * 60
DELAYED_SEND_MINUTES_AGO = 15 * 24 * 60
IMPACT_COUNTS = {
    "sent": 9,
    "delivered": 7,
    "opened": 5,
    "clicked": 5,
    "not_clicked": 3,
    "untracked": 2,
    "window_days": 7,
}
LONG_ID_SENDS = 20
SMALL_MAX_QUERY_SIZE = 16 * 1024


@time_machine.travel(NOW, tick=False)
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
class TestTransactionalEmailLog(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.workflow_id = create_workflow_for_test(team_id=self.team.id, name="Password reset").id
        self.template = MessageTemplate.objects.create(
            team=self.team, name="Password reset", transactional_hog_flow_id=self.workflow_id
        )

    def _send(
        self,
        minutes_ago: int,
        recipient: str,
        statuses: list[tuple[str, int, str]],
        *,
        team: Team | None = None,
        workflow_id: str | None = None,
        domain: str = "mail.example.com",
        keyed: bool = False,
        status_consumer_behind: bool = False,
    ) -> str:
        queued_at = NOW - timedelta(minutes=minutes_ago)
        message_id = (
            str(uuid5(NAMESPACE_URL, f"{recipient}/{minutes_ago}"))
            if keyed
            else str(UUIDT(unix_time_ms=int(queued_at.timestamp() * 1000)))
        )
        rows = [("queued", 0, ""), *statuses]
        if keyed and not status_consumer_behind:
            # Both tables read the same topic, and a keyed id is found through email_status's sort key.
            sync_execute(
                f"""
                INSERT INTO {EMAIL_STATUS_DATA_TABLE}
                    (team_id, message_id, status, version, created_at, status_at, _timestamp, _offset, _partition)
                VALUES
                """,
                [
                    {
                        "team_id": (team or self.team).id,
                        "message_id": message_id,
                        "status": "queued",
                        "version": int(queued_at.timestamp() * 1000),
                        "created_at": queued_at,
                        "status_at": queued_at,
                        "_timestamp": queued_at,
                        "_offset": 0,
                        "_partition": 0,
                    }
                ],
            )
        sync_execute(
            f"""
            INSERT INTO {EMAIL_STATUS_EVENTS_DATA_TABLE}
                (team_id, message_id, status, version, created_at, status_at, reason, recipient, function_id,
                 sending_domain, _timestamp, _offset, _partition)
            VALUES
            """,
            [
                {
                    "team_id": (team or self.team).id,
                    "message_id": message_id,
                    "status": "failed" if row_status == "run_failed" else row_status,
                    "version": RANK[row_status] * 2**48
                    + int((queued_at + timedelta(seconds=seconds)).timestamp() * 1000),
                    "created_at": queued_at,
                    "status_at": queued_at + timedelta(seconds=seconds),
                    "reason": reason,
                    "recipient": recipient if row_status == "queued" else "",
                    "function_id": (workflow_id or self.workflow_id) if row_status == "queued" else "",
                    "sending_domain": domain if row_status == "sent" else "",
                    "_timestamp": queued_at,
                    "_offset": 0,
                    "_partition": 0,
                }
                for row_status, seconds, reason in rows
            ],
        )
        return message_id

    def _record_distinct_id(self, message_id: str, distinct_id: str, recipient: str, sent_at: datetime) -> None:
        sync_execute(
            """
            INSERT INTO message_assets_data
                (team_id, function_kind, function_id, parent_run_id, invocation_id, action_id, kind, distinct_id,
                 person_id, recipient, subject, status, sent_at, version, is_deleted, html)
            VALUES
            """,
            [
                {
                    "team_id": self.team.id,
                    "function_kind": "hog_flow",
                    "function_id": self.workflow_id,
                    "parent_run_id": "",
                    "invocation_id": message_id,
                    "action_id": "transactional_email",
                    "kind": "email",
                    "distinct_id": distinct_id,
                    "person_id": "",
                    "recipient": recipient,
                    "subject": "Reset",
                    "status": "sent",
                    "sent_at": sent_at,
                    "version": 1,
                    "is_deleted": 0,
                    "html": "",
                }
            ],
        )

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/transactional_email_log/{suffix}"

    def test_lists_sends_newest_first_and_an_open_never_hides_a_bounce(self, _flag):
        oldest = self._send(30, "a@example.com", [("sent", 1, ""), ("delivered", 2, ""), ("opened", 60, "")])
        bounced = self._send(20, "b@example.com", [("sent", 1, ""), ("bounced", 2, "hard"), ("opened", 90, "")])
        newest = self._send(10, "c@example.com", [("sent", 1, ""), ("clicked", 30, "")])
        self._send(5, "other@example.com", [("sent", 1, "")], team=Team.objects.create(organization=self.organization))

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK, response.json()
        results = response.json()["results"]
        assert [(r["message_id"], r["status"], r["reason"], r["opened"], r["clicked"]) for r in results] == [
            (newest, "sent", None, False, True),
            (bounced, "bounced", "hard", True, False),
            (oldest, "delivered", None, True, False),
        ]
        assert results[0]["template_name"] == "Password reset"
        assert results[0]["sending_domain"] == "mail.example.com"

    @parameterized.expand([("restricted", 403), ("granted", 200), ("admin", 200)])
    def test_send_list_follows_property_access(self, _flag, access: PropertyAccess, expected: int) -> None:
        set_member_property_access(team=self.team, membership=self.organization_membership, access=access)
        message_id = self._send(10, "a@example.com", [("sent", 1, "")])

        responses = [
            self.client.get(self._url()),
            self.client.get(self._url(f"{message_id}/")),
            self.client.get(self._url(f"{message_id}/activity/")),
            self.client.get(self._url("stats/")),
        ]

        assert [response.status_code == 403 for response in responses] == [expected == 403] * 4

    @parameterized.expand(
        [
            ("part_of_the_recipient", {"search": "JANE"}, ["jane@example.com"], False),
            ("status", {"status": "failed"}, ["bob@example.com"], False),
            ("page_size", {"limit": 1}, ["bob@example.com"], True),
            ("second_page", {"limit": 1, "offset": 1}, ["jane@example.com"], False),
            ("search_and_status", {"search": "bob", "status": "failed"}, ["bob@example.com"], False),
            ("status_and_reason", {"status": "failed", "reason": "provider_error"}, ["bob@example.com"], False),
            ("reason_no_send_stopped_for", {"status": "failed", "reason": "sending_paused"}, [], False),
            ("search_with_no_match_for_the_status", {"search": "jane", "status": "failed"}, [], False),
            ("status_past_its_last_send", {"status": "sent", "offset": 1}, [], False),
        ]
    )
    def test_filters_the_list(self, _flag, _name, params, expected_recipients, expected_has_more):
        self._send(20, "jane@example.com", [("sent", 1, "")])
        self._send(10, "bob@example.com", [("failed", 1, "provider_error")])

        response = self.client.get(self._url(), params)

        assert [r["recipient"] for r in response.json()["results"]] == expected_recipients
        assert response.json()["has_more"] == expected_has_more

    def test_finds_sends_by_reason_alone_past_the_newest_page(self, _flag):
        self._send(60, "bob@example.com", [("failed", 1, "provider_error")])
        for minutes in range(10, 15):
            self._send(minutes, f"newer-{minutes}@example.com", [("sent", 1, "")])

        response = self.client.get(self._url(), {"reason": "provider_error", "limit": "1"})

        assert [r["recipient"] for r in response.json()["results"]] == ["bob@example.com"]

    @parameterized.expand(
        [("uuidt", False, False), ("keyed", True, False), ("keyed_status_consumer_behind", True, True)]
    )
    def test_finds_a_send_by_message_id_only_inside_the_date_range(self, _flag, _name, keyed, status_consumer_behind):
        message_id = self._send(
            60, "jane@example.com", [("sent", 1, "")], keyed=keyed, status_consumer_behind=status_consumer_behind
        )
        self._send(10, "bob@example.com", [("sent", 1, "")])

        inside = self.client.get(self._url(), {"search": message_id}).json()
        outside = self.client.get(
            self._url(), {"search": message_id, "date_from": (NOW - timedelta(minutes=30)).isoformat()}
        ).json()

        assert [r["message_id"] for r in inside["results"]] == [message_id]
        assert outside["results"] == []

    @parameterized.expand(
        [
            ("list", ""),
            ("stats", "stats/?group_by=template"),
            ("stats_over_time", "stats_over_time/"),
            ("results", "results/?event=purchase&workflow_id={workflow_id}"),
            ("detail", "0d9c1f6e-6f2a-5b1e-9c1a-2f6b4c1d8e3a/"),
        ]
    )
    def test_a_full_query_slot_answers_429(self, _flag, _name, path):
        with patch(
            "products.messaging.backend.presentation.query_concurrency.app_org_concurrency_slot",
            side_effect=ConcurrencyLimitExceeded("Exceeded maximum concurrency limit"),
        ):
            response = self.client.get(self._url(path.format(workflow_id=self.workflow_id)))

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS, response.json()

    @parameterized.expand(
        [("uuidt", False, False), ("keyed", True, False), ("keyed_status_consumer_behind", True, True)]
    )
    def test_shows_one_send_with_its_timeline(self, _flag, _name, keyed, status_consumer_behind):
        message_id = self._send(
            10,
            "jane@example.com",
            [("failed", 1, "provider_error"), ("run_failed", 2, "hog_error")],
            keyed=keyed,
            status_consumer_behind=status_consumer_behind,
        )

        response = self.client.get(self._url(f"{message_id}/"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert (body["status"], body["reason"]) == ("failed", "provider_error")
        # A failed email step also fails its run, and that second failure says less.
        assert [(event["kind"], event["reason"]) for event in body["timeline"]] == [
            ("queued", None),
            ("failed", "provider_error"),
        ]

    def test_looks_past_email_status_only_for_a_recent_keyed_send(self, _flag):
        # Missing from email_status hours after it was queued, a send is gone, not waiting on a lagging consumer.
        message_id = self._send(180, "jane@example.com", [("sent", 1, "")], keyed=True, status_consumer_behind=True)

        response = self.client.get(self._url(f"{message_id}/"))

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()

    def test_a_status_delivered_twice_shows_once(self, _flag):
        message_id = self._send(
            10, "jane@example.com", [("sent", 1, ""), ("clicked", 2, ""), ("clicked", 2, ""), ("clicked", 3, "")]
        )

        body = self.client.get(self._url(f"{message_id}/")).json()

        assert [event["kind"] for event in body["timeline"]] == ["queued", "sent", "clicked", "clicked"]

    def test_a_queued_row_delivered_twice_takes_one_place_on_a_page(self, _flag):
        self._send(20, "older@example.com", [("queued", 0, "")])
        self._send(10, "newer@example.com", [("queued", 0, "")])

        first_page = self.client.get(self._url(), {"limit": 1}).json()
        second_page = self.client.get(self._url(), {"limit": 1, "offset": 1}).json()

        assert [r["recipient"] for r in first_page["results"]] == ["newer@example.com"]
        assert first_page["has_more"] is True
        assert [r["recipient"] for r in second_page["results"]] == ["older@example.com"]
        assert second_page["has_more"] is False

    @parameterized.expand(
        [
            ("list", "", ["hog_flow:read"], "person:read"),
            ("retrieve", "{message_id}/", ["hog_flow:read"], "person:read"),
            ("activity", "{message_id}/activity/", ["hog_flow:read", "person:read"], "query:read"),
            ("stats_over_time", "stats_over_time/", ["query:read"], "hog_flow:read"),
            (
                "results",
                "results/?event=purchase&workflow_id={workflow_id}",
                ["hog_flow:read", "person:read"],
                "query:read",
            ),
            ("impact", "impact/?workflow_id={workflow_id}", ["hog_flow:read", "person:read"], "query:read"),
        ]
    )
    def test_a_token_needs_the_scope_for_the_data_it_reads(self, _flag, _name, path, scopes, missing_scope):
        message_id = self._send(10, "jane@example.com", [("sent", 1, "")])
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="scoped", user=self.user, secure_value=hash_key_value(key), scopes=scopes)

        response = self.client.get(
            self._url(path.format(message_id=message_id, workflow_id=self.workflow_id)),
            headers={"authorization": f"Bearer {key}"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert missing_scope in response.json()["detail"]

    @parameterized.expand([("another_projects_send", True), ("a_deleted_template", False)])
    def test_hides_what_the_project_cannot_see(self, _flag, _name, other_team):
        team = Team.objects.create(organization=self.organization) if other_team else None
        message_id = self._send(10, "jane@example.com", [("sent", 1, "")], team=team)
        self.template.deleted = True
        self.template.save()

        response = self.client.get(self._url(f"{message_id}/"))

        if other_team:
            assert response.status_code == status.HTTP_404_NOT_FOUND
        else:
            assert (response.json()["template_id"], response.json()["template_name"]) == (None, "")

    @parameterized.expand([("listed_ids", 100), ("too_many_ids_to_list", 1)])
    def test_shows_what_the_recipient_did_around_the_send(self, _flag, _name, max_distinct_ids):
        create_person(team=self.team, distinct_ids=["jane", "jane-anonymous"])
        create_person(team=self.team, distinct_ids=["someone-else"])
        message_id = self._send(3 * 24 * 60, "jane@example.com", [("sent", 1, ""), ("clicked", 300, "")])
        sent_at = NOW - timedelta(days=3) + timedelta(seconds=1)
        self._record_distinct_id(message_id, "jane", "jane@example.com", sent_at)
        for event, distinct_id, offset, session_id in [
            ("$pageview", "jane-anonymous", -timedelta(hours=2), "before"),
            ("$feature_flag_called", "jane", -timedelta(hours=1), "before"),
            ("$feature_flag_called", "jane", -timedelta(minutes=1), "ongoing"),
            ("$pageview", "jane", timedelta(minutes=2), "ongoing"),
            ("$pageview", "jane", timedelta(minutes=5), "after"),
            ("upgraded_plan", "jane", timedelta(minutes=6), "after"),
            ("invoice_paid", "jane", timedelta(minutes=10), None),
            ("$pageview", "someone-else", timedelta(minutes=7), "other"),
            ("$pageview", "jane", timedelta(days=8), "much-later"),
        ]:
            _create_event(
                team=self.team,
                event=event,
                distinct_id=distinct_id,
                timestamp=sent_at + offset,
                properties={"$session_id": session_id} if session_id else {},
            )
        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id="jane",
            timestamp=sent_at + timedelta(minutes=5, seconds=30),
            properties={"$session_id": "after", "$event_type": "click", "$pathname": "/billing"},
            elements=[Element(tag_name="button", text="Upgrade", nth_child=0, nth_of_type=0)],
        )
        flush_persons_and_events()

        with patch(
            "products.messaging.backend.services.transactional_email_activity.MAX_DISTINCT_IDS", max_distinct_ids
        ):
            response = self.client.get(self._url(f"{message_id}/activity/"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["distinct_id"] == "jane"
        assert datetime.fromisoformat(body["sent_at"]) == sent_at
        assert [(e["event"], e["session_id"]) for e in body["before"]] == [("$pageview", "before")]
        assert [(e["event"], e["session_id"]) for e in body["after"]] == [
            ("$pageview", "ongoing"),
            ("$pageview", "after"),
            ("$autocapture", "after"),
            ("upgraded_plan", "after"),
            ("invoice_paid", None),
        ]
        click = body["after"][2]
        assert (click["event_type"], click["pathname"]) == ("click", "/billing")
        assert 'text="Upgrade"' in click["elements_chain"]
        assert [(s["session_id"], s["event_count"], s["started_after_send"]) for s in body["sessions"]] == [
            ("before", 1, False),
            ("ongoing", 1, False),
            ("after", 3, True),
        ]

    def test_shows_the_activity_of_a_recipient_without_a_person_profile(self, _flag):
        message_id = self._send(3 * 24 * 60, "visitor@example.com", [("sent", 1, "")])
        sent_at = NOW - timedelta(days=3) + timedelta(seconds=1)
        self._record_distinct_id(message_id, "visitor", "visitor@example.com", sent_at)
        _create_event(
            team=self.team, event="$pageview", distinct_id="visitor", timestamp=sent_at + timedelta(minutes=5)
        )
        flush_persons_and_events()

        body = self.client.get(self._url(f"{message_id}/activity/")).json()

        assert [e["event"] for e in body["after"]] == ["$pageview"]

    def test_counts_sends_per_template_and_per_sending_domain(self, _flag):
        self._send(30, "a@example.com", [("sent", 1, ""), ("delivered", 2, ""), ("opened", 60, ""), ("opened", 90, "")])
        self._send(20, "b@example.com", [("sent", 1, ""), ("bounced", 2, "hard")], domain="other.example.com")
        self._send(10, "c@example.com", [("failed", 1, "provider_error")])

        by_template = self.client.get(self._url("stats/")).json()["results"]
        by_domain = self.client.get(self._url("stats/"), {"group_by": "sending_domain"}).json()["results"]

        assert [
            (r["key"], r["label"], r["sent"], r["delivered"], r["bounced"], r["opened"], r["failed"])
            for r in by_template
        ] == [(str(self.template.id), "Password reset", 2, 1, 1, 1, 1)]
        assert [(r["key"], r["sent"], r["bounced"]) for r in by_domain] == [
            ("mail.example.com", 1, 0),
            ("other.example.com", 1, 1),
        ]

    def test_counts_sends_over_time_in_the_project_timezone_with_the_period_before(self, _flag):
        self.team.timezone = "Europe/Prague"
        self.team.save()
        # 22:30 UTC on June 12 is already June 13 in Prague.
        self._send(60 * 61 + 30, "late@example.com", [("sent", 1, ""), ("delivered", 2, "")])
        self._send(60 * 26, "a@example.com", [("sent", 1, ""), ("bounced", 2, "hard")])
        self._send(60 * 26, "b@example.com", [("failed", 1, "provider_error")])
        self._send(60 * 24 * 5, "before@example.com", [("sent", 1, ""), ("delivered", 2, "")])

        body = self.client.get(
            self._url("stats_over_time/"), {"date_from": (NOW - timedelta(days=4)).isoformat()}
        ).json()

        assert body["interval"] == "day"
        assert body["timezone"] == "Europe/Prague"
        by_day = {
            bucket["start"]: (bucket["counts"]["sent"], bucket["counts"]["bounced"], bucket["counts"]["failed"])
            for bucket in body["buckets"]
        }
        assert by_day == {
            "2026-06-10T22:00:00Z": (0, 0, 0),
            "2026-06-11T22:00:00Z": (0, 0, 0),
            "2026-06-12T22:00:00Z": (1, 0, 0),
            "2026-06-13T22:00:00Z": (1, 1, 1),
            "2026-06-14T22:00:00Z": (0, 0, 0),
        }
        assert body["previous"]["sent"] == 1

    def test_compares_the_same_length_of_time_when_the_period_ends_now(self, _flag):
        self._send(61, "in@example.com", [("sent", 1, "")])
        self._send(64, "out@example.com", [("sent", 1, "")])

        body = self.client.get(
            self._url("stats_over_time/"), {"date_from": (NOW - timedelta(hours=1)).isoformat()}
        ).json()

        assert body["previous"]["sent"] == 2
        assert sum(bucket["counts"]["sent"] for bucket in body["buckets"]) == 0

    def test_has_no_earlier_period_when_retention_does_not_cover_it(self, _flag):
        body = self.client.get(
            self._url("stats_over_time/"), {"date_from": (NOW - timedelta(days=30)).isoformat()}
        ).json()

        assert body["previous"] is None

    def test_counts_who_converted_within_the_window_after_their_first_send(self, _flag):
        for distinct_id, sent_minutes_ago in [
            ("converted", 600),
            ("too-late", 600 * 24),
            ("never", 60),
            ("personless", 600),
        ]:
            if distinct_id != "personless":
                create_person(team=self.team, distinct_ids=[distinct_id])
            sync_execute(
                """
                INSERT INTO message_assets_data
                    (team_id, function_kind, function_id, parent_run_id, invocation_id, action_id, kind, distinct_id,
                     person_id, recipient, subject, status, sent_at, version, is_deleted, html)
                VALUES
                """,
                [
                    {
                        "team_id": self.team.id,
                        "function_kind": "hog_flow",
                        "function_id": self.workflow_id,
                        "parent_run_id": "",
                        "invocation_id": str(UUIDT()),
                        "action_id": "transactional_email",
                        "kind": "email",
                        "distinct_id": distinct_id,
                        "person_id": "",
                        "recipient": f"{distinct_id}@example.com",
                        "subject": "Reset",
                        "status": "sent",
                        "sent_at": NOW - timedelta(minutes=sent_minutes_ago),
                        "version": 1,
                        "is_deleted": 0,
                        "html": "",
                    }
                ],
            )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="converted",
            timestamp=NOW - timedelta(minutes=300),
            properties={"amount": 30},
        )
        for minutes_ago, amount in [(200, 5), (-900, 100)]:
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id="converted",
                timestamp=NOW - timedelta(minutes=minutes_ago),
                properties={"amount": amount},
            )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="personless",
            timestamp=NOW - timedelta(minutes=300),
            properties={"amount": 20, "$process_person_profile": False},
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="too-late",
            timestamp=NOW - timedelta(minutes=300),
            properties={"amount": 50},
        )
        flush_persons_and_events()

        response = self.client.get(
            self._url("results/"),
            {
                "workflow_id": str(self.workflow_id),
                "event": "purchase",
                "window_days": "1",
                "revenue_property": "amount",
                "date_from": (NOW - timedelta(days=29)).isoformat(),
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"recipients": 4, "converted": 2, "revenue": 55.0, "median_hours_to_convert": 5.0}

    def _seed_impact_sends(self) -> None:
        create_person(team=self.team, distinct_ids=["clicker", "clicker-phone"])
        for name in ["early", "slow", "sent-two-days-late", "reader", "late", "bounced"]:
            create_person(team=self.team, distinct_ids=[name])
        delivered = [("sent", 1, ""), ("delivered", 2, "")]
        clicked_an_hour_in = [*delivered, ("opened", 60, ""), ("clicked", 3600, "")]
        sends = [
            (3_000, "clicker", clicked_an_hour_in, timedelta(minutes=60 + 60 * 24)),
            (2_000, "early", clicked_an_hour_in, timedelta(minutes=10)),
            (
                SLOW_SEND_MINUTES_AGO,
                "slow",
                [*delivered, ("opened", 60, ""), ("clicked", 4 * 86400, "")],
                timedelta(days=9),
            ),
            (1_000, None, clicked_an_hour_in, None),
            (
                DELAYED_SEND_MINUTES_AGO,
                "sent-two-days-late",
                [("sent", 2 * 86400, ""), ("delivered", 2 * 86400 + 1, "")],
                timedelta(days=8),
            ),
            (4_000, "reader", [*delivered, ("opened", 60, "")], timedelta(days=1)),
            (5_000, "late", delivered, timedelta(days=7, hours=1)),
            (6_000, "bounced", [("sent", 1, ""), ("bounced", 2, "")], timedelta(hours=1)),
            (7_000, None, [("sent", 1, ""), ("clicked", 3600, "")], None),
        ]
        for minutes_ago, distinct_id, statuses, purchase_after_send in sends:
            message_id = self._send(minutes_ago, f"{distinct_id}@example.com", statuses)
            sent_at = NOW - timedelta(minutes=minutes_ago)
            if distinct_id:
                self._record_distinct_id(message_id, distinct_id, f"{distinct_id}@example.com", sent_at)
            if purchase_after_send:
                purchaser = "clicker-phone" if distinct_id == "clicker" else distinct_id
                _create_event(
                    team=self.team, event="purchase", distinct_id=purchaser, timestamp=sent_at + purchase_after_send
                )
        other_workflow = create_workflow_for_test(team_id=self.team.id, name="Welcome").id
        self._send(500, "clicker@example.com", clicked_an_hour_in, workflow_id=other_workflow)
        for workflow_id, metric_name, count in [
            (str(self.workflow_id), "email_untracked", 2),
            (str(self.workflow_id), "email_sent", 9),
            (str(other_workflow), "email_untracked", 5),
        ]:
            create_app_metric2(
                team_id=self.team.id,
                app_source="hog_flow",
                app_source_id=workflow_id,
                timestamp=NOW - timedelta(days=1),
                metric_kind="email",
                metric_name=metric_name,
                count=count,
            )
        flush_persons_and_events()

    def _impact(self, **params: str) -> dict:
        response = self.client.get(self._url("impact/"), {"workflow_id": self.workflow_id, **params})
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def test_impact_counts_how_far_this_workflows_sends_got(self, _flag):
        self._seed_impact_sends()

        assert self._impact(date_from=(NOW - timedelta(days=29)).isoformat()) == {
            **IMPACT_COUNTS,
            "after_click": None,
            "without_click": None,
        }

    def test_counts_conversions_within_a_week_of_the_click_against_sends_nobody_clicked(self, _flag):
        self._seed_impact_sends()

        assert self._impact(event="purchase", date_from=(NOW - timedelta(days=29)).isoformat()) == {
            **IMPACT_COUNTS,
            "after_click": {"sends": 3, "converted": 2},
            "without_click": {"sends": 3, "converted": 2},
        }

    def test_counts_conversions_of_sends_whose_ids_overflow_one_clickhouse_query(self, _flag):
        long_distinct_ids = [f"long-{index:02d}-{'€' * 380}" for index in range(LONG_ID_SENDS)]
        for minutes_ago, distinct_id in enumerate(long_distinct_ids, start=10):
            create_person(team=self.team, distinct_ids=[distinct_id])
            message_id = self._send(minutes_ago, f"{distinct_id}@example.com", [("sent", 1, ""), ("delivered", 2, "")])
            sent_at = NOW - timedelta(minutes=minutes_ago)
            self._record_distinct_id(message_id, distinct_id, f"{distinct_id}@example.com", sent_at)
            _create_event(
                team=self.team, event="purchase", distinct_id=distinct_id, timestamp=sent_at + timedelta(hours=1)
            )
        flush_persons_and_events()
        small_clickhouse_queries = {**default_settings(), "max_query_size": SMALL_MAX_QUERY_SIZE}

        with (
            patch("posthog.clickhouse.client.execute.default_settings", return_value=small_clickhouse_queries),
            patch(
                "products.messaging.backend.services.transactional_email_log._BATCH_QUERY_BYTES",
                SMALL_MAX_QUERY_SIZE // 4,
            ),
        ):
            impact = self._impact(event="purchase", date_from=(NOW - timedelta(days=1)).isoformat())

        assert impact["without_click"] == {"sends": LONG_ID_SENDS, "converted": LONG_ID_SENDS}

    def test_impact_follows_a_click_and_its_conversion_past_the_end_of_the_period(self, _flag):
        self._seed_impact_sends()
        slow_sent_at = NOW - timedelta(minutes=SLOW_SEND_MINUTES_AGO)

        assert self._impact(
            event="purchase",
            date_from=(slow_sent_at - timedelta(hours=1)).isoformat(),
            date_to=(slow_sent_at + timedelta(days=1)).isoformat(),
        ) == {
            "sent": 1,
            "delivered": 1,
            "opened": 1,
            "clicked": 1,
            "not_clicked": 0,
            "untracked": 0,
            "window_days": 7,
            "after_click": {"sends": 1, "converted": 1},
            "without_click": {"sends": 0, "converted": 0},
        }

    def test_hides_the_sends_of_a_workflow_the_user_cannot_view(self, _flag):
        restricted = create_workflow_for_test(team_id=self.team.id, name="Payroll").id
        visible_id = self._send(20, "jane@example.com", [("sent", 1, "")])
        hidden_id = self._send(10, "boss@example.com", [("sent", 1, "")], workflow_id=restricted)
        deleted_workflow = create_workflow_for_test(team_id=self.team.id, name="Old").id
        deleted_id = self._send(
            5, "old@example.com", [("sent", 1, "")], workflow_id=deleted_workflow, domain="old.example.com"
        )
        destroy_workflow(team_id=self.team.id, hog_flow_id=UUID(deleted_workflow))
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        create_access_control(
            team_id=self.team.id,
            resource="hog_flow",
            resource_id=restricted,
            access_level="none",
            organization_member_id=self.organization_membership.id,
        )

        denied_then_deleted = create_workflow_for_test(team_id=self.team.id, name="Secret").id
        denied_then_deleted_id = self._send(
            2, "secret@example.com", [("sent", 1, "")], workflow_id=denied_then_deleted, domain="secret.example.com"
        )
        create_access_control(
            team_id=self.team.id,
            resource="hog_flow",
            resource_id=denied_then_deleted,
            access_level="none",
            organization_member_id=self.organization_membership.id,
        )
        destroy_workflow(team_id=self.team.id, hog_flow_id=UUID(denied_then_deleted))

        listed = self.client.get(self._url()).json()["results"]
        detail = self.client.get(self._url(f"{hidden_id}/"))
        activity = self.client.get(self._url(f"{hidden_id}/activity/"))
        results = self.client.get(self._url("results/"), {"workflow_id": restricted, "event": "purchase"})
        impact = self.client.get(self._url("impact/"), {"workflow_id": restricted})

        stats = self.client.get(self._url("stats/"), {"group_by": "sending_domain"}).json()["results"]
        over_time = self.client.get(self._url("stats_over_time/")).json()["buckets"]

        assert [r["message_id"] for r in listed] == [deleted_id, visible_id]
        assert sum(bucket["counts"]["sent"] for bucket in over_time) == 2
        assert detail.status_code == status.HTTP_404_NOT_FOUND
        assert activity.status_code == status.HTTP_404_NOT_FOUND
        assert results.status_code == status.HTTP_404_NOT_FOUND
        assert impact.status_code == status.HTTP_404_NOT_FOUND
        assert {row["label"] for row in stats} == {"mail.example.com", "old.example.com"}
        assert self.client.get(self._url(f"{deleted_id}/")).json()["recipient"] == "old@example.com"
        assert self.client.get(self._url(f"{denied_then_deleted_id}/")).status_code == status.HTTP_404_NOT_FOUND

    def _deny_member(self, resource: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        create_access_control(
            team_id=self.team.id,
            resource=resource,
            access_level="none",
            organization_member_id=self.organization_membership.id,
        )

    @parameterized.expand([("person",), ("query",)])
    def test_activity_needs_access_to_persons_and_queries(self, _flag, resource):
        message_id = self._send(10, "jane@example.com", [("sent", 1, "")])
        self._deny_member(resource)

        assert self.client.get(self._url(f"{message_id}/activity/")).status_code == status.HTTP_403_FORBIDDEN

    def test_impact_answers_only_teams_with_the_impact_flag(self, flag):
        flag.side_effect = lambda key, *args, **kwargs: key != "workflows-email-impact"

        response = self.client.get(self._url("impact/"), {"workflow_id": self.workflow_id})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_impact_counts_conversions_only_with_query_access(self, _flag):
        self._deny_member("query")

        funnel = self.client.get(self._url("impact/"), {"workflow_id": self.workflow_id})
        conversions = self.client.get(self._url("impact/"), {"workflow_id": self.workflow_id, "event": "purchase"})

        assert funnel.status_code == status.HTTP_200_OK, funnel.json()
        assert conversions.status_code == status.HTTP_403_FORBIDDEN, conversions.json()

    def test_names_a_send_from_code_by_its_template_key_and_links_its_code_email(self, _flag):
        workflow_id = str(create_code_email_workflow(team_id=self.team.id, key="order-shipped"))
        code_email = TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).create(
            team_id=self.team.id, key="order-shipped", hog_flow_id=workflow_id
        )
        taken_workflow_id = str(create_code_email_workflow(team_id=self.team.id, key="welcome"))
        TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).create(
            team_id=self.team.id, key="welcome", hog_flow_id=taken_workflow_id
        )
        MessageTemplate.objects.create(team=self.team, name="Welcome", key="welcome")
        message_id = self._send(5, "jane@example.com", [("sent", 1, "")], workflow_id=workflow_id)
        self._send(10, "john@example.com", [("sent", 1, "")])
        self._send(15, "joe@example.com", [("sent", 1, "")], workflow_id=taken_workflow_id)

        listed = self.client.get(self._url()).json()["results"]
        detail = self.client.get(self._url(f"{message_id}/")).json()
        stats = self.client.get(self._url("stats/"), {"group_by": "template"}).json()["results"]

        assert [(r["template_name"], r["code_email_id"]) for r in listed] == [
            ("order-shipped", str(code_email.id)),
            ("Password reset", None),
            ("welcome", None),
        ]
        assert (detail["code_email_id"], detail["sensitive"]) == (str(code_email.id), False)
        assert sorted((r["label"], r["template_id"], r["code_email_id"]) for r in stats) == [
            ("Password reset", str(self.template.id), None),
            ("order-shipped", None, str(code_email.id)),
            ("welcome", None, None),
        ]

    def test_no_access_to_workflows_also_hides_the_sends_of_deleted_ones(self, _flag):
        deleted_workflow = create_workflow_for_test(team_id=self.team.id, name="Old").id
        deleted_id = self._send(5, "old@example.com", [("sent", 1, "")], workflow_id=deleted_workflow)
        destroy_workflow(team_id=self.team.id, hog_flow_id=UUID(deleted_workflow))
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        create_access_control(
            team_id=self.team.id,
            resource="hog_flow",
            access_level="none",
            organization_member_id=self.organization_membership.id,
        )
        assert self.client.get(self._url()).status_code == status.HTTP_403_FORBIDDEN

        granted_id = self._send(10, "jane@example.com", [("sent", 1, "")])
        create_access_control(
            team_id=self.team.id,
            resource="hog_flow",
            resource_id=str(self.workflow_id),
            access_level="viewer",
            organization_member_id=self.organization_membership.id,
        )

        listed = self.client.get(self._url())
        assert listed.status_code == status.HTTP_200_OK, listed.json()
        assert [r["message_id"] for r in listed.json()["results"]] == [granted_id]
        assert self.client.get(self._url(f"{deleted_id}/")).status_code == status.HTTP_404_NOT_FOUND


class TestStatsBuckets(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "keeps_the_repeated_hour_when_clocks_go_back",
                datetime(2026, 10, 25, 0, 10, tzinfo=UTC),
                datetime(2026, 10, 25, 2, 0, tzinfo=UTC),
                EmailStatsInterval.HOUR,
                [(10, 25, 0), (10, 25, 1)],
            ),
            (
                "starts_each_day_on_local_midnight_across_a_clock_change",
                datetime(2026, 10, 24, 12, 0, tzinfo=UTC),
                datetime(2026, 10, 26, 12, 0, tzinfo=UTC),
                EmailStatsInterval.DAY,
                [(10, 23, 22), (10, 24, 22), (10, 25, 23)],
            ),
        ]
    )
    def test_bucket_starts(self, _name, start, end, interval, expected):
        starts = _bucket_starts(start, end, interval, ZoneInfo("Europe/Prague"))

        assert [(moment.month, moment.day, moment.hour) for moment in starts] == expected
