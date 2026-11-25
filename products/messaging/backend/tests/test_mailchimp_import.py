import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.cohorts.backend.models.cohort import Cohort
from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.provider_import_run import ProviderImportRun
from products.messaging.backend.provider_imports import runs
from products.messaging.backend.provider_imports.base import (
    ImportCredentialsInvalid,
    ImportProviderUnavailable,
    ImportStepBlocked,
)
from products.messaging.backend.provider_imports.mailchimp import (
    ALL_DELETED_NOTE,
    DELETED_AUDIENCE_NOTE,
    NO_AUDIENCES_NOTE,
    NO_AUDIENCES_ROLE_MESSAGE,
    NO_AUDIENCES_UNCONFIRMED_MESSAGE,
    NOT_EMPTIED_NOTE,
    MailchimpImportProvider,
)
from products.messaging.backend.tests.fake_mailchimp import FULL_KEY, Failure, FakeMailchimp, split_url
from products.messaging.backend.tests.people_import_recorder import PeopleImportRecorder

CLIENT = "products.messaging.backend.services.mailchimp_client"
HOST = "https://us21.api.mailchimp.com"
NOVEDADES = "Novedades del producto ñ (from Mailchimp)"
OPT_OUT_STEPS = ["audiences", "groups", "cleaned", "complaints"]
# Every step that doesn't write people, so these runs need no ClickHouse.
ALL_STEPS = [spec.key for spec in MailchimpImportProvider.steps if spec.key != "new_people" and spec.key != "contacts"]


