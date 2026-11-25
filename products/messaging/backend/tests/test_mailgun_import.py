import base64
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.cohorts.backend.models.cohort import Cohort
from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
)
from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.provider_import_run import ProviderImportRun
from products.messaging.backend.models.transactional_email_key import TransactionalEmailKey
from products.messaging.backend.provider_imports import mailgun, runs
from products.messaging.backend.provider_imports.base import (
    ImportCredentialsInvalid,
    ImportProviderUnavailable,
    ImportStepBlocked,
)
from products.messaging.backend.provider_imports.imported_senders import apply_sender
from products.messaging.backend.provider_imports.liquid_text import literal_liquid
from products.messaging.backend.provider_imports.mailgun import (
    COMPLAINT_REASON_PREFIX,
    TEMPLATE_KEY_MAX_LENGTH,
    MailgunImportProvider,
    _Target,
    _template_key,
)
from products.messaging.backend.services.mailgun_client import MailgunRegion
from products.messaging.backend.services.suppression import ComplaintConfirmationRequired, remove_suppressions
from products.messaging.backend.tests.fake_mailgun import (
    ANALYST_KEY,
    EMPTY_KEY,
    EU_ONLY_KEY,
    FULL_KEY,
    Failure,
    FakeMailgun,
    split_url,
)
from products.messaging.backend.tests.people_import_recorder import PeopleImportRecorder

US = "https://api.mailgun.net"
EU = "https://api.eu.mailgun.net"
CONTACT_STEPS = ("contacts", "new_people")
ALL_STEPS = [spec.key for spec in MailgunImportProvider.steps if spec.key not in CONTACT_STEPS]
CONTACT_RUN = ["bounces", "complaints", "unsubscribes", "mailing_lists", *CONTACT_STEPS]
CLIENT = "products.messaging.backend.services.mailgun_client"
ACCOUNT_TEMPLATES = "/v4/templates"
EU_WELCOME = _template_key(_Target(region=MailgunRegion.EU, owner="", name="", path=ACCOUNT_TEMPLATES), "welcome", None)


def _domain_welcome(domain: str) -> str:
    return _template_key(
        _Target(region=MailgunRegion.US, owner="", name=domain, path=f"/v3/{domain}/templates"), "welcome", None
    )


DOMAIN_WELCOME = _domain_welcome("mg.example.com")
WELCOME_V1 = _template_key(_Target(region=MailgunRegion.US, owner="", name="", path=ACCOUNT_TEMPLATES), "welcome", "v1")


