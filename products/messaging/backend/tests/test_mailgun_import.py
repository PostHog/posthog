import json
import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
)
from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.provider_import_run import ProviderImportRun
from products.messaging.backend.provider_imports import runs
from products.messaging.backend.provider_imports.base import ImportCredentialsInvalid, ImportProviderUnavailable
from products.messaging.backend.provider_imports.mailgun import MailgunImportProvider
from products.messaging.backend.provider_imports.mailgun_templates import convert_text, convert_version
from products.messaging.backend.services.suppression import remove_suppressions
from products.messaging.backend.tests.fake_mailgun import (
    ANALYST_KEY,
    EMPTY_KEY,
    EU_ONLY_KEY,
    FULL_KEY,
    Failure,
    FakeMailgun,
    split_url,
)

US = "https://api.mailgun.net"
EU = "https://api.eu.mailgun.net"
ALL_STEPS = [spec.key for spec in MailgunImportProvider.steps]
RENDER_CASES = json.loads((Path(__file__).parent / "fixtures" / "mailgun_template_renders.json").read_text())
CLIENT = "products.messaging.backend.services.mailgun_client"


class TestMailgunImport(BaseTest):
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
        assert rows["both@example.com"].source == SuppressionSource.BOUNCE
        assert rows["both@example.com"].hard_bounced_at is not None
        assert rows["both@example.com"].last_bounce_diagnostic == "550 User unknown"
        assert "angry@example.com" not in rows
        assert run.progress["bounces"]["counts"]["bounced"] == 4

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

    def test_allowlists_change_nothing_and_name_what_is_also_suppressed(self) -> None:
        run = self._run(["bounces", "allowlists"])

        assert run.progress["allowlists"]["imported"] == 0
        assert run.progress["allowlists"]["counts"] == {"addresses": 1, "domains": 1, "also_suppressed": 1}
        notes = run.progress["allowlists"]["items"][0]["notes"]
        assert any("both@example.com" in note for note in notes)
        assert any("qa.example.com" in note for note in notes)
        assert "both@example.com" in self._suppressions()

    def test_mailing_lists_make_categories_and_read_only_who_left(self) -> None:
        run = self._run(["mailing_lists"])

        category = MessageCategory.objects.get(team_id=self.team.id, name="Developers")
        assert self._preferences()["Left@example.com"] == {str(category.id): "OPTED_OUT"}
        assert "stays@example.com" not in self._preferences()
        assert MessageCategory.objects.filter(team_id=self.team.id, name="empty@mg.example.com").exists()
        member_calls = [call for call in self.mailgun.calls if call["path"].endswith("/members/pages")]
        assert member_calls and all(call["query"]["subscribed"] == "false" for call in member_calls)
        assert next(call for call in member_calls if "acme" in call["path"])["on_behalf_of"] == "sub-acme"
        assert run.progress["mailing_lists"]["counts"]["members"] == 4

    def test_templates_keep_their_scope_and_never_send_on_their_own(self) -> None:
        run = self._run(["templates"])

        templates = {row.key: row for row in MessageTemplate.objects.filter(team_id=self.team.id)}
        assert set(templates) >= {"welcome", "mg-example-com-welcome", "eu-welcome"}
        assert all(row.transactional_hog_flow_id is None for row in templates.values())
        assert templates["welcome"].content["email"]["subject"] == "Welcome {{ variables.name }}"
        assert templates["welcome"].content["email"]["replyTo"] == "help@mg.example.com"
        assert "{{ variables.city | raw }}" in templates["welcome"].content["email"]["html"]
        assert "{{ unsubscribe_url }}" in templates["welcome"].content["email"]["html"]
        assert "Hi {{ variables.Name }}" in templates["mg-example-com-welcome"].content["email"]["html"]
        assert "Hallo" in templates["eu-welcome"].content["email"]["html"]
        assert not any("Old hello" in row.content["email"]["html"] for row in templates.values())

        items = {item["label"]: item for item in run.progress["templates"]["items"]}
        assert any("Still in Mailgun: v1" in note for note in items["welcome"]["notes"])
        assert any("Go templates" in note for note in items["welcome (mg.example.com)"]["notes"])
        unicode_item = items["reçu 🧾 mensuel (mg.example.com)"]
        assert any("{{lookup a b}}" in note for note in unicode_item["notes"])
        assert any("MJML" in note for note in unicode_item["notes"])
        assert items["empty.template"]["status"] == "skipped"
        assert run.progress["templates"]["counts"]["no_content"] == 1

    def test_every_version_imports_when_asked(self) -> None:
        self._run(["templates"], region="us", template_versions="all")

        old = MessageTemplate.objects.get(team_id=self.team.id, key="welcome-version-v1")
        assert "Old hello" in old.content["email"]["html"]
        assert "Hello" in MessageTemplate.objects.get(team_id=self.team.id, key="welcome").content["email"]["html"]

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
        ]
    )
    def test_a_rate_limit_waits_as_mailgun_says(self, _name: str, reset: str, expected_wait: float) -> None:
        run = self._start(["bounces"], "us")
        self.mailgun.failures = [Failure(r"/bounces$", 429, 1, {"X-RateLimit-Reset": reset})]

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
        self.mailgun.failures = [Failure(r"news\.example\.com/bounces$", 500, 2)]

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
        self.mailgun.failures = [Failure(r"/v3/mg\.example\.com/bounces$", 500, only_later_pages=True)]

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
        MessageTemplate.objects.filter(team_id=self.team.id, key="eu-welcome").update(deleted=True)
        MessageCategory.objects.filter(team_id=self.team.id, name="Developers").update(name="Renamed")
        MessageRecipientPreference.objects.filter(team_id=self.team.id, identifier="no-tags@example.com").update(
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_IN"}
        )
        template_count = MessageTemplate.objects.filter(team_id=self.team.id).count()

        second = self._run()

        assert second.status == "completed"
        assert "both@example.com" not in self._suppressions()
        assert MessageTemplate.objects.get(team_id=self.team.id, key="welcome").name == "Edited here"
        assert MessageTemplate.objects.get(team_id=self.team.id, key="eu-welcome").deleted is True
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