class TestMailchimpImportBase(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.mailchimp = FakeMailchimp()
        self.hosts: list[str] = []
        self.sleep = self._patch(f"{CLIENT}.time.sleep")
        self._patch("products.messaging.backend.provider_imports.runs.start_provider_import_workflow")
        self._patch(f"{CLIENT}.requests.get", self._get)
        self._patch(f"{CLIENT}.REQUESTS_PER_SECOND", 100000)

    def _patch(self, target: str, *replacement: Any) -> Any:
        patcher = patch(target, *replacement)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def _get(self, url: str, params: dict | None = None, headers: dict | None = None, **_: Any) -> MagicMock:
        base, path, query = split_url(url)
        self.hosts.append(base)
        query = {**query, **{key: str(value) for key, value in (params or {}).items()}}
        status, body, response_headers = self.mailchimp.handle(path, query, (headers or {}).get("Authorization", ""))
        response = MagicMock(status_code=status, ok=status < 400, headers=response_headers)
        response.json.return_value = body
        return response

    def _run(self, steps: list[str] | None = None, **settings: str) -> ProviderImportRun:
        run = runs.start_run(self.team.id, "mailchimp", steps or ALL_STEPS, FULL_KEY, self.user.id, settings)
        for step in run.steps:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        runs.finish_run(self.team.id, run.id)
        run.refresh_from_db()
        return run

    def _opt_outs(self) -> dict[str, set[str]]:
        names = {str(row.id): row.name for row in MessageCategory.objects.filter(team_id=self.team.id)}
        return {
            row.identifier: {names[category] for category, status in row.preferences.items() if status == "OPTED_OUT"}
            for row in MessageRecipientPreference.objects.filter(team_id=self.team.id)
        }


class TestMailchimpImport(TestMailchimpImportBase):
    def test_imports_every_step_from_the_key_data_center(self) -> None:
        run = self._run()

        assert run.status == "completed", run.progress
        assert set(self.hosts) == {HOST}
        assert sorted(MessageCategory.objects.filter(team_id=self.team.id).values_list("name", flat=True)) == [
            "Event invitations 🎉",
            "Novedades del producto ñ",
            "Product updates",
            "Weekly newsletter",
        ]
        weekly_groups = {"Product updates", "Event invitations 🎉"}
        assert self._opt_outs() == {
            "ada@example.com": {"Event invitations 🎉"},
            "Grace.Hopper@example.com": {"Product updates", "Event invitations 🎉"},
            "grace.hopper@example.com": {"Product updates", "Event invitations 🎉"},
            "Left.Person@example.com": {"Weekly newsletter", "Novedades del producto ñ", *weekly_groups},
            "left.person@example.com": {"Weekly newsletter", "Novedades del producto ñ", *weekly_groups},
            "jürgen.müller@example.com": {"Weekly newsletter", *weekly_groups},
            "pending@example.com": {"Weekly newsletter", *weekly_groups},
            "receipt-only@example.com": {"Weekly newsletter", *weekly_groups},
            "archived@example.com": {"Weekly newsletter", *weekly_groups},
        }
        assert sorted(MessageSuppression.objects.for_team(self.team.id).values_list("identifier", "source")) == [
            ("angry@example.com", SuppressionSource.COMPLAINT),
            ("bounced@example.com", SuppressionSource.BOUNCE),
        ]
        assert run.progress["audiences"]["counts"] == {
            "created": 2,
            "already_present": 0,
            "empty_audiences": 1,
            "opted_out": 6,
            "already_opted_out": 0,
            "unsubscribed": 3,
            "never_subscribed": 2,
            "archived": 1,
            "invalid": 0,
        }
        assert run.progress["groups"]["counts"]["hidden_groups"] == 1
        assert run.progress["cleaned"]["counts"] == {"bounced": 1, "already_present": 0, "invalid": 1}

        templates = {str(row.key): row for row in MessageTemplate.objects.filter(team_id=self.team.id)}
        assert sorted(templates) == [
            "mailchimp-campaign-camp001",
            "mailchimp-campaign-camp002",
            "mailchimp-campaign-camp005",
            "mailchimp-template-101",
            "mailchimp-template-103",
            "mailchimp-template-104",
        ]
        welcome = templates["mailchimp-template-101"].content["email"]["html"]
        assert "{{ person.properties.first_name | escape | raw }}" in welcome
        assert '{% if person.properties.COMPANY and person.properties.COMPANY != "" %}' in welcome
        assert "*|ARCHIVE|*" in welcome
        assert "*|LIST:COMPANY|*" in welcome
        assert "\\*|ARCHIVE|\\*" in templates["mailchimp-template-101"].description
        assert run.progress["templates"]["counts"] == {"needs_review": 2, "created": 1, "no_content": 1}
        assert templates["mailchimp-template-104"].content["email"]["html"] == (
            "<p>{% if false %}<span></span>{% endif %}Your login is {{ person.properties.email | escape | raw }}.</p>"
        )

        draft = templates["mailchimp-campaign-camp001"].content["email"]
        assert draft["subject"] == "{{ person.properties.first_name }}, here's what's new"
        assert "<title>*|MC:SUBJECT|*</title>" in draft["html"]
        assert "<!--{% if true %}--><span>Five things we shipped</span><!--{% endif %}-->" in draft["html"]
        assert "MC_PREVIEW_TEXT" not in templates["mailchimp-campaign-camp001"].description
        assert "You signed up on example.com." in draft["html"]
        plain = templates["mailchimp-campaign-camp002"].content["email"]["html"]
        assert "&lt;b&gt;no html here&lt;/b&gt;" in plain
        assert "{{ unsubscribe_url }}" in plain
        ab_test = templates["mailchimp-campaign-camp005"]
        assert ab_test.content["email"]["html"] == "<p>Short {{ person.properties.first_name | escape | raw }}</p>"
        assert ab_test.content["email"]["subject"] == "Short {{ person.properties.first_name }}"
        assert "tests 2 subject lines in Mailchimp. PostHog used the first one." in ab_test.description
        assert "A/B test with 2 variations. PostHog imported Short subject." in ab_test.description
        assert "no subject" not in ab_test.description

    def test_importing_again_adds_nothing(self) -> None:
        self._run()
        before = (
            MessageCategory.objects.count(),
            MessageTemplate.objects.count(),
            MessageSuppression.objects.for_team(self.team.id).count(),
        )

        run = self._run()

        assert (
            MessageCategory.objects.count(),
            MessageTemplate.objects.count(),
            MessageSuppression.objects.for_team(self.team.id).count(),
        ) == before
        assert run.progress["audiences"]["counts"]["opted_out"] == 0
        assert run.progress["templates"]["counts"] == {"already_present": 3, "no_content": 1}

    @parameterized.expand(
        [
            ("unsent", {"camp001", "camp002", "camp005"}, {"paused", "save", "schedule"}),
            ("recent", {"camp001", "camp002", "camp003", "camp005"}, {"paused", "save", "schedule", "sent"}),
            ("all", {"camp001", "camp002", "camp003", "camp004", "camp005"}, {None}),
        ]
    )
    def test_campaigns_setting_picks_which_campaigns_import(
        self, choice: str, expected: set[str], statuses_read: set[str | None]
    ) -> None:
        campaigns = {campaign["id"]: campaign for campaign in self.mailchimp.data["campaigns"]}
        campaigns["camp003"]["send_time"] = (datetime.now(UTC) - timedelta(days=21)).isoformat()
        campaigns["camp004"]["send_time"] = (datetime.now(UTC) - timedelta(days=200)).isoformat()

        self._run(["campaigns"], campaigns=choice)

        templates = {
            str(row.key).removeprefix("mailchimp-campaign-"): row
            for row in MessageTemplate.objects.filter(team_id=self.team.id)
        }
        assert set(templates) == expected
        assert {call["query"].get("status") for call in self.mailchimp.calls if call["route"] == "campaigns"} == (
            statuses_read
        )
        if "camp003" in templates:
            html = templates["camp003"].content["email"]["html"]
            assert html == (
                "<!--{% if true %}--><span>*|MC_PREVIEW_TEXT|*</span><!--{% endif %}-->{% if person.properties.first_name "
                'and person.properties.first_name != "" %}<p>October {{ person.properties.first_name | escape | raw }}</p>'
                "{% endif %}"
            )

    def test_a_failed_page_resumes_one_page_before_its_offset(self) -> None:
        self._patch(f"{CLIENT}.PAGE_SIZE", 1)
        self.mailchimp.failures.append(Failure(route="members", status=500, times=100, from_offset=1))
        run = runs.start_run(self.team.id, "mailchimp", ["audiences"], FULL_KEY, self.user.id, {})

        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "audiences", attempt=1)
        self.mailchimp.failures.clear()
        calls_before_retry = len(self.mailchimp.calls)
        runs.run_step(self.team.id, run.id, "audiences", attempt=2)

        retried = [
            (call["query"]["status"], call["query"]["offset"])
            for call in self.mailchimp.calls[calls_before_retry:]
            if call["route"] == "members" and call["query"].get("fields") != "total_items"
        ]
        assert retried[0] == ("unsubscribed", "0")
        assert {"Left.Person@example.com", "jürgen.müller@example.com"} <= set(self._opt_outs())

    def _change_after_each_read(self, status: str, change: Callable[[int, dict[str, Any]], None]) -> None:
        handle = self.mailchimp.handle
        audience = self.mailchimp.data["lists"][0]
        reads = 0

        def answer_then_change(
            path: str, query: dict[str, str], authorization: str
        ) -> tuple[int, dict[str, Any], dict[str, str]]:
            nonlocal reads
            answer = handle(path, query, authorization)
            if query.get("status") == status and path.endswith(f"{audience['id']}/members"):
                change(reads, audience)
                reads += 1
            return answer

        patcher = patch.object(self.mailchimp, "handle", answer_then_change)
        self.addCleanup(patcher.stop)
        patcher.start()

    @parameterized.expand(
        [
            # How many contacts leave the front of the list after each read of it.
            ("within_the_overlap", 250, [5], False),
            ("exactly_the_overlap", 250, [10], False),
            ("just_past_the_overlap", 250, [11], False),
            ("past_the_overlap_before_the_last_page", 205, [0, 20], False),
            ("shrinks_below_the_offset", 250, [0, 150], False),
            ("shrinks_to_nothing", 250, [250], False),
            ("past_the_overlap_on_every_read", 1000, [15] * 40, True),
        ]
    )
    def test_contacts_leaving_the_list_mid_import_skip_no_one(
        self, _name: str, total: int, leaving: list[int], keeps_changing: bool
    ) -> None:
        self._patch(f"{CLIENT}.PAGE_SIZE", 100)
        audience = self.mailchimp.data["lists"][0]
        audience["members"] = [
            {"email_address": f"person{number:04}@example.com", "status": "unsubscribed"} for number in range(total)
        ]

        def leave(read: int, audience: dict[str, Any]) -> None:
            audience["members"] = audience["members"][leaving[read] if read < len(leaving) else 0 :]

        self._change_after_each_read("unsubscribed", leave)
        run = self._run(["audiences"])

        assert run.status == "completed", run.progress
        progress = run.progress["audiences"]
        imported = {identifier for identifier in self._opt_outs() if identifier.startswith("person")}
        stayed = {member["email_address"] for member in audience["members"]}
        if keeps_changing:
            assert [warning.split(":")[0] for warning in progress["warnings"]] == ["Weekly newsletter"]
            assert max(stayed) in imported
        else:
            assert progress["warnings"] == []
            assert stayed <= imported
        # Contacts read again after a restart count once. The other audience has one unsubscribed contact.
        assert progress["counts"]["unsubscribed"] == len(imported) + 1

    def test_contacts_past_the_remembered_limit_import_once(self) -> None:
        self._patch(f"{CLIENT}.PAGE_SIZE", 100)
        self._patch("products.messaging.backend.provider_imports.mailchimp.MAX_REMEMBERED_CONTACTS", 50)
        emails = {f"person{number:04}@example.com" for number in range(250)}
        self.mailchimp.data["lists"][0]["members"] = [
            {"email_address": email, "status": "unsubscribed"} for email in sorted(emails)
        ]

        run = self._run(["audiences"])

        assert emails <= set(self._opt_outs())
        assert run.progress["audiences"]["counts"]["unsubscribed"] == len(emails) + 1

    def test_changed_contacts_moving_behind_unread_ones_hide_no_one(self) -> None:
        self._patch(f"{CLIENT}.PAGE_SIZE", 100)
        audience = self.mailchimp.data["lists"][0]
        audience["members"] = [
            {
                "email_address": f"person{number:04}@example.com",
                "status": "subscribed",
                "interests": {"int1": False, "int2": False},
                "last_changed": "2026-01-02T03:04:05+00:00",
            }
            for number in range(105)
        ]

        def change_twelve(read: int, audience: dict[str, Any]) -> None:
            if read == 0:
                moved = [{**member, "last_changed": "2026-05-02T03:04:05+00:00"} for member in audience["members"][:12]]
                audience["members"] = audience["members"][12:] + moved

        self._change_after_each_read("subscribed", change_twelve)
        run = self._run(["groups"])

        assert run.progress["groups"]["warnings"] == []
        assert {member["email_address"] for member in audience["members"]} <= set(self._opt_outs())

    def test_a_retry_after_a_restart_reads_the_list_from_the_start(self) -> None:
        self._patch(f"{CLIENT}.PAGE_SIZE", 100)
        audience = self.mailchimp.data["lists"][0]
        audience["members"] = [
            {"email_address": f"person{number:04}@example.com", "status": "unsubscribed"} for number in range(460)
        ]

        def leave_then_fail(read: int, audience: dict[str, Any]) -> None:
            if read == 2:
                audience["members"] = audience["members"][150:]
            if read == 3:
                self.mailchimp.failures.append(
                    Failure(route="members", status=500, times=100, status_filter="unsubscribed")
                )

        self._change_after_each_read("unsubscribed", leave_then_fail)
        run = runs.start_run(self.team.id, "mailchimp", ["audiences"], FULL_KEY, self.user.id, {})
        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "audiences", attempt=1)
        self.mailchimp.failures.clear()
        runs.run_step(self.team.id, run.id, "audiences", attempt=2)

        assert {member["email_address"] for member in audience["members"]} <= set(self._opt_outs())

    def test_an_audience_of_only_pending_contacts_imports(self) -> None:
        old_audience = self.mailchimp.data["lists"][2]
        old_audience["members"].append({"email_address": "unconfirmed@example.com", "status": "pending"})

        run = self._run(["audiences"])

        assert self._opt_outs()["unconfirmed@example.com"] == {"Old audience"}
        assert "empty_audiences" not in run.progress["audiences"]["counts"]

    def test_an_audience_deleted_after_its_first_list_is_reported_once(self) -> None:
        self.mailchimp.failures.append(Failure(route="members", status=404, times=100, status_filter="pending"))

        run = self._run(["audiences"])

        assert run.progress["audiences"]["counts"]["missing"] == 3
        assert len(run.progress["audiences"]["warnings"]) == 3

    def test_waits_out_a_rate_limit(self) -> None:
        self.mailchimp.failures.append(Failure(route="lists", status=429, times=2, headers={"Retry-After": "7"}))

        run = self._run(["cleaned"])

        assert run.status == "completed"
        assert [call.args[0] for call in self.sleep.call_args_list if call.args[0] >= 1] == [7.0, 7.0]

    @parameterized.expand(
        [
            ("no_suffix", "fakekeywithoutdatacenter"),
            ("host_in_suffix", "fake-key-evil.example.com"),
            ("path_in_suffix", "fake-key-us21/x"),
            ("port_in_suffix", "fake-key-us21:80"),
            ("newline_in_suffix", "fake-key-us21\n"),
        ]
    )
    def test_a_key_without_a_plain_data_center_is_refused_before_any_request(self, _name: str, key: str) -> None:
        with self.assertRaises(ImportCredentialsInvalid):
            MailchimpImportProvider().check_credentials(self.team.id, key, {}, ALL_STEPS)

        assert self.mailchimp.calls == []

    def test_a_rejected_key_fails_the_check(self) -> None:
        with self.assertRaises(ImportCredentialsInvalid):
            MailchimpImportProvider().check_credentials(self.team.id, "fake-wrong-key-us21", {}, ALL_STEPS)

        assert self.hosts == [HOST]

    def test_contacts_need_every_opt_out_step_in_the_run(self) -> None:
        with self.assertRaisesRegex(runs.InvalidImportSteps, "Contacts needs Groups, Abuse reports selected too"):
            runs.start_run(self.team.id, "mailchimp", ["audiences", "cleaned", "contacts"], FULL_KEY, self.user.id, {})


