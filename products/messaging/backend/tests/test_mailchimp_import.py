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
from products.messaging.backend.provider_imports.mailchimp import MailchimpImportProvider
from products.messaging.backend.tests.fake_mailchimp import FULL_KEY, Failure, FakeMailchimp, split_url
from products.messaging.backend.tests.people_import_recorder import PeopleImportRecorder

CLIENT = "products.messaging.backend.services.mailchimp_client"
HOST = "https://us21.api.mailchimp.com"
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

    def test_a_contact_who_joined_after_the_run_started_waits_for_the_next_import(self) -> None:
        self.mailchimp.data["lists"][1]["members"].append(
            {
                "email_address": "new@example.com",
                "status": "subscribed",
                "timestamp_opt": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            }
        )

        run = self._import_contacts("new_people")

        assert "new@example.com" not in self._staged(run)["Mailchimp contacts, Example Co"]