class TestMailgunTemplateConversion(SimpleTestCase):
    @parameterized.expand([(case["name"], case) for case in RENDER_CASES])
    def test_converted_templates_match_the_rendered_fixture(self, _name: str, case: dict) -> None:
        assert convert_text(case["template"], engine=case["engine"]).text == case["liquid"]

    @parameterized.expand(
        [
            ("helper_with_arguments", "{{lookup a b}}", "{% raw %}{{lookup a b}}{% endraw %}"),
            ("partial", "{{> footer}}", "{% raw %}{{> footer}}{% endraw %}"),
            (
                "subexpression_keeps_body",
                "{{#if (eq a b)}}x{{/if}}",
                "{% raw %}{{#if (eq a b)}}{% endraw %}x{% raw %}{{/if}}{% endraw %}",
            ),
            ("stray_closer", "x{{/if}}", "x{% raw %}{{/if}}{% endraw %}"),
            ("stray_else", "x{{else}}", "x{% raw %}{{else}}{% endraw %}"),
            ("unclosed_opening", "a {{ b", 'a {{ "{{" }} b'),
            ("endraw_inside", "{{foo endraw bar}}", '{{ "{{" }}foo endraw bar}}'),
            (
                "unclosed_block_is_closed",
                "{{#if a}}x",
                "{% if variables.a and variables.a != empty and variables.a != 0 %}x{% endif %}",
            ),
        ]
    )
    def test_what_cannot_convert_stays_text_that_liquid_can_parse(self, _name: str, source: str, expected: str) -> None:
        assert convert_text(source).text == expected

    @parameterized.expand(
        [
            ("fixed_html", "%recipient_email%", True, "{{ variables.recipient_email | raw }}"),
            ("custom_html", "%recipient.first-name%", True, "{{ variables.first-name | raw }}"),
            ("custom_with_space_stays", "%recipient.a b%", True, "%recipient.a b%"),
            ("custom_text", "%recipient.city%", False, "{{ variables.city }}"),
            ("dotted_key_is_one_name", "%recipient.a.b%", True, '{{ variables["a.b"] | raw }}'),
            ("unsubscribe", 'href="%unsubscribe_url%"', True, 'href="{{ unsubscribe_url }}"'),
            ("percent_signs_alone", "100% of 50%", True, "100% of 50%"),
            ("unsubscribe_email_stays", "%unsubscribe_email%", True, "%unsubscribe_email%"),
            ("triple_in_subject_has_no_raw", "{{{x}}}", False, "{{ variables.x }}"),
        ]
    )
    def test_mailgun_variables(self, _name: str, source: str, is_html: bool, expected: str) -> None:
        assert convert_text(source, is_html=is_html).text == expected

    @parameterized.expand(
        [
            ("no_subject", {"template": "x"}, "no subject"),
            ("variable_subject", {"template": "x", "headers": {"Subject": "{{a}}"}}, "subject uses variables"),
            ("tag_unsubscribe", {"template": "%tag_unsubscribe_url%"}, "message category"),
            ("list_unsubscribe", {"template": "%mailing_list_unsubscribe_url%"}, "imported from the list"),
            ("unknown_engine", {"template": "x", "engine": "mustache"}, "lists the engine mustache"),
            ("unclosed", {"template": "{{#if a}}x"}, "never closed"),
        ]
    )
    def test_notes_name_what_to_review(self, _name: str, version: dict, expected: str) -> None:
        assert any(expected in note for note in convert_version(version).notes)

    def test_a_blank_engine_with_go_syntax_reads_as_go(self) -> None:
        assert "{{ variables.Name }}" in convert_version({"engine": "", "template": "{{.Name}}"}).html

    def test_unclosed_braces_scan_in_linear_time(self) -> None:
        assert convert_text("{{ " * 20000).text.count('{{ "{{" }}') == 20000