class _MailgunTestCase(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.mailgun = FakeMailgun({US: "us", EU: "eu"})
        self.sleep = self._patch(f"{CLIENT}.time.sleep")
        self.start_workflow = self._patch(
            "products.messaging.backend.provider_imports.runs.start_provider_import_workflow"
        )
        self._patch(f"{CLIENT}.requests.get", self._get)
        self._patch(f"{CLIENT}.REQUESTS_PER_SECOND", 100000)

    def _patch(self, target: str, *replacement: Any) -> Any:
        patcher = patch(target, *replacement)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def _get(
        self,
        url: str,
        params: dict | None = None,
        auth: tuple[str, str] | None = None,
        headers: dict | None = None,
        **_: Any,
    ) -> MagicMock:
        base, path, query = split_url(url)
        query = {**query, **{key: str(value) for key, value in (params or {}).items()}}
        credentials = f"{auth[0]}:{auth[1]}".encode() if auth else b""
        status, body, response_headers = self.mailgun.handle(
            base,
            path,
            query,
            f"Basic {base64.b64encode(credentials).decode()}",
            (headers or {}).get("X-Mailgun-On-Behalf-Of"),
        )
        response = MagicMock(status_code=status, ok=status < 400, headers=response_headers)
        response.json.return_value = body
        return response

    def _start(
        self, steps: list[str] | None = None, region: str = "both", key: str = FULL_KEY, **settings: str
    ) -> ProviderImportRun:
        return runs.start_run(
            self.team.id, "mailgun", steps or ALL_STEPS, key, self.user.id, {"region": region, **settings}
        )

    def _run(
        self, steps: list[str] | None = None, region: str = "both", key: str = FULL_KEY, **settings: str
    ) -> ProviderImportRun:
        run = self._start(steps, region, key, **settings)
        for step in run.steps:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        runs.finish_run(self.team.id, run.id)
        run.refresh_from_db()
        return run

    def _suppressions(self) -> dict[str, MessageSuppression]:
        return {row.identifier: row for row in MessageSuppression.objects.for_team(self.team.id).filter(deleted=False)}

    def _preferences(self) -> dict[str, dict[str, str]]:
        return {
            row.identifier: row.preferences for row in MessageRecipientPreference.objects.filter(team_id=self.team.id)
        }


class TestMailgunImport(_MailgunTestCase):
    def test_bounces_outrank_complaints_across_domains_and_regions(self) -> None:
        run = self._run(["bounces", "complaints"])

        rows = self._suppressions()
        assert {identifier: row.source for identifier, row in rows.items()} == {
            "gone.person@example.com": SuppressionSource.BOUNCE,
            "both@example.com": SuppressionSource.BOUNCE,
            "josé@example.com": SuppressionSource.BOUNCE,
            "sub-bounce@example.com": SuppressionSource.BOUNCE,
            "eu-bounce@example.com": SuppressionSource.BOUNCE,
            "angry@example.com": SuppressionSource.COMPLAINT,
        }
        assert rows["both@example.com"].hard_bounced_at is not None
        assert rows["angry@example.com"].hard_bounced_at is None
        assert rows["josé@example.com"].last_bounce_diagnostic == "551 Boîte inconnue 📭"
        assert rows["gone.person@example.com"].suppressed_at == datetime(2025, 12, 11, 1, 49, 40, tzinfo=UTC)
        assert run.progress["bounces"]["counts"] == {"bounced": 5, "already_present": 1, "invalid": 1}
        assert run.progress["complaints"]["counts"] == {"complained": 1, "already_present": 1, "invalid": 0}

    def test_a_bounce_that_resumes_after_complaints_still_blocks_transactional_email(self) -> None:
        self._run(["complaints"], region="us")
        remove_suppressions(self.team.id, ["angry@example.com"], confirm_complaints=True)
        self.mailgun.data["us"]["bounces"]["mg.example.com"].append(
            {"address": "angry@example.com", "code": "550", "error": "x", "created_at": "Thu, 11 Dec 2025 01:49:40 UTC"}
        )

        run = self._run(["bounces"], region="us")

        rows = self._suppressions()
        assert rows["both@example.com"].source == SuppressionSource.COMPLAINT
        assert rows["both@example.com"].hard_bounced_at is not None
        assert rows["both@example.com"].last_bounce_diagnostic == "550 User unknown"
        assert "angry@example.com" not in rows
        assert run.progress["bounces"]["counts"]["bounced"] == 3
        with self.assertRaises(ComplaintConfirmationRequired):
            remove_suppressions(self.team.id, ["both@example.com"], confirm_complaints=False)

    def test_a_bounce_from_a_child_environment_reaches_the_complaint_on_its_project(self) -> None:
        child = Team.objects.create(organization=self.organization, project=self.project, parent_team=self.team)
        MessageSuppression.objects.for_team(self.team.id).create(
            team=self.team,
            identifier="both@example.com",
            source=SuppressionSource.COMPLAINT,
            reason=f"{COMPLAINT_REASON_PREFIX}mg.example.com)",
            suppressed=True,
        )
        run = runs.start_run(child.id, "mailgun", ["bounces"], FULL_KEY, self.user.id, {"region": "us"})

        runs.run_step(child.id, run.id, "bounces", attempt=1)

        assert self._suppressions()["both@example.com"].hard_bounced_at is not None

    def test_unsubscribes_opt_out_of_everything_or_only_their_tags(self) -> None:
        run = self._run(["unsubscribes"])

        categories = {
            row.name: str(row.id)
            for row in MessageCategory.objects.filter(team_id=self.team.id, key__startswith="mailgun_tag_")
        }
        assert set(categories) == {"newsletter", "promo 🎁", "digest"}
        assert self._preferences() == {
            "Everything@Example.com": {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"},
            "no-tags@example.com": {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"},
            "eu-unsub@example.com": {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"},
            "tagged@example.com": {
                categories["newsletter"]: "OPTED_OUT",
                categories["promo 🎁"]: "OPTED_OUT",
                categories["digest"]: "OPTED_OUT",
            },
        }
        assert run.progress["unsubscribes"]["counts"]["tag_categories"] == 3

    def test_allowlists_change_nothing_and_never_say_who_is_suppressed(self) -> None:
        run = self._run(["bounces", "allowlists"])

        assert run.progress["allowlists"]["imported"] == 0
        assert run.progress["allowlists"]["counts"] == {"addresses": 1, "domains": 1}
        notes = run.progress["allowlists"]["items"][0]["notes"]
        assert not any("both@example.com" in note for note in notes)
        assert any("qa.example.com" in note for note in notes)
        assert "both@example.com" in self._suppressions()

    def test_mailing_lists_make_categories_and_read_only_who_left(self) -> None:
        run = self._run(["mailing_lists"])

        category = MessageCategory.objects.get(team_id=self.team.id, name="Developers")
        assert self._preferences()["Left@example.com"] == {str(category.id): "OPTED_OUT"}
        assert category.public_description == ""
        assert "stays@example.com" not in self._preferences()
        assert MessageCategory.objects.filter(team_id=self.team.id, name="empty@mg.example.com").exists()
        member_calls = [call for call in self.mailgun.calls if call["path"].endswith("/members/pages")]
        assert member_calls and all(call["query"]["subscribed"] == "false" for call in member_calls)
        assert next(call for call in member_calls if "acme" in call["path"])["on_behalf_of"] == "sub-acme"
        assert run.progress["mailing_lists"]["counts"]["members"] == 4

    def test_a_key_a_code_email_sends_under_is_left_to_it(self) -> None:
        TransactionalEmailKey.objects.for_team(self.team.id).create(team=self.team, key="welcome", hog_flow_id=uuid4())

        self._run(["templates"])

        assert not MessageTemplate.objects.filter(team_id=self.team.id, key="welcome").exists()

    def test_a_key_a_code_email_starts_sending_under_during_the_import_is_left_to_it(self) -> None:
        convert = mailgun.convert_version

        def send_starts(version: dict) -> Any:
            TransactionalEmailKey.objects.for_team(self.team.id).get_or_create(
                team=self.team, key="welcome", defaults={"hog_flow_id": uuid4()}
            )
            return convert(version)

        with patch.object(mailgun, "convert_version", send_starts):
            self._run(["templates"], region="us")

        assert not MessageTemplate.objects.filter(team_id=self.team.id, key="welcome").exists()

    def test_templates_keep_their_scope_and_never_send_on_their_own(self) -> None:
        run = self._run(["templates"])

        templates = {row.key: row for row in MessageTemplate.objects.filter(team_id=self.team.id)}
        assert set(templates) >= {"welcome", DOMAIN_WELCOME, EU_WELCOME}
        assert all(row.transactional_hog_flow_id is None for row in templates.values())
        assert templates["welcome"].content["email"]["subject"] == 'Welcome {{ variables.name | join: "," }}'
        assert templates["welcome"].content["email"]["replyTo"] == '{{ "{{" }}help}}@mg.example.com'
        assert (
            templates["welcome"]
            .content["email"]["html"]
            .startswith(
                '<h1>Hello {{ variables.name | join: "," }}</h1>{% if variables.vip != nil and variables.vip != false and variables.vip != 0 and variables.vip.length != 0 or variables.vip != empty %}'
            )
        )
        assert templates["welcome"].content["email"]["design"]["body"]["rows"]
        assert "<p>Hi {% if go_value1" in templates[DOMAIN_WELCOME].content["email"]["html"]
        assert "Hallo" in templates[EU_WELCOME].content["email"]["html"]
        assert not any("Old hello" in row.content["email"]["html"] for row in templates.values())

        items = {item["label"]: item for item in run.progress["templates"]["items"]}
        assert any("Still in Mailgun: v1" in note for note in items["welcome"]["notes"])
        assert not any("convert" in note for note in items["welcome"]["notes"])
        assert any("Go templates" in note for note in items["welcome (mg.example.com)"]["notes"])
        unicode_item = items["reçu 🧾 mensuel (mg.example.com)"]
        assert any("{{lookup a b}}" in note for note in unicode_item["notes"])
        assert any("MJML" in note for note in unicode_item["notes"])
        assert items["empty.template"]["status"] == "skipped"
        assert run.progress["templates"]["counts"]["no_content"] == 1

    def test_every_version_imports_when_asked(self) -> None:
        self._run(["templates"], region="us", template_versions="all")

        old = MessageTemplate.objects.get(team_id=self.team.id, key=WELCOME_V1)
        assert "Old hello" in old.content["email"]["html"]
        assert "Hello" in MessageTemplate.objects.get(team_id=self.team.id, key="welcome").content["email"]["html"]
        list_calls = [call for call in self.mailgun.calls if call["path"].endswith("/templates")]
        assert list_calls and all(call["query"]["limit"] == "10" for call in list_calls)

    def test_a_version_mailgun_lost_skips_only_that_version(self) -> None:
        self.mailgun.failures = [Failure(r"/v4/templates/welcome/versions/v1$", 404)]

        run = self._run(["templates"], region="us", template_versions="all")

        assert not MessageTemplate.objects.filter(team_id=self.team.id, key=WELCOME_V1).exists()
        active = MessageTemplate.objects.get(team_id=self.team.id, key="welcome")
        assert "Hello" in active.content["email"]["html"]
        items = {item["label"]: item for item in run.progress["templates"]["items"]}
        assert any("couldn't find the versions v1" in note for note in items["welcome"]["notes"])

    def test_templates_from_domains_with_similar_names_both_import(self) -> None:
        us = self.mailgun.data["us"]
        welcome = us["domain_templates"]["mg.example.com"][0]
        for index, name in enumerate(("a.b.example.com", "a-b.example.com")):
            us["domains"].append({**us["domains"][0], "name": name, "id": f"similar-{index}"})
            us["domain_templates"][name] = [
                {**welcome, "versions": [{**welcome["versions"][0], "template": f"<p>From {name}</p>"}]}
            ]

        self._run(["templates"], region="us")

        html = {row.key: row.content["email"]["html"] for row in MessageTemplate.objects.filter(team_id=self.team.id)}
        assert html[_domain_welcome("a.b.example.com")] == "<p>From a.b.example.com</p>"
        assert html[_domain_welcome("a-b.example.com")] == "<p>From a-b.example.com</p>"

    def test_every_request_is_a_documented_read_with_basic_auth(self) -> None:
        self._run(region="both")

        assert self.mailgun.undocumented == []
        expected = f"Basic {base64.b64encode(f'api:{FULL_KEY}'.encode()).decode()}"
        assert {call["authorization"] for call in self.mailgun.calls} == {expected}
        subaccount_calls = [call for call in self.mailgun.calls if "acme.example.com" in call["path"]]
        assert subaccount_calls and all(
            call["on_behalf_of"] == "sub-acme" for call in subaccount_calls if call["path"] != "/v4/domains"
        )
        run = ProviderImportRun.objects.for_team(self.team.id).get()
        assert run.status == "completed" and run.temporary_api_key is None

    @parameterized.expand([("us", {"us"}), ("eu", {"eu"}), ("both", {"us", "eu"})])
    def test_the_key_only_goes_to_the_chosen_region(self, region: str, reached: set[str]) -> None:
        self._run(region=region)

        assert {call["region"] for call in self.mailgun.calls} == reached

    def test_a_wrong_host_in_a_paging_link_never_gets_the_key(self) -> None:
        self.mailgun.paging_host = "https://evil.example.com"
        seen: list[str] = []
        original = self._get

        def spy(url: str, **kwargs: Any) -> MagicMock:
            seen.append(url)
            return original(url, **kwargs)

        with patch(f"{CLIENT}.requests.get", spy):
            self._run(["bounces"], region="us")

        assert seen and all(url.startswith(US) for url in seen)
        assert len(self._suppressions()) == 4

    def test_an_account_whose_domains_all_belong_to_subaccounts_can_start(self) -> None:
        us = self.mailgun.data["us"]
        us["domains"] = [domain for domain in us["domains"] if domain.get("subaccount_id")]

        run = self._start(["bounces"], "us")

        assert run.status == "queued"

    def test_the_credential_check_does_not_wait_out_a_spent_rate_limit(self) -> None:
        original = self._get

        def spent(url: str, **kwargs: Any) -> MagicMock:
            response = original(url, **kwargs)
            response.headers = {**response.headers, "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "30000"}
            return response

        with patch(f"{CLIENT}.requests.get", spent):
            self._start(["bounces"], "us")

        self.sleep.assert_not_called()

    def test_a_region_with_no_domains_for_the_key_stops_before_any_run(self) -> None:
        with self.assertRaisesRegex(ImportCredentialsInvalid, "no domains for this key in the US region"):
            self._start(["bounces"], "us", EU_ONLY_KEY)
        with self.assertRaisesRegex(ImportCredentialsInvalid, "in the US or EU region"):
            self._start(ALL_STEPS, "both", EMPTY_KEY)
        assert not ProviderImportRun.objects.for_team(self.team.id).exists()

    def test_both_regions_say_which_one_has_no_domains(self) -> None:
        run = self._run(["bounces", "domains"], region="both", key=EU_ONLY_KEY)

        assert run.status == "completed"
        assert "no domains in the US region" in run.progress["domains"]["warnings"][0]

    @parameterized.expand(
        [
            ("wrong_key", "nope", ALL_STEPS, "rejected this API key"),
            ("analyst_for_suppressions", ANALYST_KEY, ["templates", "bounces"], "can't read bounces"),
        ]
    )
    def test_a_key_with_too_little_access_stops_before_any_run(
        self, _name: str, key: str, steps: list[str], message: str
    ) -> None:
        with self.assertRaisesRegex(ImportCredentialsInvalid, message):
            self._start(steps, "us", key)
        assert not ProviderImportRun.objects.for_team(self.team.id).exists()

    def test_an_analyst_key_can_still_import_what_it_can_read(self) -> None:
        run = self._run(["templates", "domains"], region="us", key=ANALYST_KEY)

        assert run.status == "completed"

    @parameterized.expand(
        [
            ("duration", "2500", 2.5),
            ("past_epoch", "1000000000000", 2.0),
            ("garbage", "soon", 2.0),
            ("too_long", "99999999", 60.0),
            ("retry_after_only", None, 7.0),
        ]
    )
    def test_a_rate_limit_waits_as_mailgun_says(self, _name: str, reset: str | None, expected_wait: float) -> None:
        run = self._start(["bounces"], "us")
        headers = {"X-RateLimit-Reset": reset} if reset else {"Retry-After": "7"}
        self.mailgun.failures = [Failure(r"/bounces$", 429, 1, headers)]

        runs.run_step(self.team.id, run.id, "bounces", attempt=1)

        assert any(call.args == (expected_wait,) for call in self.sleep.call_args_list), self.sleep.call_args_list
        assert "both@example.com" in self._suppressions()

    def test_a_rate_limit_that_never_clears_fails_the_step_without_losing_the_place(self) -> None:
        run = self._start(["bounces"], "us")
        self.mailgun.failures = [Failure(r"news\.example\.com/bounces$", 429, 100)]

        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "bounces", attempt=1)

        run.refresh_from_db()
        assert run.progress["bounces"]["last_error"] == "Mailgun kept asking PostHog to slow down. Import again later."
        assert run.progress["bounces"]["checkpoint"]["name"] == "news.example.com"

    def test_a_failure_on_one_domain_resumes_there_after_a_retry_and_after_a_new_import(self) -> None:
        run = self._start(["bounces"], "us")
        self.mailgun.failures = [Failure(r"news\.example\.com/bounces$", 500, 8)]

        for attempt in (1, 2):
            with self.assertRaises(ImportProviderUnavailable):
                runs.run_step(self.team.id, run.id, "bounces", attempt=attempt)
        runs.finish_run(self.team.id, run.id)
        run.refresh_from_db()
        assert run.status == "failed"
        assert run.temporary_api_key is None
        assert "both@example.com" in self._suppressions()
        assert "josé@example.com" not in self._suppressions()

        calls_before = len(self.mailgun.calls)
        again = self._run(["bounces"], region="us")

        assert again.status == "completed"
        resumed = [
            call["path"]
            for call in self.mailgun.calls[calls_before:]
            if call["path"].endswith("/bounces") and call["query"].get("limit") != "1"
        ]
        assert resumed[0] == "/v3/news.example.com/bounces"
        assert "/v3/mg.example.com/bounces" not in resumed
        assert "josé@example.com" in self._suppressions()

    def test_a_retry_continues_from_the_saved_page_inside_a_domain(self) -> None:
        self.mailgun.data["us"]["bounces"]["mg.example.com"] = [
            {
                "address": f"user{index:04}@example.com",
                "code": "550",
                "error": "x",
                "created_at": "Thu, 11 Dec 2025 01:49:40 UTC",
            }
            for index in range(1500)
        ]
        run = self._start(["bounces"], "us")
        self.mailgun.failures = [Failure(r"/v3/mg\.example\.com/bounces$", 500, 4, only_later_pages=True)]

        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "bounces", attempt=1)
        run.refresh_from_db()
        assert run.progress["bounces"]["processed"] == 1000
        checkpoint = run.progress["bounces"]["checkpoint"]
        assert checkpoint["name"] == "mg.example.com" and checkpoint["after"].startswith("/v3/mg.example.com/bounces?")

        runs.run_step(self.team.id, run.id, "bounces", attempt=2)
        run.refresh_from_db()
        assert run.progress["bounces"]["status"] == "completed"
        assert run.progress["bounces"]["processed"] == 1500 + 3
        assert len(self._suppressions()) == 1500 + 3

    def test_a_passing_server_error_is_retried_inside_the_step(self) -> None:
        self.mailgun.failures = [Failure(r"news\.example\.com/bounces$", 503)]

        run = self._run(["bounces"], region="us")

        assert run.status == "completed"
        assert "josé@example.com" in self._suppressions()

    def test_a_domain_mailgun_lost_is_named_and_the_rest_import(self) -> None:
        self.mailgun.failures = [Failure(r"mg\.example\.com/bounces$", 404, 5)]

        run = self._run(["bounces"], region="us")

        assert run.status == "completed"
        assert run.progress["bounces"]["counts"]["missing_domains"] == 1
        assert "mg.example.com" in run.progress["bounces"]["warnings"][0]
        assert "josé@example.com" in self._suppressions()

    def test_importing_again_keeps_every_change_made_in_posthog(self) -> None:
        first = self._run()
        assert first.status == "completed"

        remove_suppressions(self.team.id, ["both@example.com"], confirm_complaints=False)
        MessageTemplate.objects.filter(team_id=self.team.id, key="welcome").update(name="Edited here")
        MessageTemplate.objects.filter(team_id=self.team.id, key=EU_WELCOME).update(deleted=True)
        MessageCategory.objects.filter(team_id=self.team.id, name="Developers").update(name="Renamed")
        MessageRecipientPreference.objects.filter(team_id=self.team.id, identifier="no-tags@example.com").update(
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_IN"}
        )
        template_count = MessageTemplate.objects.filter(team_id=self.team.id).count()

        second = self._run()

        assert second.status == "completed"
        assert "both@example.com" not in self._suppressions()
        assert MessageTemplate.objects.get(team_id=self.team.id, key="welcome").name == "Edited here"
        assert MessageTemplate.objects.get(team_id=self.team.id, key=EU_WELCOME).deleted is True
        assert MessageTemplate.objects.filter(team_id=self.team.id).count() == template_count
        assert MessageCategory.objects.filter(team_id=self.team.id, name="Renamed").exists()
        assert self._preferences()["no-tags@example.com"] == {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_IN"}
        assert second.progress["templates"]["counts"].get("created", 0) == 0
        assert second.progress["bounces"]["counts"]["bounced"] == 0
        for step in ("unsubscribes", "mailing_lists"):
            assert second.progress[step]["counts"]["opted_out"] == 0
            assert (
                second.progress[step]["counts"]["already_opted_out"] == first.progress[step]["counts"]["opted_out"] > 0
            )

    def test_domains_list_their_records_and_what_breaks(self) -> None:
        run = self._run(["domains"])

        items = {item["label"]: item for item in run.progress["domains"]["items"]}
        assert set(items) == {
            "mg.example.com",
            "news.example.com",
            "sandbox123.mailgun.example.com",
            "acme.example.com",
            "eu.example.com",
        }
        assert any("TXT mx._domainkey.mg.example.com" in note for note in items["mg.example.com"]["notes"])
        assert not any("unsubscribe footer" in note for note in items["mg.example.com"]["notes"])
        assert any("unsubscribe footer" in note for note in items["news.example.com"]["notes"])
        assert any("feedback subdomain" in note for note in items["news.example.com"]["notes"])
        assert any("unverified" in note for note in items["news.example.com"]["notes"])
        assert any("sandbox" in note for note in items["sandbox123.mailgun.example.com"]["notes"])
        assert any("EU" in note for note in items["eu.example.com"]["notes"])
        assert run.progress["domains"]["counts"] == {"needs_setup": 4, "sandbox": 1}

    def test_names_with_slashes_and_unicode_stay_inside_their_path(self) -> None:
        self.mailgun.data["us"]["account_templates"][""].append(
            {
                "name": "a/b?c#d",
                "id": "x",
                "versions": [{"tag": "v/1", "active": True, "headers": {"Subject": "S"}, "template": "<p>x</p>"}],
            }
        )
        self._run(["templates"], region="us", template_versions="all")

        name = quote("a/b?c#d", safe="")
        assert any(call["path"] == f"/v4/templates/{name}" for call in self.mailgun.calls)
        assert MessageTemplate.objects.filter(team_id=self.team.id, name="a/b?c#d").exists()


def _member(address: str, subscribed: bool = True, name: str = "", variables: Any = None) -> dict[str, Any]:
    return {"address": address, "name": name, "vars": variables or {}, "subscribed": subscribed}


class TestMailgunContacts(ClickhouseTestMixin, _MailgunTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.people = PeopleImportRecorder(self)
        self.members = self.mailgun.data["us"]["members"]

    def _run_contacts(self, region: str = "us") -> ProviderImportRun:
        run = self._start(CONTACT_RUN, region)
        with self.captureOnCommitCallbacks(execute=True):
            for step in run.steps:
                runs.run_step(self.team.id, run.id, step, attempt=1)
        run.refresh_from_db()
        return run

    def _lists(self, run: ProviderImportRun) -> dict[str, dict[str, bool]]:
        """By cohort name, each stored person's distinct ID and whether they join the cohort."""
        return {
            Cohort.objects.get(id=plan["cohort_id"]).name or "": {
                person["distinct_id"]: person.get("member", True) for person in self.people.people(plan)
            }
            for plan in run.progress["contacts"]["people_imports"]
        }

    def _properties(self, run: ProviderImportRun) -> dict[str, dict[str, str]]:
        [plan, *_] = run.progress["contacts"]["people_imports"]
        return {person["distinct_id"]: person["properties"] for person in self.people.people(plan)}

    def test_members_become_one_person_each_and_only_subscribed_ones_join_a_cohort(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-stays"], properties={"email": "Stays@Example.com"})
        flush_persons_and_events()
        # More than one page, a member of two lists who left one of them, and names an import may not set.
        self.members["devs@mg.example.com"] += [_member(f"page-{n:03}@example.com") for n in range(150)]
        self.members["devs@mg.example.com"] += [
            _member(
                "jose@example.com",
                name="José 🎉",
                variables='{"plan": "pro", "$ip": "1.2.3.4", "distinct_id": "admin", "": "x", "name": "Other"}',
            ),
            _member("not-an-address"),
        ]
        self.members["acme@acme.example.com"] += [
            _member("JOSE@example.com", subscribed=False, variables={"plan": "free", "city": "Zürich"})
        ]

        run = self._run_contacts()

        lists = self._lists(run)
        everyone, developers = (
            lists["Mailgun list members (US, sandbox123.mailgun.example.com)"],
            lists["Developers (from Mailgun)"],
        )
        assert len(everyone) == 155 and len(developers) == 152
        assert {person for person, member in everyone.items() if not member} == {
            "Left@example.com",
            "left-too@example.com",
            "sub-left@example.com",
        }
        assert {"user-stays", "jose@example.com", "page-149@example.com"} <= set(developers)
        # No one is subscribed to either of the other lists, and neither has a cohort from an earlier import.
        assert set(lists) == {"Mailgun list members (US, sandbox123.mailgun.example.com)", "Developers (from Mailgun)"}
        properties = self._properties(run)
        assert properties["jose@example.com"] == {
            "email": "jose@example.com",
            "name": "José 🎉",
            "plan": "pro",
            "city": "Zürich",
        }
        assert properties["user-stays"] == {"email": "stays@example.com", "name": "Stays", "age": "26"}
        assert run.progress["contacts"]["counts"]["invalid_skipped"] == 1
        notes = [note for item in run.progress["mailing_lists"]["items"] for note in item["notes"]]
        assert not any("created no people" in note for note in notes)

    def test_importing_again_takes_out_who_unsubscribed_or_left_and_opts_them_out(self) -> None:
        self.members["devs@mg.example.com"].append(_member("leaves@example.com"))
        first = self._run_contacts()
        runs.finish_run(self.team.id, first.id)
        cohorts = {plan["cohort_id"] for plan in first.progress["contacts"]["people_imports"]}
        run = self._start(CONTACT_RUN, "us")
        with self.captureOnCommitCallbacks(execute=True):
            for step in CONTACT_RUN[:4]:
                runs.run_step(self.team.id, run.id, step, attempt=1)
            # Unsubscribes after the mailing list step read who left.
            self.members["devs@mg.example.com"] = [_member("Stays@example.com", subscribed=False)]
            self.mailgun.data["us"]["lists"][""][0]["members_count"] = 1
            for step in CONTACT_STEPS:
                runs.run_step(self.team.id, run.id, step, attempt=1)
        run.refresh_from_db()

        assert {plan["cohort_id"] for plan in run.progress["contacts"]["people_imports"]} == cohorts
        lists = self._lists(run)
        assert lists["Developers (from Mailgun)"] == {}
        assert lists["Mailgun list members (US, sandbox123.mailgun.example.com)"] == {
            "Stays@example.com": False,
            "sub-left@example.com": False,
        }
        category = MessageCategory.objects.get(team_id=self.team.id, name="Developers")
        assert self._preferences()["Stays@example.com"] == {str(category.id): "OPTED_OUT"}

    def test_each_region_keeps_its_own_cohorts(self) -> None:
        devs = {**self.mailgun.data["us"]["lists"][""][0], "members_count": 1}
        self.mailgun.data["eu"]["lists"][""] = [devs]
        self.mailgun.data["eu"]["members"][devs["address"]] = [_member("eu@example.com")]
        cohorts = {}
        for region in ("us", "eu", "both"):
            run = self._run_contacts(region)
            runs.finish_run(self.team.id, run.id)
            cohorts[region] = {plan["cohort_id"] for plan in run.progress["contacts"]["people_imports"]}

        assert len(cohorts["us"]) == len(cohorts["eu"]) == 2
        assert cohorts["us"].isdisjoint(cohorts["eu"])
        assert cohorts["both"] == cohorts["us"] | cohorts["eu"]

    def test_new_and_deleted_domains_keep_the_accounts_cohort(self) -> None:
        domains = self.mailgun.data["us"]["domains"]
        domains[0]["created_at"] = "Mon, 01 Jan 2001 15:04:05 UTC"
        first = self._run_contacts()
        cohorts = self._lists(first).keys()
        runs.finish_run(self.team.id, first.id)
        domains += [
            {"name": "a-newer.example.com", "created_at": "Tue, 02 Jan 2001 15:04:05 UTC"},
            {"name": "a-sub.example.com", "created_at": "Fri, 01 Jan 1999 15:04:05 UTC", "subaccount_id": "sub-acme"},
        ]
        del domains[0]

        assert self._lists(self._run_contacts()).keys() == cohorts

    def test_a_member_deleted_while_their_list_is_read_does_not_stop_the_import(self) -> None:
        devs = self.mailgun.data["us"]["lists"][""][0]
        run = self._start(CONTACT_RUN, "us")
        for step in CONTACT_RUN[:4]:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        handle = self.mailgun.handle

        def delete_then_handle(base_url: str, path: str, *args: Any) -> Any:
            if path.endswith("/members/pages") and "devs" in path and len(self.members[devs["address"]]) == 3:
                self.members[devs["address"]].pop()
                self.mailgun.data["us"]["lists"][""][0] = {**devs, "members_count": 2}
            return handle(base_url, path, *args)

        with patch.object(self.mailgun, "handle", delete_then_handle):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert self.people.stored

    def test_another_account_keeps_the_first_accounts_cohort(self) -> None:
        first = self._run_contacts()
        runs.finish_run(self.team.id, first.id)
        us = self.mailgun.data["us"]
        us["domains"] = [{**us["domains"][0], "name": "mail.example.org"}]
        us["lists"] = {"": [{"address": "news@mail.example.org", "name": "News", "members_count": 1}]}
        us["members"] = {"news@mail.example.org": [_member("other@example.com")]}

        second = self._run_contacts()

        assert self._lists(second)["Mailgun list members (US, mail.example.org)"] == {"other@example.com": True}
        cohorts = [
            {plan["cohort_id"] for plan in run.progress["contacts"]["people_imports"]} for run in (first, second)
        ]
        assert cohorts[0].isdisjoint(cohorts[1])

    def test_both_regions_send_each_person_once_and_keep_the_cohorts_apart(self) -> None:
        self.mailgun.data["eu"]["lists"][""] = [{"address": "news@eu.example.com", "name": "EU news"}]
        self.mailgun.data["eu"]["members"]["news@eu.example.com"] = [
            _member("eu@example.com"),
            _member("stays@example.com", subscribed=False),
        ]

        run = self._run_contacts("both")

        joined = {name: {p for p, member in people.items() if member} for name, people in self._lists(run).items()}
        assert joined["Mailgun list members (US, sandbox123.mailgun.example.com)"] == {"stays@example.com"}
        assert (
            joined["Mailgun list members (EU, eu.example.com)"]
            == joined["EU news (from Mailgun)"]
            == {"eu@example.com"}
        )
        sends = [plan["send_events"] for plan in run.progress["contacts"]["people_imports"]]
        assert sends.count(True) == 1

    @parameterized.expand(
        [
            ("later_page_fails", Failure(r"devs%40mg.*/members/pages$", 500, 20, only_later_pages=True)),
            ("list_not_found", Failure(r"devs%40mg.*/members/pages$", 404, 20)),
        ]
    )
    def test_a_read_that_fails_changes_no_cohort(self, _name: str, failure: Failure) -> None:
        self.members["devs@mg.example.com"] += [_member(f"page-{n:03}@example.com") for n in range(150)]
        run = self._start(CONTACT_RUN, "us")
        for step in CONTACT_RUN[:4]:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        self.mailgun.failures = [failure]

        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        run.refresh_from_db()
        assert not run.progress["contacts"].get("people_imports") and self.people.stored == {}

    @parameterized.expand(
        [
            ("empty_answer", "members/pages", None),
            ("full_page_without_a_next", "members/pages", 100),
            ("too_few_members", "members/pages", 20),
            ("too_few_members_and_no_count", "members/pages", 20),
            ("lists_without_a_next", "lists/pages", 100),
            ("unsubscribes_without_a_next", "/unsubscribes", 1000),
            ("domains_before_their_total", "/v4/domains", None),
        ]
    )
    def test_a_cut_short_read_changes_no_cohort(self, name: str, cut_path: str, kept: int | None) -> None:
        self.mailgun.data["us"]["lists"][""] += [
            {"address": f"list-{n:03}@mg.example.com", "name": "", "members_count": 0} for n in range(120)
        ]
        self.mailgun.data["us"]["lists"][""][0]["members_count"] = 153
        self.mailgun.data["us"]["unsubscribes"]["mg.example.com"] += [
            {"address": f"unsub-{n}@example.com", "tags": ["*"]} for n in range(1100)
        ]
        self.members["devs@mg.example.com"] += [_member(f"page-{n:03}@example.com") for n in range(150)]
        handle = self.mailgun.handle

        def cut(base_url: str, path: str, query: dict, *args: Any) -> Any:
            status, body, headers = handle(base_url, path, query, *args)
            cut = "devs" in path or "members" not in path
            if path.endswith(cut_path) and cut and "subscribed" not in query and query.get("limit") != "1":
                body = {**body, "items": body["items"][:kept] if kept else None, "paging": {}}
            if name == "too_few_members_and_no_count" and path.endswith("/lists/devs%40mg.example.com"):
                body = {}
            return status, body, headers

        with patch.object(self.mailgun, "handle", cut), self.assertRaises(ImportProviderUnavailable):
            self._run_contacts()

        assert self.people.stored == {}

    @parameterized.expand(
        [
            ("not_found", 404, ("", "sub-acme"), True),
            ("not_found_in_a_subaccounts_account", 404, ("sub-acme",), True),
            ("not_found_without_subaccounts", 404, ("",), False),
            ("refused", 403, ("", "sub-acme"), True),
            ("refused_to_a_subaccounts_own_key", 403, ("sub-acme",), False),
            ("refused_without_subaccounts", 403, ("",), False),
            ("a_plan_without_subaccounts", 400, ("",), False),
            ("bad_request", 400, ("", "sub-acme"), True),
        ]
    )
    def test_subaccounts_mailgun_does_not_list_stop_contacts_only_when_there_are_some(
        self, _name: str, status: int, owners: tuple[str, ...], stops: bool
    ) -> None:
        us = self.mailgun.data["us"]
        us["domains"] = [domain for domain in us["domains"] if (domain.get("subaccount_id") or "") in owners]
        run = self._start(CONTACT_RUN, "us")
        for step in CONTACT_RUN[:4]:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        self.mailgun.failures = [Failure(r"/subaccounts$", status, 20)]

        if stops:
            with self.assertRaises(ImportProviderUnavailable):
                runs.run_step(self.team.id, run.id, "contacts", attempt=1)
        else:
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert bool(self.people.stored) is not stops

    @parameterized.expand([("its_own_key", 403, "subaccount"), ("its_accounts_key", 200, "subaccounts")])
    def test_a_region_of_one_subaccount_has_a_cohort_per_kind_of_key(self, _name: str, status: int, kind: str) -> None:
        us = self.mailgun.data["us"]
        us["domains"] = [domain for domain in us["domains"] if domain.get("subaccount_id")]
        run = self._start(CONTACT_RUN, "us")
        for step in CONTACT_RUN[:4]:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        if status != 200:
            self.mailgun.failures = [Failure(r"/subaccounts$", status, 20)]
        runs.run_step(self.team.id, run.id, "contacts", attempt=1)
        run.refresh_from_db()

        assert f"Mailgun list members (US, {us['domains'][0]['name']}, {kind})" in self._lists(run)

    def test_a_subaccount_list_that_ends_before_its_total_stops_contacts(self) -> None:
        run = self._start(CONTACT_RUN, "us")
        for step in CONTACT_RUN[:4]:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        handle = self.mailgun.handle

        def cut(base_url: str, path: str, *args: Any) -> Any:
            status, body, headers = handle(base_url, path, *args)
            if path.endswith("/subaccounts"):
                body = {**body, "subaccounts": [], "total": 1}
            return status, body, headers

        with patch.object(self.mailgun, "handle", cut), self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert self.people.stored == {}

    def test_contacts_never_continue_the_opt_outs_of_a_failed_run(self) -> None:
        self.mailgun.failures = [Failure(r"news\.example\.com/unsubscribes$", 500, 20)]
        failed = self._start(CONTACT_RUN, "us")
        with self.assertRaises(ImportProviderUnavailable):
            for step in failed.steps:
                runs.run_step(self.team.id, failed.id, step, attempt=1)
        runs.finish_run(self.team.id, failed.id)
        self.mailgun.failures = []
        # Unsubscribes from a domain the failed run already read.
        self.mailgun.data["us"]["unsubscribes"]["mg.example.com"].append(
            {"address": "stays@example.com", "tags": ["*"]}
        )

        self._run_contacts()

        assert self._preferences()["stays@example.com"][ALL_MESSAGE_PREFERENCE_CATEGORY_ID] == "OPTED_OUT"

    def test_contacts_wait_while_a_domains_unsubscribes_cannot_be_read(self) -> None:
        self.mailgun.failures = [Failure(r"mg\.example\.com/unsubscribes$", 404, 20)]
        run = self._start(CONTACT_RUN, "us")

        for step in CONTACT_RUN[:4]:
            if step == "unsubscribes":
                # The start checks that the key can read unsubscribes, and a missing domain passes that check.
                with self.assertRaises(ImportProviderUnavailable):
                    runs.run_step(self.team.id, run.id, step, attempt=1)
            else:
                runs.run_step(self.team.id, run.id, step, attempt=1)

        with self.assertRaises(ImportStepBlocked):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)
        assert self.people.stored == {}


class TestMailgunTemplateKeys(SimpleTestCase):
    def test_long_keys_that_differ_only_at_the_end_stay_apart(self) -> None:
        target = _Target(region=MailgunRegion.US, owner="", name="d" * 200, path="/v3/x/templates")
        tags = ["v" * 100 + "a", "v" * 100 + "b"]

        keys = [_template_key(target, "n" * 150, tag) for tag in tags]

        assert keys[0] != keys[1]
        assert all(len(key) <= TEMPLATE_KEY_MAX_LENGTH for key in keys)

    @parameterized.expand(
        [
            ("region", (MailgunRegion.US, "", "eu-welcome", None), (MailgunRegion.EU, "", "welcome", None)),
            ("version", (MailgunRegion.US, "", "receipt-version-v1", None), (MailgunRegion.US, "", "receipt", "v1")),
            (
                "domain",
                (MailgunRegion.US, "", "{domain_key}", None),
                (MailgunRegion.US, "mg.example.com", "welcome", None),
            ),
        ]
    )
    def test_names_that_read_like_another_templates_scope_stay_apart(
        self, _name: str, first: tuple, second: tuple
    ) -> None:
        keys = [
            _template_key(
                _Target(region=region, owner="", name=domain, path="/v4/templates"),
                name.format(domain_key=DOMAIN_WELCOME),
                version,
            )
            for region, domain, name, version in (first, second)
        ]

        assert keys[0] != keys[1]


class TestImportedSender(SimpleTestCase):
    def test_a_sender_name_with_liquid_stays_text_when_the_from_header_has_no_name(self) -> None:
        sender = SimpleNamespace(
            id=7, config={"email": "hello@example.com", "name": "{{ variables.reset_token }}", "verified": True}
        )
        email: dict[str, Any] = {}

        apply_sender(email, "", "hello@example.com", {"hello@example.com": sender})

        assert email["from"]["name"] == literal_liquid("{{ variables.reset_token }}")
        assert email["from"]["name"] != "{{ variables.reset_token }}"


class TestMailgunSettings(SimpleTestCase):
    @parameterized.expand(
        [
            ("region_missing", {}, "Choose a value for Mailgun region"),
            ("region_wrong", {"region": "mars"}, "isn't a valid value"),
            ("unknown_setting", {"region": "us", "color": "red"}, "no setting named color"),
            ("versions_wrong", {"region": "us", "template_versions": "some"}, "isn't a valid value"),
        ]
    )
    def test_settings_are_checked_before_the_key_goes_anywhere(self, _name: str, settings: dict, message: str) -> None:
        with patch(f"{CLIENT}.requests.get") as get, self.assertRaisesRegex(runs.InvalidImportSettings, message):
            runs.start_run(1, "mailgun", ["bounces"], FULL_KEY, None, settings)
        get.assert_not_called()