class TestMailchimpContacts(ClickhouseTestMixin, TestMailchimpImportBase):
    def setUp(self) -> None:
        super().setUp()
        self.people = PeopleImportRecorder(self)

    def _staged(self, run: ProviderImportRun) -> dict[str, dict[str, dict[str, str]]]:
        """Each cohort's people as the run stored them, by cohort name and then person ID."""
        return {
            Cohort.objects.get(id=plan["cohort_id"]).name or "": {
                person["distinct_id"]: person["properties"] for person in self.people.people(plan)
            }
            for plan in run.progress["contacts"]["people_imports"]
        }

    def _import_contacts(self, *extra_steps: str) -> ProviderImportRun:
        run = runs.start_run(
            self.team.id, "mailchimp", [*OPT_OUT_STEPS, "contacts", *extra_steps], FULL_KEY, self.user.id, {}
        )
        for step in run.steps:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        run.refresh_from_db()
        return run

    def _close(self, run: ProviderImportRun) -> None:
        runs.finish_run(self.team.id, run.id)

    def test_only_subscribed_members_become_people_and_fill_each_audience_cohort(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-ada"], properties={"email": "Ada@Example.com"})
        flush_persons_and_events()
        weekly, novedades, _ = self.mailchimp.data["lists"]
        weekly["members"][0]["merge_fields"] = {
            "FNAME": "Ada \x00Ñ 🎉",
            "LNAME": "",
            "COMPANY": "Example GmbH",
            "ADDRESS": {"addr1": "1 Main St", "addr2": "", "city": "Köln", "zip": "50667", "country": "DE"},
            "SEATS": 3,
            "ID": "other-person",
            "$browser": "no",
        }
        novedades["members"][0]["merge_fields"] = {"FNAME": "Other", "ROLE": "Admin"}
        weekly["members"].append(
            {
                "email_address": "Left.Person@example.com",
                "status": "cleaned",
                "last_changed": "2026-03-04T05:06:07+00:00",
            }
        )

        run = self._import_contacts("new_people")

        ada = {
            "email": "ada@example.com",
            "first_name": "Ada Ñ 🎉",
            "COMPANY": "Example GmbH",
            "ADDRESS": "1 Main St, Köln, 50667, DE",
            "SEATS": "3",
            "ROLE": "Admin",
        }
        grace = {"email": "Grace.Hopper@example.com"}
        linus = {"email": "linus@example.com"}
        assert self._staged(run) == {
            "Mailchimp contacts, Example Co": {
                "user-ada": ada,
                "Grace.Hopper@example.com": grace,
                "linus@example.com": linus,
            },
            "Weekly newsletter (from Mailchimp)": {
                "user-ada": ada,
                "Grace.Hopper@example.com": grace,
                "linus@example.com": linus,
            },
            "Novedades del producto ñ (from Mailchimp)": {"user-ada": ada},
        }
        assert run.progress["contacts"]["processed"] == 4
        assert run.progress["contacts"]["counts"]["repeats_merged"] == 1
        # The person PostHog already had spells the address differently, and a send matches it exactly.
        assert self._opt_outs()["Ada@Example.com"] == {"Event invitations 🎉"}

    def test_importing_again_drops_who_left_and_empties_an_audience_everyone_left(self) -> None:
        self._close(self._import_contacts("new_people"))
        weekly, novedades, _ = self.mailchimp.data["lists"]
        weekly["members"][0]["status"] = "unsubscribed"
        del weekly["members"][1]
        novedades["members"][0]["status"] = "archived"

        run = self._import_contacts("new_people")

        assert self._staged(run) == {
            "Mailchimp contacts, Example Co": {"linus@example.com": {"email": "linus@example.com"}},
            "Weekly newsletter (from Mailchimp)": {"linus@example.com": {"email": "linus@example.com"}},
            "Novedades del producto ñ (from Mailchimp)": {},
        }
        assert {"Weekly newsletter", "Novedades del producto ñ"} <= self._opt_outs()["ada@example.com"]

    @parameterized.expand([("not_found", 404), ("server_error", 500)])
    def test_an_audience_that_cannot_be_read_whole_leaves_every_cohort_alone(self, _name: str, status: int) -> None:
        self._patch(f"{CLIENT}.PAGE_SIZE", 2)
        run = runs.start_run(self.team.id, "mailchimp", [*OPT_OUT_STEPS, "contacts"], FULL_KEY, self.user.id, {})
        for step in OPT_OUT_STEPS:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        self.mailchimp.failures.append(
            Failure(route="members", status=status, times=100, from_offset=1, status_filter="subscribed")
        )

        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        run.refresh_from_db()
        assert "people_imports" not in run.progress["contacts"]
        assert not Cohort.objects.filter(team_id=self.team.id).exists()
        self.mailchimp.failures.clear()
        runs.run_step(self.team.id, run.id, "contacts", attempt=2)
        run.refresh_from_db()
        assert len(run.progress["contacts"]["people_imports"]) == 3

    def test_a_second_account_leaves_the_first_accounts_cohort_alone(self) -> None:
        first = self._import_contacts("new_people")
        self._close(first)
        self.mailchimp.data["account"] = {"account_id": "acct2", "account_name": "Example Co"}
        for audience in self.mailchimp.data["lists"]:
            audience["id"] = f"{audience['id']}-2"
            audience["members"] = audience["members"][:1]

        second = self._import_contacts("new_people")

        cohorts = [
            {plan["cohort_id"] for plan in run.progress["contacts"]["people_imports"]} for run in (first, second)
        ]
        assert all(cohorts)
        assert cohorts[0].isdisjoint(cohorts[1])

    @parameterized.expand(
        [
            ("audiences", "members", "unsubscribed"),
            ("groups", "members", "subscribed"),
            ("cleaned", "members", "cleaned"),
            ("complaints", "abuse", None),
        ]
    )
    def test_contacts_wait_when_an_audience_hid_its_opt_outs(
        self, step: str, route: str, status_filter: str | None
    ) -> None:
        run = runs.start_run(self.team.id, "mailchimp", [*OPT_OUT_STEPS, "contacts"], FULL_KEY, self.user.id, {})
        for earlier in OPT_OUT_STEPS[: OPT_OUT_STEPS.index(step)]:
            runs.run_step(self.team.id, run.id, earlier, attempt=1)
        self.mailchimp.failures.append(Failure(route=route, status=404, times=100, status_filter=status_filter))

        with self.assertRaisesRegex(ImportProviderUnavailable, "couldn't find this audience"):
            runs.run_step(self.team.id, run.id, step, attempt=1)
        with self.assertRaises(ImportStepBlocked):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

    @parameterized.expand([("members", "unsubscribed", "audiences"), ("members", "subscribed", "contacts")])
    def test_a_list_shorter_than_its_total_is_not_whole(self, route: str, status: str, step: str) -> None:
        handle = self.mailchimp.handle

        def short(path: str, query: dict[str, str], authorization: str) -> tuple[int, dict[str, Any], dict[str, str]]:
            code, body, headers = handle(path, query, authorization)
            if path.endswith(f"/{route}") and query.get("status") == status and "members" in body:
                wanted = "merge_fields" in query.get("fields", "") if step == "contacts" else True
                body = {"total_items": body["total_items"]} if wanted else body
            return code, body, headers

        run = runs.start_run(self.team.id, "mailchimp", [*OPT_OUT_STEPS, "contacts"], FULL_KEY, self.user.id, {})
        for earlier in run.steps[: run.steps.index(step)]:
            runs.run_step(self.team.id, run.id, earlier, attempt=1)
        with patch.object(self.mailchimp, "handle", short), self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, step, attempt=1)

        assert not Cohort.objects.filter(team_id=self.team.id).exists()

    @parameterized.expand(
        [("empty", []), ("a_lower_total", [{"email_address": "x@example.com", "status": "subscribed"}])]
    )
    def test_a_later_page_that_denies_the_rest_of_the_list_is_not_the_end(
        self, _name: str, items: list[dict[str, str]]
    ) -> None:
        self._patch(f"{CLIENT}.PAGE_SIZE", 1)
        handle = self.mailchimp.handle

        def denied(path: str, query: dict[str, str], authorization: str) -> tuple[int, dict[str, Any], dict[str, str]]:
            if "merge_fields" in query.get("fields", "") and int(query.get("offset", 0)) > 0:
                return 200, {"members": items, "total_items": len(items) and 1}, {}
            return handle(path, query, authorization)

        run = runs.start_run(self.team.id, "mailchimp", [*OPT_OUT_STEPS, "contacts"], FULL_KEY, self.user.id, {})
        for step in OPT_OUT_STEPS:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        with patch.object(self.mailchimp, "handle", denied), self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert not Cohort.objects.filter(team_id=self.team.id).exists()

    @parameterized.expand([("opt_in", "timestamp_opt"), ("no_opt_in_time", "last_changed")])
    def test_a_contact_who_joined_after_the_run_started_waits_for_the_next_import(self, _name: str, field: str) -> None:
        self.mailchimp.data["lists"][1]["members"].append(
            {
                "email_address": "new@example.com",
                "status": "subscribed",
                field: (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            }
        )

        run = self._import_contacts("new_people")

        assert "new@example.com" not in self._staged(run)["Mailchimp contacts, Example Co"]

    def _add_segments(self, audience: int, *segments: tuple[int, str, str, list[str]]) -> None:
        self.mailchimp.data["lists"][audience]["segments"] = [
            {"id": segment_id, "name": name, "type": kind, "emails": emails}
            for segment_id, name, kind, emails in segments
        ]

    def test_each_tag_and_segment_fills_a_cohort_with_its_subscribed_members(self) -> None:
        everyone = [member["email_address"] for member in self.mailchimp.data["lists"][0]["members"]]
        self._add_segments(
            0,
            (1, "VIP 🎉", "static", ["ada@example.com", *everyone[3:]]),
            (2, "VIP 🎉", "saved", ["linus@example.com"]),
            (3, "Made by Mailchimp", "fuzzy", everyone),
            (4, "Empty", "static", []),
        )
        self._add_segments(1, (5, "VIP 🎉", "static", ["ada@example.com"]))

        run = self._import_contacts("new_people")

        staged = {name: set(people) for name, people in self._staged(run).items() if " in " in name}
        assert staged == {
            "VIP 🎉 (tag in Weekly newsletter, from Mailchimp)": {"ada@example.com"},
            "VIP 🎉 (segment in Weekly newsletter, from Mailchimp)": {"linus@example.com"},
            "VIP 🎉 (tag in Novedades del producto ñ, from Mailchimp)": {"ada@example.com"},
        }
        self._close(run)
        self._add_segments(0, (1, "Renamed", "static", []))

        later = self._staged(self._import_contacts("new_people"))

        # The tag's cohort keeps its name and loses the person who left the tag.
        assert later["VIP 🎉 (tag in Weekly newsletter, from Mailchimp)"] == {}

    def test_a_tag_takes_only_members_the_audience_read_as_subscribed(self) -> None:
        self._add_segments(0, (1, "Old", "static", ["Left.Person@example.com", "ada@example.com"]))
        left = self.mailchimp.data["lists"][0]["members"][3]
        handle = self.mailchimp.handle

        def resubscribed_since(
            path: str, query: dict[str, str], authorization: str
        ) -> tuple[int, dict[str, Any], dict[str, str]]:
            if "/segments/" in path:
                left["status"] = "subscribed"
            return handle(path, query, authorization)

        with patch.object(self.mailchimp, "handle", resubscribed_since):
            run = self._import_contacts("new_people")

        assert set(self._staged(run)["Old (tag in Weekly newsletter, from Mailchimp)"]) == {"ada@example.com"}

    @parameterized.expand([("not_found", 404, 0), ("server_error", 500, 0), ("later_page", 500, 1)])
    def test_a_tag_that_cannot_be_read_whole_keeps_its_cohort_and_the_contacts_still_import(
        self, _name: str, status: int, from_offset: int
    ) -> None:
        self._patch(f"{CLIENT}.PAGE_SIZE", 1)
        self._add_segments(0, (1, "Old", "static", ["linus@example.com", "ada@example.com"]))
        self.mailchimp.failures.append(
            Failure(route="segment_members", status=status, times=100, from_offset=from_offset)
        )

        run = self._import_contacts("new_people")

        assert run.progress["contacts"]["status"] == "completed"
        assert set(self._staged(run)) == {
            "Mailchimp contacts, Example Co",
            "Weekly newsletter (from Mailchimp)",
            "Novedades del producto ñ (from Mailchimp)",
        }
        item = run.progress["contacts"]["items"][1]
        assert (item["label"], item["status"]) == ("Old (tag in Weekly newsletter, from Mailchimp)", "failed")
        assert "its cohort stays as it is" in item["notes"][0]

    @parameterized.expand([("segments", 2, 250_000), ("memberships", 300, 1)])
    def test_an_account_past_a_segment_limit_still_imports_its_contacts(
        self, _name: str, max_segments: int, max_memberships: int
    ) -> None:
        module = "products.messaging.backend.provider_imports.mailchimp"
        self._patch(f"{module}.MAX_SEGMENTS", max_segments)
        self._patch(f"{module}.MAX_SEGMENT_MEMBERSHIPS", max_memberships)
        too_many = ["ada@example.com", "linus@example.com"] if max_memberships == 1 else []
        self._add_segments(
            0,
            (1, "Too many people", "static", too_many),
            (2, "Older", "static", ["ada@example.com"]),
            (7, "Newer", "static", ["ada@example.com"]),
        )

        run = self._import_contacts("new_people")

        assert [name for name in self._staged(run) if " in " in name] == [
            "Older (tag in Weekly newsletter, from Mailchimp)"
        ]
        assert re.match(r"[12] more", run.progress["contacts"]["items"][1]["notes"][0])

    def test_reads_of_tags_stop_after_several_fail(self) -> None:
        self._add_segments(0, *((number, f"Tag {number}", "static", ["ada@example.com"]) for number in range(1, 10)))
        self.mailchimp.failures.append(Failure(route="segment_members", status=500, times=1000))

        run = self._import_contacts("new_people")

        assert run.progress["contacts"]["status"] == "completed"
        tried = {call["path"] for call in self.mailchimp.calls if call["route"] == "segment_members"}
        assert len(tried) == 5
        assert run.progress["contacts"]["items"][6]["notes"][0].startswith("4 more")

    def test_listing_tags_stops_at_its_page_limit(self) -> None:
        module = "products.messaging.backend.provider_imports.mailchimp"
        self._patch(f"{module}.MAX_EXTRA_SEGMENT_PAGES", 1)
        self._patch(f"{CLIENT}.PAGE_SIZE", 4)
        self._add_segments(0, *((number, f"Tag {number}", "static", []) for number in range(1, 20)))

        run = self._import_contacts("new_people")

        assert run.progress["contacts"]["status"] == "completed"
        assert sum(call["route"] == "segments" for call in self.mailchimp.calls) == 4
        assert run.progress["contacts"]["items"][1]["notes"][0].startswith("11 more tags and segments")

    @parameterized.expand([("empty_page", {"segments": [], "total_items": 0}), ("no_total", {"segments": []})])
    def test_a_tag_list_that_breaks_off_is_reported(self, _name: str, later: dict[str, Any]) -> None:
        self._patch(f"{CLIENT}.PAGE_SIZE", 4)
        self._add_segments(0, *((number, f"Tag {number}", "static", []) for number in range(1, 8)))
        handle = self.mailchimp.handle

        def broken(path: str, query: dict[str, str], authorization: str) -> tuple[int, dict[str, Any], dict[str, str]]:
            if path.endswith("/segments") and int(query.get("offset", 0)):
                return 200, later, {}
            return handle(path, query, authorization)

        with patch.object(self.mailchimp, "handle", broken):
            run = self._import_contacts("new_people")

        assert not any(" in " in name for name in self._staged(run))
        assert run.progress["contacts"]["counts"]["segments_failed"] == 1
        assert run.progress["contacts"]["items"][1]["label"] == "Tags and segments in Weekly newsletter"

    def test_listing_tags_stops_after_several_audiences_fail(self) -> None:
        self.mailchimp.data["lists"] += [
            {
                "id": f"extra{number}",
                "name": f"Extra {number}",
                "members": [],
                "abuse_reports": [],
                "interest_categories": [],
            }
            for number in range(4)
        ]
        self.mailchimp.failures.append(Failure(route="segments", status=500, times=1000))

        run = self._import_contacts("new_people")

        assert run.progress["contacts"]["status"] == "completed"
        assert len({call["path"] for call in self.mailchimp.calls if call["route"] == "segments"}) == 5
        items = {item["label"]: item["notes"][0] for item in run.progress["contacts"]["items"]}
        assert items["Tags and segments in other audiences"].startswith("2 more audiences")

    def test_contacts_import_when_an_audience_hides_its_tags(self) -> None:
        self.mailchimp.failures.append(Failure(route="segments", status=500, times=1000))

        run = self._import_contacts("new_people")

        assert run.progress["contacts"]["status"] == "completed"
        assert run.progress["contacts"]["items"][1]["label"] == "Tags and segments in Old audience"

    def _cohort(self, name: str) -> Cohort:
        return Cohort.objects.get(team_id=self.team.id, name=name)

    def _emptied(self, run: ProviderImportRun) -> dict[str, tuple[str, str]]:
        """Each item that names a cohort an import before made for an audience that's missing now."""
        return {
            item["label"]: (item["status"], item["notes"][0])
            for item in run.progress["contacts"]["items"]
            if item["notes"][0] in (DELETED_AUDIENCE_NOTE, NOT_EMPTIED_NOTE)
        }

    def test_the_cohort_of_a_deleted_audience_is_emptied_and_named_every_time(self) -> None:
        self._close(self._import_contacts("new_people"))
        Cohort.objects.filter(id=self._cohort(NOVEDADES).id).update(name="Renamed here")
        del self.mailchimp.data["lists"][1]

        for _ in range(2):
            run = self._import_contacts("new_people")

            staged = self._staged(run)
            assert staged["Renamed here"] == {}
            assert set(staged["Mailchimp contacts, Example Co"]) == {
                "ada@example.com",
                "Grace.Hopper@example.com",
                "linus@example.com",
            }
            assert self._emptied(run) == {"Renamed here": ("listed", DELETED_AUDIENCE_NOTE)}
            assert [item["label"] for item in run.progress["contacts"]["items"]][:3] == [
                "Mailchimp contacts, Example Co",
                "Renamed here",
                "Old audience (from Mailchimp)",
            ]
            assert "Novedades del producto ñ" in self._opt_outs()["Left.Person@example.com"]
            self._close(run)

    def _hide(self) -> None:
        self.mailchimp.data["lists"][1]["hidden"] = True

    def _delete(self) -> None:
        del self.mailchimp.data["lists"][1]

    def _as_manager(self) -> None:
        self._delete()
        self.mailchimp.data["account"] = {"account_id": "acct1", "account_name": "Example Co", "role": "manager"}

    def _refuse_read(self, status: int) -> None:
        self._delete()
        self.mailchimp.failures.append(Failure(route="list", status=status, times=100))

    @parameterized.expand(
        [
            ("still_there", lambda test: test._hide()),
            ("role_without_every_audience", lambda test: test._as_manager()),
            ("forbidden", lambda test: test._refuse_read(403)),
            ("server_error", lambda test: test._refuse_read(500)),
        ]
    )
    def test_an_audience_not_confirmed_deleted_changes_no_cohort(
        self, _name: str, change: Callable[["TestMailchimpContacts"], None]
    ) -> None:
        self._close(self._import_contacts("new_people"))
        change(self)
        run = runs.start_run(self.team.id, "mailchimp", [*OPT_OUT_STEPS, "contacts"], FULL_KEY, self.user.id, {})
        for step in OPT_OUT_STEPS:
            runs.run_step(self.team.id, run.id, step, attempt=1)

        with self.assertRaises((ImportProviderUnavailable, ImportCredentialsInvalid)):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        run.refresh_from_db()
        assert "people_imports" not in run.progress["contacts"]

    def _use_account(self, account_id: str) -> None:
        self.mailchimp.data["account"] = {"account_id": account_id, "account_name": "Other", "role": "owner"}

    def _change_cohort(self, **values: Any) -> None:
        Cohort.objects.filter(id=self._cohort(NOVEDADES).id).update(**values)

    def _forget_imports(self) -> None:
        ProviderImportRun.objects.for_team(self.team.id).delete()

    @parameterized.expand(
        [
            ("another_account", lambda test: test._use_account("acct2")),
            ("account_id_that_starts_the_same", lambda test: test._use_account("acct")),
            ("account_id_that_goes_on", lambda test: test._use_account("acct10")),
            ("made_dynamic", lambda test: test._change_cohort(is_static=False)),
            ("deleted_in_posthog", lambda test: test._change_cohort(deleted=True)),
            ("description_edited", lambda test: test._change_cohort(description="Mine now")),
            (
                "account_unknown",
                lambda test: test._change_cohort(description="Imported from Mailchimp audience f6e5d4c3b2."),
            ),
            ("not_made_by_an_import", lambda test: test._forget_imports()),
        ]
    )
    def test_a_deleted_audience_leaves_cohorts_that_are_not_its_own_alone(
        self, _name: str, change: Callable[["TestMailchimpContacts"], None]
    ) -> None:
        self._close(self._import_contacts("new_people"))
        cohort_id = self._cohort(NOVEDADES).id
        self._delete()
        change(self)

        run = self._import_contacts("new_people")

        assert cohort_id not in {plan["cohort_id"] for plan in run.progress["contacts"]["people_imports"]}
        assert self._emptied(run) == {}

    @parameterized.expand([("newer_copy", False), ("older_cohort_given_its_description", True)])
    def test_a_cohort_someone_gave_the_same_description_is_not_emptied(self, _name: str, older: bool) -> None:
        other = Cohort.objects.create(team_id=self.team.id, name="Mine", is_static=True) if older else None
        self._close(self._import_contacts("new_people"))
        imported = self._cohort(NOVEDADES)
        other = other or Cohort.objects.create(team_id=self.team.id, name="Mine", is_static=True)
        Cohort.objects.filter(id=other.id).update(description=imported.description)
        self._delete()

        run = self._import_contacts("new_people")

        assert other.id not in {plan["cohort_id"] for plan in run.progress["contacts"]["people_imports"]}

    def test_a_cohort_that_could_not_be_emptied_says_so(self) -> None:
        self._close(self._import_contacts("new_people"))
        self._delete()
        handle = self.mailchimp.handle

        def edited_meanwhile(
            path: str, query: dict[str, str], authorization: str
        ) -> tuple[int, dict[str, Any], dict[str, str]]:
            if path.endswith("/lists/f6e5d4c3b2"):
                self._change_cohort(description="Mine now")
            return handle(path, query, authorization)

        with patch.object(self.mailchimp, "handle", edited_meanwhile):
            run = self._import_contacts("new_people")

        assert self._emptied(run) == {NOVEDADES: ("failed", NOT_EMPTIED_NOTE)}

    def test_an_account_whose_audiences_were_all_deleted_empties_every_cohort(self) -> None:
        self._close(self._import_contacts("new_people"))
        self.mailchimp.data["lists"] = []

        run = self._import_contacts("new_people")

        assert self._staged(run) == {
            "Mailchimp contacts, Example Co": {},
            "Weekly newsletter (from Mailchimp)": {},
            NOVEDADES: {},
        }
        account = run.progress["contacts"]["items"][0]
        assert (account["label"], account["status"]) == ("Mailchimp contacts, Example Co", "listed")

    def test_an_account_that_hides_every_audience_changes_no_cohort(self) -> None:
        self._close(self._import_contacts("new_people"))
        for audience in self.mailchimp.data["lists"]:
            audience["hidden"] = True

        run = runs.start_run(self.team.id, "mailchimp", [*OPT_OUT_STEPS, "contacts"], FULL_KEY, self.user.id, {})
        for step in OPT_OUT_STEPS:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        run.refresh_from_db()
        assert "people_imports" not in run.progress["contacts"]

    def _only_account_cohort_left(self) -> int:
        self._close(self._import_contacts("new_people"))
        Cohort.objects.filter(team_id=self.team.id, description__contains=", audience ").update(description="Mine now")
        self.mailchimp.data["lists"] = []
        return self._cohort("Mailchimp contacts, Example Co").id

    def _contacts_step(self) -> ProviderImportRun:
        run = runs.start_run(self.team.id, "mailchimp", [*OPT_OUT_STEPS, "contacts"], FULL_KEY, self.user.id, {})
        for step in OPT_OUT_STEPS:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        return run

    @parameterized.expand([("owner",), ("admin",)])
    def test_an_account_without_audiences_empties_its_cohort_every_time(self, role: str) -> None:
        cohort_id = self._only_account_cohort_left()
        self._set_role(role)
        Cohort.objects.filter(id=cohort_id).update(name="Renamed here")

        for _ in range(2):
            run = self._import_contacts("new_people")

            assert self._staged(run) == {"Renamed here": {}}
            assert [
                (item["label"], item["status"], item["url"], item["notes"])
                for item in run.progress["contacts"]["items"]
            ] == [("Renamed here", "listed", f"/cohorts/{cohort_id}", [ALL_DELETED_NOTE])]
            self._close(run)

    def _set_role(self, role: str | None) -> None:
        account = {"account_id": "acct1", "account_name": "Example Co"}
        self.mailchimp.data["account"] = account | ({} if role is None else {"role": role})

    @parameterized.expand([("manager",), ("author",), ("viewer",), ("superuser",), ("",), (None,)])
    def test_a_role_that_may_not_see_every_audience_empties_no_account_cohort(self, role: str | None) -> None:
        self._only_account_cohort_left()
        self._set_role(role)
        run = self._contacts_step()

        with self.assertRaisesMessage(ImportCredentialsInvalid, NO_AUDIENCES_ROLE_MESSAGE):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        run.refresh_from_db()
        assert "people_imports" not in run.progress["contacts"]

    @parameterized.expand(
        [
            ("first_error", 1, (500, {}, {}), "HTTP 500. Import again in a few minutes. No cohort changed."),
            ("first_has_no_total", 1, (200, {"lists": []}, {}), "unexpected response"),
            ("first_is_short", 1, (200, {"lists": [], "total_items": 1}, {}), "unexpected response"),
            ("second_error", 2, (500, {}, {}), None),
            ("second_rate_limited", 2, (429, {}, {}), None),
            ("second_has_no_total", 2, (200, {"lists": []}, {}), None),
            ("second_total_not_a_number", 2, (200, {"lists": [], "total_items": False}, {}), None),
            ("second_total_not_zero", 2, (200, {"lists": [], "total_items": 1}, {}), None),
            ("second_has_no_list", 2, (200, {"total_items": 0}, {}), None),
            ("second_lists_an_audience", 2, (200, {"lists": [{"id": "x"}], "total_items": 0}, {}), None),
            ("second_lists_null", 2, (200, {"lists": None, "total_items": 0}, {}), None),
        ]
    )
    def test_an_empty_audience_list_not_confirmed_empties_no_account_cohort(
        self, _name: str, changed_from: int, answer: tuple[int, dict, dict], message: str | None
    ) -> None:
        self._only_account_cohort_left()
        run = self._contacts_step()
        handle = self.mailchimp.handle
        reads = 0

        def changed(path: str, query: dict[str, str], authorization: str) -> tuple[int, dict[str, Any], dict[str, str]]:
            nonlocal reads
            if not path.endswith("/lists"):
                return handle(path, query, authorization)
            reads += 1
            return answer if reads >= changed_from else handle(path, query, authorization)

        with (
            patch.object(self.mailchimp, "handle", changed),
            self.assertRaisesRegex(ImportProviderUnavailable, re.escape(message or NO_AUDIENCES_UNCONFIRMED_MESSAGE)),
        ):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        run.refresh_from_db()
        assert "people_imports" not in run.progress["contacts"]

    @parameterized.expand([("error", 500, {}), ("rejected", 403, {}), ("without_account_id", 200, {"role": "owner"})])
    def test_an_account_that_cannot_be_read_empties_no_account_cohort(
        self, _name: str, status: int, body: dict
    ) -> None:
        self._only_account_cohort_left()
        run = self._contacts_step()
        handle = self.mailchimp.handle

        def changed(path: str, query: dict[str, str], authorization: str) -> tuple[int, dict[str, Any], dict[str, str]]:
            return (status, body, {}) if path == "/3.0/" else handle(path, query, authorization)

        with (
            patch.object(self.mailchimp, "handle", changed),
            self.assertRaisesRegex((ImportProviderUnavailable, ImportCredentialsInvalid), "No cohort changed"),
        ):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        run.refresh_from_db()
        assert "people_imports" not in run.progress["contacts"]

    def _change_account_cohort(self, **values: Any) -> None:
        Cohort.objects.filter(id=self._cohort("Mailchimp contacts, Example Co").id).update(**values)

    @parameterized.expand(
        [
            ("another_account", lambda test: test._use_account("acct2")),
            ("account_id_that_starts_the_same", lambda test: test._use_account("acct")),
            ("account_id_that_goes_on", lambda test: test._use_account("acct10")),
            ("made_dynamic", lambda test: test._change_account_cohort(is_static=False)),
            ("deleted_in_posthog", lambda test: test._change_account_cohort(deleted=True)),
            ("description_edited", lambda test: test._change_account_cohort(description="Mine now")),
            ("not_made_by_an_import", lambda test: test._forget_imports()),
        ]
    )
    def test_an_account_without_audiences_changes_no_cohort_but_its_own(
        self, _name: str, change: Callable[["TestMailchimpContacts"], None]
    ) -> None:
        self._only_account_cohort_left()
        change(self)

        run = self._import_contacts("new_people")

        assert run.progress["contacts"]["status"] == "completed"
        assert "people_imports" not in run.progress["contacts"]
        assert run.progress["contacts"]["items"][0]["notes"] == [NO_AUDIENCES_NOTE]

    @parameterized.expand(
        [
            ("error", (500, {}, {})),
            ("short", (200, {"lists": [], "total_items": 2}, {})),
            ("denies_the_rest", (200, {"lists": [], "total_items": 0}, {})),
            ("repeats_one", None),
            ("without_an_id", (200, {"lists": [{"name": "x"}], "total_items": 2}, {})),
        ]
    )
    def test_an_audience_list_not_read_whole_empties_nothing(
        self, name: str, later: tuple[int, dict, dict] | None
    ) -> None:
        self._close(self._import_contacts("new_people"))
        run = runs.start_run(self.team.id, "mailchimp", [*OPT_OUT_STEPS, "contacts"], FULL_KEY, self.user.id, {})
        for step in OPT_OUT_STEPS:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        self._patch(f"{CLIENT}.PAGE_SIZE", 1)
        del self.mailchimp.data["lists"][2]
        handle = self.mailchimp.handle

        def cut(path: str, query: dict[str, str], authorization: str) -> tuple[int, dict[str, Any], dict[str, str]]:
            answer = handle(path, query, authorization)
            if not path.endswith("/lists") or query.get("offset") == "0":
                return answer
            first = {"id": self.mailchimp.data["lists"][0]["id"], "name": "again"}
            return later or (200, {"lists": [first], "total_items": 2}, {})

        with patch.object(self.mailchimp, "handle", cut), self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        run.refresh_from_db()
        assert "people_imports" not in run.progress["contacts"]

    def test_the_tag_and_segment_cohorts_of_a_deleted_audience_are_emptied_too(self) -> None:
        self._add_segments(0, (1, "Stays", "static", ["ada@example.com"]))
        self._add_segments(1, (5, "VIP", "static", ["ada@example.com"]), (6, "VIP", "saved", ["ada@example.com"]))
        self._close(self._import_contacts("new_people"))
        self._delete()

        for _ in range(2):
            run = self._import_contacts("new_people")

            staged = self._staged(run)
            gone = {
                NOVEDADES,
                "VIP (tag in Novedades del producto ñ, from Mailchimp)",
                "VIP (segment in Novedades del producto ñ, from Mailchimp)",
            }
            assert {name for name, people in staged.items() if not people} == gone
            assert set(staged["Stays (tag in Weekly newsletter, from Mailchimp)"]) == {"ada@example.com"}
            assert self._emptied(run) == dict.fromkeys(gone, ("listed", DELETED_AUDIENCE_NOTE))
            self._close(run)

    def test_a_deleted_tag_of_an_audience_that_remains_keeps_its_cohort(self) -> None:
        self._add_segments(0, (1, "VIP", "static", ["ada@example.com"]))
        self._close(self._import_contacts("new_people"))
        self._add_segments(0)

        run = self._import_contacts("new_people")

        assert "VIP (tag in Weekly newsletter, from Mailchimp)" not in self._staged(run)
        assert self._emptied(run) == {}
