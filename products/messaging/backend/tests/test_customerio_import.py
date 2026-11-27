import csv
import json
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.integration import Integration

from products.cohorts.backend.models.cohort import Cohort
from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
)
from products.messaging.backend.models.message_suppression import MessageSuppression
from products.messaging.backend.models.provider_import_run import ProviderImportRun
from products.messaging.backend.provider_imports import runs
from products.messaging.backend.provider_imports.base import (
    ImportCredentialsInvalid,
    ImportProviderUnavailable,
    ImportStepError,
    ImportTooLarge,
)
from products.messaging.backend.services import customerio_exports
from products.messaging.backend.tests.customerio_fake_server import KEY, NO_EXPORT_KEY, FakeCustomerIO, person
from products.messaging.backend.tests.people_import_recorder import PeopleImportRecorder

CONTACT_RUN = ["categories", "suppressions", "opt_outs", "contacts", "new_people"]
EXPORTS = "products.messaging.backend.services.customerio_exports"
PLACE = "EU workspace 1001"


class _CustomerIOTestCase(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        fake = FakeCustomerIO()
        self.customerio = self.enterContext(fake)
        self.workspace = fake.workspace
        for target, value in (
            ("products.messaging.backend.services.customerio_client.CustomerIOClient.EU_BASE_URL", fake.url),
            # The US host sends a key of the EU region there.
            ("products.messaging.backend.services.customerio_client.CustomerIOClient.US_BASE_URL", f"{fake.url}/us"),
            (f"{EXPORTS}.POLL_FIRST_DELAY_SECONDS", 0),
        ):
            self.enterContext(patch(target, value))
        self.enterContext(patch(f"{EXPORTS}.time.sleep"))
        self.enterContext(patch("products.messaging.backend.provider_imports.runs.start_provider_import_workflow"))

    def _start(self, steps: list[str] | None = None, key: str = KEY) -> ProviderImportRun:
        Integration.objects.filter(team_id=self.team.id, kind="customerio-app").delete()
        return runs.start_run(self.team.id, "customerio", steps or CONTACT_RUN, key, self.user.id)

    def _preferences(self) -> dict[str, dict[str, str]]:
        rows = MessageRecipientPreference.objects.filter(team_id=self.team.id)
        return {row.identifier: row.preferences for row in rows}


class TestCustomerIOGlobalUnsubscribes(_CustomerIOTestCase):
    def test_everyone_customerio_counts_as_unsubscribed_is_opted_out(self) -> None:
        values: tuple[Any, ...] = (True, "TRUE", 1, "1", False)
        self.workspace.people = [person(n, unsubscribed=value) for n, value in enumerate(values)]
        run = self._start(["opt_outs"])

        runs.run_step(self.team.id, run.id, "opt_outs", attempt=1)

        assert set(self._preferences()) == {f"person-{n}@example.com" for n in range(4)}


class TestCustomerIOSkipReasons(_CustomerIOTestCase):
    def test_opt_outs_it_skips_are_counted_by_reason(self) -> None:
        MessageRecipientPreference.objects.create(
            team_id=self.team.id,
            identifier="person-1@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"},
        )
        self.workspace.people = [
            person(0, unsubscribed=True),
            person(1, unsubscribed=True),
            person(2, email=None, unsubscribed=True),
            person(3, email="person-0@example.com", unsubscribed=True),
        ]
        run = self._start(["opt_outs"])

        runs.run_step(self.team.id, run.id, "opt_outs", attempt=1)

        run.refresh_from_db()
        assert run.progress["opt_outs"]["imported"] == 1
        assert run.progress["opt_outs"]["counts"] == {"no_email": 1, "duplicate_email": 1, "already_opted_out": 1}

    def test_suppressions_it_skips_are_counted_by_reason(self) -> None:
        MessageSuppression.objects.for_team(self.team.id).create(
            team_id=self.team.id, identifier="kept@example.com", source="MANUAL", suppressed=True
        )
        self.workspace.suppressions = {
            "bounces": [
                {"email": "new@example.com"},
                {"email": "kept@example.com"},
                {"email": "NEW@example.com"},
                {"email": "not-an-address"},
            ]
        }
        run = self._start(["suppressions"])

        runs.run_step(self.team.id, run.id, "suppressions", attempt=1)

        run.refresh_from_db()
        assert run.progress["suppressions"]["imported"] == 1
        assert run.progress["suppressions"]["counts"] == {"no_address_or_repeat": 2, "already_suppressed": 1}


