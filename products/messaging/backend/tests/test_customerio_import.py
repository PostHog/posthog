import csv
import json
from typing import Any

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration

from products.access_control.backend.facade.testing import set_member_property_access
from products.cohorts.backend.models.cohort import Cohort
from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
)
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.provider_import_run import ProviderImportRun
from products.messaging.backend.provider_imports import runs
from products.messaging.backend.provider_imports.base import (
    ImportCredentialsInvalid,
    ImportProviderUnavailable,
    ImportStepBlocked,
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


PROVIDER_FLAGS_PATH = "products.messaging.backend.facade.provider_imports.feature_enabled_or_false"
TRANSACTIONAL_MESSAGES = [
    {"id": 1, "name": "All uncategorized email messages", "send_to_unsubscribed": True},
    {"id": 7, "name": "Password reset", "send_to_unsubscribed": True, "hide_message_body": True},
    {"id": 8, "name": "Subject only", "send_to_unsubscribed": True},
]
TRANSACTIONAL_CONTENTS: dict[str, list[dict[str, Any]]] = {
    "1": [{"id": 1, "language": "", "subject": "", "body": "", "headers": "[]"}],
    "7": [
        {
            "id": 70,
            "language": "",
            "subject": "Reset your password, {{customer.first_name | default: 'there'}}",
            "preheader_text": "For {{customer['last_name']}}",
            "body": "<html><body>{% for step in trigger.steps %}<p>{{step}}</p>{% endfor %}"
            '<a href="{{trigger.reset_url}}">Reset</a></body></html>',
            "body_plain": "Reset here: {{trigger.reset_url}}",
            "headers": "[]",
        },
        {
            "id": 71,
            "language": "fr",
            "subject": "Réinitialisez votre mot de passe",
            "body": '<html><body><a href="{{trigger.reset_url}}">Réinitialiser</a></body></html>',
            "headers": "[]",
        },
    ],
    "8": [{"id": 80, "language": "", "subject": "No body yet", "body": "", "headers": "[]"}],
}


def _customerio_answer(method: str, url: str, **_: Any) -> MagicMock:
    response = MagicMock(status_code=200)
    path = url.split("/v1", 1)[1]
    if path == "/transactional":
        body: dict[str, Any] = {"messages": TRANSACTIONAL_MESSAGES}
    elif path.startswith("/transactional/"):
        body = {"contents": TRANSACTIONAL_CONTENTS[path.split("/")[2]]}
    elif path == "/sender_identities":
        body = {"sender_identities": [], "next": ""}
    else:
        body = {"topics": [], "snippets": []}
    response.json.return_value = body
    return response


class TestCustomerIOTransactionalMessages(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("products.messaging.backend.provider_imports.runs.start_provider_import_workflow"))
        self.enterContext(
            patch(
                "products.messaging.backend.services.customerio_client.requests.Session.request",
                side_effect=_customerio_answer,
            )
        )

    def _import(self, api_key: str | None = "app-key") -> dict[str, Any]:
        run = runs.start_run(self.team.id, "customerio", ["transactional"], api_key, self.user.id)
        try:
            runs.run_step(self.team.id, run.id, "transactional", attempt=1)
        except ImportStepBlocked:
            pass
        runs.finish_run(self.team.id, run.id)
        run.refresh_from_db()
        return run.progress["transactional"]

    def _verified_sender(self) -> Integration:
        return Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )

    def test_each_language_becomes_a_transactional_template_and_a_second_import_keeps_edits(self) -> None:
        sender = self._verified_sender()

        progress = self._import()

        templates = {t.key: t for t in MessageTemplate.objects.filter(team_id=self.team.id)}
        assert set(templates) == {"customerio-transactional-7", "customerio-transactional-7-fr"}
        reset = templates["customerio-transactional-7"]
        email = reset.content["email"]
        assert reset.transactional_hog_flow_id is not None
        assert templates["customerio-transactional-7-fr"].transactional_hog_flow_id is not None
        assert reset.sensitive is True
        assert email["from"]["integrationId"] == sender.id
        assert email["subject"] == "Reset your password, {{variables.customer.first_name | default: 'there'}}"
        assert "{% for step in variables.steps %}" in email["html"]
        assert email["text"] == "Reset here: {{variables.reset_url}}"
        assert progress["counts"] == {"needs_review": 1, "created": 1, "empty": 1, "failed": 1}
        notes = " ".join(note for item in progress["items"] for note in item["notes"])
        assert "customerio-transactional-7-fr" in notes
        assert "reads steps and reset_url" in notes and '"customer": {"first_name": ..., "last_name": ...}' in notes

        MessageTemplate.objects.filter(id=reset.id).update(name="Edited by the team")
        progress = self._import(api_key=None)

        assert MessageTemplate.objects.filter(team_id=self.team.id).count() == 2
        assert MessageTemplate.objects.get(id=reset.id).name == "Edited by the team"
        assert progress["counts"] == {"already_present": 2, "empty": 1, "failed": 1}

    def test_no_verified_sender_fails_the_step_and_creates_nothing(self) -> None:
        progress = self._import()

        assert progress["status"] == "failed"
        assert not MessageTemplate.objects.filter(team_id=self.team.id).exists()

    @patch(PROVIDER_FLAGS_PATH, return_value=True)
    def test_restricted_property_access_refuses_the_step(self, _flags: MagicMock) -> None:
        self._verified_sender()
        set_member_property_access(team=self.team, membership=self.organization_membership, access="restricted")

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_provider_imports/",
            {"provider": "customerio", "steps": ["transactional"], "api_key": "app-key"},
        )

        assert response.status_code == 403
        assert not MessageTemplate.objects.filter(team_id=self.team.id).exists()

    @patch(PROVIDER_FLAGS_PATH, return_value=False)
    def test_transactional_email_off_hides_the_step_and_refuses_it(self, _flags: MagicMock) -> None:
        self._verified_sender()
        url = f"/api/projects/{self.team.id}/messaging_provider_imports/"

        providers = self.client.get(f"{url}providers/").json()
        response = self.client.post(url, {"provider": "customerio", "steps": ["transactional"], "api_key": "app-key"})

        customerio = next(provider for provider in providers if provider["key"] == "customerio")
        assert "transactional" not in [step["key"] for step in customerio["steps"]]
        assert "Transactional messages stay in Customer.io" in customerio["not_imported"]
        assert not any("transactional send" in step for step in customerio["next_steps"])
        assert response.status_code == 400
        assert not MessageTemplate.objects.filter(team_id=self.team.id).exists()