class TestCustomerIOContacts(ClickhouseTestMixin, _CustomerIOTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.people = PeopleImportRecorder(self)

    def _run_contacts(self) -> ProviderImportRun:
        run = self._start()
        with self.captureOnCommitCallbacks(execute=True):
            for step in run.steps:
                runs.run_step(self.team.id, run.id, step, attempt=1)
        run.refresh_from_db()
        return run

    def _lists(self, run: ProviderImportRun) -> dict[str, dict[str, bool]]:
        """By cohort name, each stored person's distinct ID and whether they join the cohort."""
        return {
            Cohort.objects.get(id=plan["cohort_id"]).name or "": {
                stored["distinct_id"]: stored.get("member", True) for stored in self.people.people(plan)
            }
            for plan in run.progress["contacts"]["people_imports"]
        }

    def _properties(self, run: ProviderImportRun) -> dict[str, dict[str, str]]:
        [plan, *_] = run.progress["contacts"]["people_imports"]
        return {stored["distinct_id"]: stored["properties"] for stored in self.people.people(plan)}

    def test_people_match_by_email_and_only_fill_in_what_they_lack(self) -> None:
        _create_person(team=self.team, distinct_ids=["app-id"], properties={"email": "Ada@Example.com"})
        # Customer.io's ID for someone else, so matching on it would write to the wrong person.
        _create_person(team=self.team, distinct_ids=["user-2"], properties={"email": "other@example.com"})
        flush_persons_and_events()
        self.workspace.people = [
            person(
                1, "ada@example.com", plan="pro", **{"$browser": "x", "distinct_id": "admin", "Distinct Id": "admin"}
            ),
            person(2, "Zoë@example.com", note="no"),
            person(
                3, "new@example.com", first_name="Žofie 😀", note='a,"b"\r\nc', nested={"a": [1]}, created_at=1700000000
            ),
            person(4, None, plan="free"),
            {"cio_id": "c5", "email": "noid@example.com"},
            person(6, "NEW@example.com", plan="late"),
            person(7, "not-an-email"),
            person(8, "wide@example.com", **{f"wide_{n}": "x" * 1000 for n in range(9)}),
        ]

        run = self._run_contacts()

        assert run.progress["contacts"]["status"] == "completed"
        assert self._lists(run) == {
            f"Customer.io people ({PLACE})": {
                "app-id": True,
                "new@example.com": True,
                "noid@example.com": True,
                "wide@example.com": True,
            }
        }
        properties = self._properties(run)
        assert properties["app-id"] == {"email": "ada@example.com", "plan": "pro", "customerio_id": "user-1"}
        assert properties["new@example.com"] == {
            "email": "new@example.com",
            "first_name": "Žofie 😀",
            "note": 'a,"b"\r\nc',
            "nested": '{"a":[1]}',
            "created_at": "1700000000",
            "plan": "late",
            "customerio_id": "user-3",
        }
        assert properties["noid@example.com"] == {"email": "noid@example.com"}
        counts = run.progress["contacts"]["counts"]
        assert counts["no_email"] == 1 and counts["repeats_merged"] == 1
        assert counts["invalid_skipped"] + counts["dropped"] + counts["unsendable"] == 2

    def test_whoever_left_is_opted_out_and_joins_no_cohort(self) -> None:
        self.workspace.topics = [
            {"id": 1, "identifier": "news", "name": "News", "subscribed_by_default": True},
            {"id": 2, "identifier": "topic_2", "name": "Offers", "subscribed_by_default": False},
            # An identifier that reads like another topic's key doesn't take that topic's choices.
            {"id": 3, "identifier": "topic_1", "name": "Odd", "subscribed_by_default": True},
        ]

        def choices(**preferences: Any) -> dict[str, str]:
            return {"cio_subscription_preferences": json.dumps(preferences)}

        self.workspace.people = [
            person(1, "stays@example.com", unsubscribed="false", **choices(topics={"topic_1": True})),
            person(2, "Topic@Example.com", **choices(topics={"topic_1": False, "topic_2": True, "topic_9": False})),
            person(3, "channel@example.com", **choices(channels={"email": False, "sms": True})),
            person(4, "one@example.com", unsubscribed=1),
            person(5, "unreadable@example.com", cio_subscription_preferences="{topics"),
            person(8, "malformed@example.com", **choices(topics=["topic_1"])),
            person(9, "bare@example.com", **choices(topics={"1": "0"})),
            # Two people share an address, and one of them left.
            person(6, "shared@example.com"),
            person(7, "SHARED@example.com", unsubscribed=True),
        ]

        run = self._run_contacts()

        [members] = self._lists(run).values()
        assert {who for who, member in members.items() if member} == {
            "stays@example.com",
            "Topic@Example.com",
            "bare@example.com",
        }
        everything = {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"}
        news = str(MessageCategory.objects.get(team_id=self.team.id, key="customerio_news").id)
        preferences = self._preferences()
        assert preferences["Topic@Example.com"] == {news: "OPTED_OUT"} == preferences["bare@example.com"]
        for left in ("channel@example.com", "one@example.com", "unreadable@example.com", "malformed@example.com"):
            assert preferences[left] == everything
        assert preferences["shared@example.com"] == everything
        assert "stays@example.com" not in preferences
        assert "can't read: 2." in run.progress["contacts"]["warnings"][0]

    def test_importing_again_takes_out_who_unsubscribed_or_was_deleted(self) -> None:
        self.workspace.people = [person(1), person(2), person(3)]
        first = self._run_contacts()
        runs.finish_run(self.team.id, first.id)
        run = self._start()
        with self.captureOnCommitCallbacks(execute=True):
            for step in CONTACT_RUN[:3]:
                runs.run_step(self.team.id, run.id, step, attempt=1)
            # Unsubscribes after the opt-out step read who left.
            self.workspace.people = [person(1), person(2, unsubscribed=True)]
            for step in CONTACT_RUN[3:]:
                runs.run_step(self.team.id, run.id, step, attempt=1)
        run.refresh_from_db()

        [plan] = run.progress["contacts"]["people_imports"]
        assert plan["cohort_id"] == first.progress["contacts"]["people_imports"][0]["cohort_id"]
        assert list(self._lists(run).values()) == [{"person-1@example.com": True, "person-2@example.com": False}]
        assert ALL_MESSAGE_PREFERENCE_CATEGORY_ID in self._preferences()["person-2@example.com"]

    def test_another_workspace_keeps_the_first_ones_cohort(self) -> None:
        self.workspace.people = [person(1)]
        first = self._run_contacts()
        assert set(self._lists(first)) == {"Customer.io people (EU workspace 1001)"}
        runs.finish_run(self.team.id, first.id)
        self.workspace.id = 1002
        self.workspace.people = [person(2)]

        second = self._run_contacts()

        assert set(self._lists(second)) == {"Customer.io people (EU workspace 1002)"}

    def test_segments_fill_a_cohort_each_next_to_any_realtime_cohort(self) -> None:
        self.workspace.people = [person(1), person(2, unsubscribed=True), person(3, None), person(4)]
        self.workspace.segments = [
            {"id": 1, "name": "All Users", "type": "dynamic", "state": "finished"},
            {"id": 2, "name": "VIP 🚀", "type": "manual", "state": "finished"},
            {"id": 3, "name": "Empty", "type": "manual", "state": "finished"},
            {"id": 4, "name": "Building", "type": "dynamic", "state": "build"},
            {"id": 5, "name": "Rules", "type": "dynamic", "state": "finished"},
            {"id": "²", "name": "Not a number", "type": "manual", "state": "finished"},
            {"id": "9" * 5000, "name": "Too long", "type": "manual", "state": "finished"},
        ]
        everyone = {each["cio_id"] for each in self.workspace.people}
        self.workspace.members = {
            "1": everyone,
            "2": {"c0000001", "c0000002", "c0000003"},
            "4": everyone,
            "5": everyone,
        }
        Cohort.objects.create(
            team=self.team,
            name="Rules",
            description="Imported from Customer.io segment 5. Made by the workflow import from the segment's rules.",
            cohort_type="realtime",
            realtime_enabled_at=timezone.now(),
        )
        everyone_list = f"Customer.io people ({PLACE})"

        first = self._run_contacts()

        assert self._lists(first) == {
            everyone_list: {
                "person-1@example.com": True,
                "person-2@example.com": False,
                "person-4@example.com": True,
            },
            "VIP 🚀 (from Customer.io)": {"person-1@example.com": True, "person-2@example.com": False},
            "All Users (from Customer.io)": {
                "person-1@example.com": True,
                "person-2@example.com": False,
                "person-4@example.com": True,
            },
            # The automation import's realtime cohort stays, and the static copy sits next to it.
            "Rules (from Customer.io)": {
                "person-1@example.com": True,
                "person-2@example.com": False,
                "person-4@example.com": True,
            },
        }
        warnings = " ".join(first.progress["contacts"]["warnings"])
        assert '"Building" wasn\'t imported' in warnings and '"Rules"' not in warnings
        assert [plan["send_events"] for plan in first.progress["contacts"]["people_imports"]] == [
            True,
            False,
            False,
            False,
        ]
        assert Cohort.objects.filter(team=self.team, name="Rules", cohort_type="realtime").exists()

        runs.finish_run(self.team.id, first.id)
        # A renamed segment keeps its cohort, and one that lost everyone empties it.
        self.workspace.segments[1]["name"] = "Renamed"
        self.workspace.members["2"] = set()
        second = self._run_contacts()

        cohorts = [
            [plan["cohort_id"] for plan in run.progress["contacts"]["people_imports"]] for run in (first, second)
        ]
        assert cohorts[0] == cohorts[1]
        assert self._lists(second)["VIP 🚀 (from Customer.io)"] == {}

    @patch("products.messaging.backend.provider_imports.customerio.MAX_SEGMENT_MEMBERSHIPS", 2)
    def test_segments_past_the_limit_are_left_out_after_the_manual_ones(self) -> None:
        self.workspace.people = [person(1), person(2)]
        self.workspace.segments = [
            {"id": 1, "name": "All Users", "type": "dynamic", "state": "finished"},
            {"id": 2, "name": "VIP", "type": "manual", "state": "finished"},
        ]
        self.workspace.members = {"1": {"c0000001", "c0000002"}, "2": {"c0000001"}}

        run = self._run_contacts()

        assert set(self._lists(run)) == {f"Customer.io people ({PLACE})", "VIP (from Customer.io)"}
        assert "All Users" in run.progress["contacts"]["warnings"][0]

    @parameterized.expand(
        [
            ("cut_short", {"cut_file_to": 150}),
            ("without_a_size_or_checksum", {"state_length": False}),
            ("cut_at_the_end_of_a_row", {"cut_file_to": 170}),
            ("fewer_than_stated", {"stated_total": 5}),
            ("more_than_stated", {"stated_total": 1}),
            (
                "link_to_a_private_address",
                {"download_url": "https://127.0.0.1:1/customers.csv"},
                customerio_exports.UNFOLLOWED_LINK_MESSAGE,
            ),
            (
                "link_without_https",
                {"download_url": "http://example.com/customers.csv"},
                customerio_exports.UNFOLLOWED_LINK_MESSAGE,
            ),
            (
                "cloud_metadata",
                {"download_url": "https://169.254.169.254/1001/1.csv"},
                customerio_exports.UNFOLLOWED_LINK_MESSAGE,
            ),
        ]
    )
    def test_a_file_that_is_not_complete_changes_nothing(
        self, _name: str, changes: dict[str, Any], message: str = ""
    ) -> None:
        self.workspace.people = [person(n, plan="pro") for n in range(3)]
        for attribute, value in changes.items():
            setattr(self.customerio, attribute, value)
        run = self._start()
        for step in CONTACT_RUN[:3]:
            runs.run_step(self.team.id, run.id, step, attempt=1)

        with self.assertRaises(ImportStepError):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        run.refresh_from_db()
        assert not Cohort.objects.filter(team=self.team).exists()
        assert "people_imports" not in run.progress["contacts"]
        # The link grants access to everyone's data, so no message repeats it.
        assert message in run.progress["contacts"]["last_error"]
        assert "http" not in run.progress["contacts"]["last_error"].lower().replace("http 4", "")

    def test_the_key_never_goes_to_the_download_or_after_a_redirect(self) -> None:
        self.workspace.people = [person(1)]
        self.customerio.failures = [(r"GET /files/.*", 302, {"Location": f"{self.customerio.url}/workspaces"})] * 3

        with self.assertRaises(ImportProviderUnavailable):
            self._run_contacts()

        downloads = [auth for _, path, auth in self.customerio.requests if "/files/" in path]
        assert downloads == ["", "", ""]
        # The last request is a download, because no redirect was followed.
        assert "/files/" in self.customerio.requests[-1][1]

    def test_a_retry_reads_the_export_the_first_try_started(self) -> None:
        self.workspace.people = [person(1)]
        self.customerio.pending_checks = 2
        run = self._start()
        for step in CONTACT_RUN[:3]:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        with patch.object(customerio_exports, "MAX_POLL_SECONDS", -1), self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        runs.run_step(self.team.id, run.id, "contacts", attempt=2)

        run.refresh_from_db()
        assert run.progress["contacts"]["status"] == "completed"
        assert len(self.customerio.exports) == 1

    @parameterized.expand(
        [
            ("deleted", lambda fake: fake.failures.append((r"GET /exports/1", 404, {}))),
            ("failed", lambda fake: fake.exports[0].update(status="failed", checks_left=1)),
        ]
    )
    def test_a_retry_starts_over_when_the_export_is_gone(self, _name: str, lose: Any) -> None:
        self.workspace.people = [person(1)]
        self.customerio.pending_checks = 1
        run = self._start()
        for step in CONTACT_RUN[:3]:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        with patch.object(customerio_exports, "MAX_POLL_SECONDS", -1), self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)
        lose(self.customerio)
        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "contacts", attempt=2)

        runs.run_step(self.team.id, run.id, "contacts", attempt=3)

        assert len(self.customerio.exports) == 2

    def test_a_failed_download_keeps_the_export_for_the_retry(self) -> None:
        self.workspace.people = [person(1)]
        self.customerio.failures = [(r"GET /files/.*", 503, {})] * customerio_exports.DOWNLOAD_ATTEMPTS
        run = self._start()
        for step in CONTACT_RUN[:3]:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        runs.run_step(self.team.id, run.id, "contacts", attempt=2)

        run.refresh_from_db()
        assert run.progress["contacts"]["status"] == "completed"
        assert len(self.customerio.exports) == 1

    def test_a_file_larger_than_one_import_takes_is_not_retried(self) -> None:
        self.workspace.people = [person(1)]

        with patch.object(customerio_exports, "MAX_DOWNLOAD_BYTES", 10), self.assertRaises(ImportTooLarge):
            self._run_contacts()

    @parameterized.expand(
        [
            ("a_value_past_the_csv_field_limit", "csv_limit", "larger than PostHog reads"),
            ("a_row_too_wide_to_hold", "line_limit", "more data than PostHog reads"),
        ]
    )
    def test_a_person_too_large_to_read_is_not_retried(self, _name: str, limit: str, message: str) -> None:
        self.workspace.people = [person(1, note="x" * 200)]
        if limit == "csv_limit":
            self.addCleanup(csv.field_size_limit, csv.field_size_limit(100))
        else:
            self.enterContext(patch.object(customerio_exports, "MAX_LINE_CHARS", 150))

        with self.assertRaisesRegex(ImportTooLarge, message):
            self._run_contacts()

    def test_a_key_that_cannot_export_stops_before_any_run(self) -> None:
        with self.assertRaisesRegex(ImportCredentialsInvalid, "export people"):
            self._start(key=NO_EXPORT_KEY)

        assert not ProviderImportRun.objects.for_team(self.team.id).exists()

    def test_an_account_with_no_one_imports_nothing(self) -> None:
        run = self._run_contacts()

        assert run.progress["contacts"]["status"] == "completed"
        assert not Cohort.objects.filter(team=self.team).exists()
