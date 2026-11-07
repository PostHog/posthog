import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.integrations import IntegrationManager

from products.messaging.backend.models.email_hard_bounce import EmailHardBounce
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
from products.messaging.backend.provider_imports.sendgrid import SendGridImportProvider, missing_scopes
from products.messaging.backend.provider_imports.sendgrid_templates import convert_version, plain_text_from_html
from products.messaging.backend.services.sendgrid_client import SendGridClient
from products.messaging.backend.services.suppression import remove_suppressions
from products.messaging.backend.tests.fake_sendgrid import (
    EMPTY_ACCOUNT_KEY,
    EU_KEY,
    FULL_KEY,
    NARROW_KEY,
    NO_SCOPE_KEY,
    SECOND_ACCOUNT_KEY,
    FakeSendGridServer,
    FakeSendGridState,
    _Handler,
)

ALL_STEPS = [spec.key for spec in SendGridImportProvider.steps]
RENDERS = json.loads((Path(__file__).parent / "fixtures" / "sendgrid_template_renders.json").read_text())
_CLIENT = "products.messaging.backend.services.sendgrid_client"


class TestSendGridImport(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.state = FakeSendGridState()
        self.global_server = FakeSendGridServer(self.state, "global")
        self.eu_server = FakeSendGridServer(self.state, "eu")
        self.global_server.start()
        self.eu_server.start()
        self.addCleanup(self.global_server.shutdown)
        self.addCleanup(self.eu_server.shutdown)
        settings_override = override_settings(
            MESSAGING_SENDGRID_API_URL=self.global_server.url, MESSAGING_SENDGRID_EU_API_URL=self.eu_server.url
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.sleep = self._patch(f"{_CLIENT}.time.sleep")
        self._patch(f"{_CLIENT}.REQUESTS_PER_SECOND", 100000)
        self.start_workflow = self._patch(
            "products.messaging.backend.provider_imports.runs.start_provider_import_workflow"
        )

    def _patch(self, target: str, *replacement: Any) -> Any:
        patcher = patch(target, *replacement)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def _start(self, steps: list[str] | None = None, api_key: str = FULL_KEY) -> ProviderImportRun:
        return runs.start_run(self.team.id, "sendgrid", steps or ALL_STEPS, api_key, self.user.id)

    def _run(self, steps: list[str] | None = None, api_key: str = FULL_KEY) -> ProviderImportRun:
        run = self._start(steps, api_key)
        for step in run.steps:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        runs.finish_run(self.team.id, run.id)
        run.refresh_from_db()
        return run

    def _paths(self) -> list[str]:
        return [request["path"] for request in self.state.requests]

    def _suppressions(self) -> dict[str, MessageSuppression]:
        rows = MessageSuppression.objects.for_team(self.team.id).filter(deleted=False)
        return {row.identifier: row for row in rows}

    def _preferences(self) -> dict[str, dict[str, str]]:
        rows = MessageRecipientPreference.objects.filter(team_id=self.team.id)
        return {row.identifier: row.preferences for row in rows}

    def test_lists_land_on_the_blocking_rule_of_their_kind(self) -> None:
        run = self._run(["suppressions"])

        rows = self._suppressions()
        assert {identifier: row.source for identifier, row in rows.items()} == {
            "gone@example.com": SuppressionSource.BOUNCE,
            "mixed.case@example.com": SuppressionSource.BOUNCE,
            "both@example.com": SuppressionSource.BOUNCE,
            "jürgen+🦔@example.com": SuppressionSource.BOUNCE,
            "invalid@example.com": SuppressionSource.BOUNCE,
            "complainer@example.com": SuppressionSource.COMPLAINT,
        }
        assert rows["gone@example.com"].hard_bounced_at is not None
        assert rows["gone@example.com"].last_bounce_diagnostic == "550 5.1.1 The email account does not exist"
        assert rows["invalid@example.com"].hard_bounced_at is not None
        assert rows["complainer@example.com"].hard_bounced_at is None
        assert "blocked@example.com" not in rows
        assert "/v3/suppression/blocks" not in self._paths()
        assert EmailHardBounce.objects.count() == 0
        assert run.progress["suppressions"]["counts"] == {
            "bounced": 4,
            "invalid_addresses": 1,
            "complained": 1,
            "already_present": 1,
            "invalid": 1,
        }

    def test_unsubscribes_become_opt_outs_without_creating_people(self) -> None:
        run = self._run(["global_unsubscribes", "group_unsubscribes"])

        category_ids = {
            row.key: str(row.id) for row in MessageCategory.objects.filter(team_id=self.team.id, deleted=False)
        }
        assert set(category_ids) == {"sendgrid_101", "sendgrid_102", "sendgrid_103"}
        assert self._preferences() == {
            "unsubscribed@example.com": {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"},
            "Grüße.Unsub@example.com": {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"},
            "left-updates@example.com": {
                category_ids["sendgrid_101"]: "OPTED_OUT",
                category_ids["sendgrid_102"]: "OPTED_OUT",
            },
            "Björk.Group@example.com": {category_ids["sendgrid_101"]: "OPTED_OUT"},
        }
        assert run.status == "completed"

    def test_group_category_comes_across_with_its_name(self) -> None:
        run = self._run(["suppression_groups"])

        names = set(MessageCategory.objects.filter(team_id=self.team.id).values_list("name", flat=True))
        assert names == {"Product updates", "Événements 🎉", "Empty group"}
        assert any("default group" in warning for warning in run.progress["suppression_groups"]["warnings"])

    def test_templates_import_the_active_version_and_never_send(self) -> None:
        run = self._run(["templates"])

        templates = {row.key: row for row in MessageTemplate.objects.filter(team_id=self.team.id)}
        assert set(templates) == {
            "d-1111111111111111111111111111aaaa",
            "d-2222222222222222222222222222bbbb",
            "33333333-3333-4333-8333-333333333333",
            "d-4444444444444444444444444444dddd",
        }
        receipt = templates["d-1111111111111111111111111111aaaa"]
        email = receipt.content["email"]
        assert receipt.transactional_hog_flow_id is None
        assert receipt.content["templating"] == "liquid"
        assert email["subject"] == "Your order {{ variables.order.id }}"
        assert "Old" not in email["html"]
        assert "{{ unsubscribe_url }}" in email["html"]
        assert "{{ variables.preheader }}" in email["html"]
        assert "{{ variables.first_name }}" in email["text"] or "default" in email["text"]
        assert '"first_name": "Ada"' in receipt.description
        assert templates["d-4444444444444444444444444444dddd"].content["email"]["html"] == "<p>Newest</p>"

        items = {item["label"]: item for item in run.progress["templates"]["items"]}
        assert any("Old draft" in note for note in items["Order receipt"]["notes"])
        assert any("{{customHelper name}}" in note for note in items["Přivítání 🦔"]["notes"])
        assert any("Sender_Name" in note for note in items["Přivítání 🦔"]["notes"])
        assert any("design editor" in note for note in items["Přivítání 🦔"]["notes"])
        assert any("no version" in note for note in items["Empty template"]["notes"])
        assert run.progress["templates"]["counts"]["no_version"] == 1

    def test_designs_and_single_sends_become_templates_with_notes(self) -> None:
        IntegrationManager.email.credentials.create(
            self.team.id,
            external_id="hello@example.com",
            config={"email": "hello@example.com", "domain": "example.com", "verified": True, "name": "Acme"},
            sensitive_config={},
            created_by_id=self.user.id,
        )
        run = self._run(["suppression_groups", "designs", "single_sends"])

        templates = {row.name: row for row in MessageTemplate.objects.filter(team_id=self.team.id)}
        assert templates["Newsletter design"].key == "sendgrid-design-eeeeeeee-0000-4000-8000-000000000001"
        scheduled = templates["November news"]
        assert scheduled.content["email"]["from"]["email"] == "hello@example.com"
        assert str(scheduled.message_category_id) == str(
            MessageCategory.objects.get(team_id=self.team.id, key="sendgrid_101").id
        )
        assert templates["From a design"].content["email"]["html"] == "<p>News</p>{{ unsubscribe_url }}"
        items = {item["label"]: item for item in run.progress["single_sends"]["items"]}
        assert any("still scheduled" in note for note in items["November news"]["notes"])
        assert any("first_name" in note for note in items["November news"]["notes"])
        assert any("A/B test" in note for note in items["From a design"]["notes"])
        assert any("example.com/leave" in note for note in items["From a design"]["notes"])

    def test_senders_domains_and_lists_are_listed_with_what_to_do(self) -> None:
        run = self._run(["lists", "senders", "domains"])

        assert run.progress["lists"]["counts"] == {"lists": 2, "contacts": 1234}
        assert [item["label"] for item in run.progress["lists"]["items"]] == ["Newsletter", "Bêta testeurs"]
        senders = {item["label"]: item for item in run.progress["senders"]["items"]}
        assert any("hasn't verified" in note for note in senders["new@example.org"]["notes"])
        domains = {item["label"]: item for item in run.progress["domains"]["items"]}
        assert any("s1._domainkey.example.com" in note for note in domains["example.com"]["notes"])
        assert any("feedback subdomain" in note for note in domains["mail.example.org"]["notes"])
        assert run.progress["domains"]["imported"] == 0

    def test_something_deleted_mid_import_does_not_fail_the_step(self) -> None:
        self.state.account["single_sends"][1]["email_config"]["design_id"] = "deleted-design"
        with patch.object(_Handler, "_version", return_value=(404, {"errors": [{"message": "not found"}]}, {})):
            run = self._run(["templates", "single_sends"])

        assert run.status == "completed"
        assert run.progress["templates"]["counts"]["no_version"] == 5
        assert "From a design" in MessageTemplate.objects.filter(team_id=self.team.id).values_list("name", flat=True)

    def test_requests_match_the_documented_endpoints_and_headers(self) -> None:
        self._run()

        for request in self.state.requests:
            assert request["authorization"] == f"Bearer {FULL_KEY}"
            assert request["accept"] == "application/json"
            assert request["region"] == "global"
        templates = next(r for r in self.state.requests if r["path"] == "/v3/templates")
        assert templates["query"]["generations"] == "legacy,dynamic"
        assert templates["query"]["page_size"] == "200"
        bounces = next(r for r in self.state.requests if r["path"] == "/v3/suppression/bounces")
        assert bounces["query"]["limit"] == "500"
        assert "end_time" in bounces["query"]

    @parameterized.expand(
        [
            ("wrong_key", "SG.nope", ["suppressions"], "SendGrid rejected this API key"),
            ("too_few_scopes", NARROW_KEY, ["suppressions", "templates"], "templates.read, templates.versions.read"),
            ("no_scopes", NO_SCOPE_KEY, ["domains"], "whitelabel.read"),
        ]
    )
    def test_a_key_that_cannot_read_stops_before_any_run(
        self, _name: str, key: str, steps: list[str], message: str
    ) -> None:
        with self.assertRaisesRegex(ImportCredentialsInvalid, message):
            self._start(steps, key)

        assert not ProviderImportRun.objects.for_team(self.team.id).exists()

    def test_a_narrow_key_can_run_the_steps_it_covers(self) -> None:
        assert self._run(["suppressions"], NARROW_KEY).status == "completed"

    def test_a_scope_lost_during_the_run_names_what_it_cannot_read(self) -> None:
        run = self._start(["templates"])
        self.state.failures["/v3/templates"] = [403]

        with self.assertRaisesRegex(ImportCredentialsInvalid, "/v3/templates"):
            runs.run_step(self.team.id, run.id, "templates", attempt=1)

    def test_an_eu_key_reads_from_the_eu_host(self) -> None:
        run = self._run(["suppressions"], EU_KEY)

        assert run.status == "completed"
        assert {r["region"] for r in self.state.requests if r["path"] != "/v3/scopes"} == {"eu"}

    def test_a_rate_limit_waits_until_sendgrid_says_it_resets(self) -> None:
        self.state.rate_limits["/v3/suppression/spam_reports"] = (1, 60)
        self.state.account["spam_reports"] = [
            {"created": 1, "email": f"s{i}@example.com", "ip": "192.0.2.1"} for i in range(500)
        ]
        with patch(f"{_CLIENT}.MAX_RATE_LIMIT_WAITS", 2), patch(f"{_CLIENT}._seconds_until_reset", return_value=42.0):
            run = self._start(["suppressions"])
            with self.assertRaisesRegex(ImportProviderUnavailable, "slow down"):
                runs.run_step(self.team.id, run.id, "suppressions", attempt=1)

        assert 42.0 in [call.args[0] for call in self.sleep.call_args_list]
        run.refresh_from_db()
        assert run.progress["suppressions"]["checkpoint"]["list"] == "spam"

    def test_a_retry_continues_from_the_saved_page_without_reading_it_again(self) -> None:
        self.state.account["bounces"] = [
            {"created": 1, "email": f"b{i}@example.com", "reason": "x", "status": "5.1.1"} for i in range(1250)
        ]
        run = self._start(["suppressions"])
        self.state.fail_after["/v3/suppression/bounces"] = (1, 503)

        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "suppressions", attempt=1)
        run.refresh_from_db()
        assert run.progress["suppressions"]["checkpoint"]["offset"] == 500
        assert run.progress["suppressions"]["last_error"] == "SendGrid returned HTTP 503."
        assert run.progress["suppressions"]["status"] == "running"
        assert len(self._suppressions()) == 500

        self.state.fail_after.clear()
        self.state.requests.clear()
        runs.run_step(self.team.id, run.id, "suppressions", attempt=2)

        run.refresh_from_db()
        offsets = [r["query"]["offset"] for r in self.state.requests if r["path"] == "/v3/suppression/bounces"]
        assert offsets == ["500", "1000"]
        assert run.progress["suppressions"]["status"] == "completed"
        assert run.progress["suppressions"]["counts"]["bounced"] == 1250
        assert len(self._suppressions()) == 1250 + 3

    def test_a_killed_worker_writes_nothing_once_a_newer_attempt_owns_the_step(self) -> None:
        run = self._start(["suppressions"])
        pages = iter(SendGridImportProvider().run_step("suppressions", self._context(), None))
        first_page = next(pages)
        runs._claim_step(self.team.id, run.id, "suppressions", 1)
        runs._claim_step(self.team.id, run.id, "suppressions", 2)

        with self.assertRaises(runs.StaleImportAttempt):
            runs._save_page(self.team.id, run.id, "suppressions", 1, first_page)

        assert self._suppressions() == {}

    def _context(self) -> Any:
        return runs.ImportContext(
            team_id=self.team.id, created_by_id=self.user.id, integration_id=None, api_key=FULL_KEY
        )

    def test_a_group_larger_than_a_page_resumes_at_the_same_address(self) -> None:
        emails = [f"g{i:04}@example.com" for i in range(1250)]
        self.state.account["group_suppressions"]["101"] = list(reversed(emails))
        run = self._start(["group_unsubscribes"])
        pages = SendGridImportProvider().run_step("group_unsubscribes", self._context(), None)
        runs._claim_step(self.team.id, run.id, "group_unsubscribes", 1)
        runs._save_page(self.team.id, run.id, "group_unsubscribes", 1, next(pages))
        pages.close()
        self.state.account["group_suppressions"]["101"] = emails

        runs.run_step(self.team.id, run.id, "group_unsubscribes", attempt=2)

        assert sum(key.startswith("g") for key in self._preferences()) == 1250
        run.refresh_from_db()
        assert run.progress["group_unsubscribes"]["counts"]["opted_out"] == 1250 + 1

    def test_a_new_import_resumes_only_with_the_same_account(self) -> None:
        self.state.account["bounces"] = [
            {"created": 1, "email": f"b{i}@example.com", "reason": "x", "status": "5.1.1"} for i in range(600)
        ]
        run = self._start(["suppressions"])
        self.state.fail_after["/v3/suppression/bounces"] = (1, 503)
        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "suppressions", attempt=1)
        runs.finish_run(self.team.id, run.id)
        self.state.fail_after.clear()
        self.state.requests.clear()
        self.state.second_account["bounces"] = [
            {"created": 1, "email": f"second{i}@example.com", "reason": "x", "status": "5.1.1"} for i in range(3)
        ]

        self._run(["suppressions"], SECOND_ACCOUNT_KEY)

        assert [r["query"]["offset"] for r in self.state.requests if r["path"] == "/v3/suppression/bounces"] == ["0"]
        assert "second2@example.com" in self._suppressions()

    def test_the_key_is_gone_when_the_run_ends_and_a_rerun_needs_it_again(self) -> None:
        run = self._start(["lists"])
        assert ProviderImportRun.objects.for_team(self.team.id).get(id=run.id).temporary_api_key == FULL_KEY

        runs.finish_run(self.team.id, run.id)

        assert ProviderImportRun.objects.for_team(self.team.id).get(id=run.id).temporary_api_key is None
        with self.assertRaisesRegex(Exception, "Enter your SendGrid API key"):
            runs.start_run(self.team.id, "sendgrid", ["lists"], None, self.user.id)

    def test_importing_again_keeps_every_change_made_in_posthog(self) -> None:
        self._run()
        remove_suppressions(self.team.id, ["gone@example.com"], confirm_complaints=False)
        MessageRecipientPreference.objects.filter(team_id=self.team.id, identifier="unsubscribed@example.com").update(
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_IN"}
        )
        renamed = MessageCategory.objects.get(team_id=self.team.id, key="sendgrid_101")
        renamed.name = "News"
        renamed.save()
        deleted_category = MessageCategory.objects.get(team_id=self.team.id, key="sendgrid_102")
        deleted_category.deleted = True
        deleted_category.save()
        edited = MessageTemplate.objects.get(team_id=self.team.id, key="d-1111111111111111111111111111aaaa")
        edited.content["email"]["subject"] = "Edited here"
        edited.save()
        MessageTemplate.objects.filter(team_id=self.team.id, key="d-2222222222222222222222222222bbbb").update(
            deleted=True
        )
        templates_before = MessageTemplate.objects.filter(team_id=self.team.id).count()

        run = self._run()

        assert not MessageSuppression.objects.for_team(self.team.id).get(identifier="gone@example.com").suppressed
        assert self._preferences()["unsubscribed@example.com"][ALL_MESSAGE_PREFERENCE_CATEGORY_ID] == "OPTED_IN"
        renamed.refresh_from_db()
        assert renamed.name == "News"
        deleted_category.refresh_from_db()
        assert deleted_category.deleted
        edited.refresh_from_db()
        assert edited.content["email"]["subject"] == "Edited here"
        assert MessageTemplate.objects.filter(team_id=self.team.id).count() == templates_before
        assert run.progress["templates"]["counts"]["already_present"] == 4
        assert run.status == "completed"

    def test_an_empty_account_completes_with_nothing_imported(self) -> None:
        run = self._run(api_key=EMPTY_ACCOUNT_KEY)

        assert run.status == "completed"
        assert all(run.progress[step]["imported"] == 0 for step in ALL_STEPS)
        assert not MessageTemplate.objects.filter(team_id=self.team.id).exists()

    def test_next_page_links_never_receive_the_key(self) -> None:
        self.state.next_url_host = "https://evil.example.com"
        self.state.account["lists"] = [{"id": str(i), "name": f"L{i}", "contact_count": 0} for i in range(1500)]
        with patch(f"{_CLIENT}.requests.get", wraps=requests.get) as get:
            self._run(["lists"])

        hosts = {urlparse(call.args[0]).hostname for call in get.call_args_list}
        assert hosts == {"127.0.0.1"}
        assert [r["query"].get("page_token") for r in self.state.requests if r["path"] == "/v3/marketing/lists"] == [
            None,
            "1000",
        ]


class TestSendGridTemplateConversion(SimpleTestCase):
    @parameterized.expand([(case["name"], case) for case in RENDERS])
    def test_produces_the_liquid_the_render_tests_prove(self, _name: str, case: dict[str, Any]) -> None:
        if case.get("text"):
            assert convert_version({"subject": case["source"]}).subject == case["liquid"]
        else:
            converted = convert_version(
                {"html_content": case["source"], "generate_plain_content": False, "plain_content": "p"}
            )
            assert converted.html == case["liquid"]

    @parameterized.expand(
        [
            ("{{#if a}}unclosed", "{% raw %}{{#if a}}{% endraw %}unclosed", "valid Handlebars"),
            ("{{/if}}", "{% raw %}{{/if}}{% endraw %}", "valid Handlebars"),
            ("{{> partial}}", "{% raw %}{{> partial}}{% endraw %}", "{{> partial}}"),
            ("{{helper a b}}", "{% raw %}{{helper a b}}{% endraw %}", "{{helper a b}}"),
            (
                "{{#section}}x{{/section}}",
                "{% raw %}{{#section}}{% endraw %}x{% raw %}{{/section}}{% endraw %}",
                "section",
            ),
            ("{{@../index}}", "{% raw %}{{@../index}}{% endraw %}", "index"),
            ("{{formatDate t fmt}}", '{{ variables.t | date: "%Y-%m-%dT%H:%M:%S.%LZ", 0 }}', "fmt"),
            ("{{{Weblink}}}", "", "view in browser"),
        ]
    )
    def test_what_cannot_convert_stays_visible_and_gets_a_note(self, source: str, html: str, note: str) -> None:
        converted = convert_version({"html_content": source, "generate_plain_content": False, "plain_content": "p"})

        assert converted.html == html
        assert note in " ".join(converted.notes)

    @parameterized.expand(
        [
            ("Dear -name-", 'Dear {{ variables.name | default: "-name-" | raw }}'),
            ("well-known-word and x-y-z", "well-known-word and x-y-z"),
            ("<style>a{margin:-a-}</style>", "<style>a{margin:-a-}</style>"),
            ("{{not}} handlebars", "{% raw %}{{not}}{% endraw %} handlebars"),
            ("<%body%>", "{{ variables.body | raw }}"),
            ("<%asm_preferences_raw_url%>", "{{ unsubscribe_url }}"),
            (
                "&lt;%asm_group_unsubscribe_url%&gt;",
                '<a href="{{ unsubscribe_url }}">Unsubscribe From This List</a>',
            ),
        ]
    )
    def test_legacy_templates(self, source: str, html: str) -> None:
        converted = convert_version(
            {"html_content": source, "generate_plain_content": False, "plain_content": ""}, generation="legacy"
        )
        assert converted.html.strip() == html

    def test_only_a_template_with_other_tag_marks_gets_the_note_about_them(self) -> None:
        version = {"subject": "<%subject%>", "generate_plain_content": False}
        assert "%name%" not in " ".join(
            convert_version({**version, "html_content": "<%body%> 100% #fff"}, generation="legacy").notes
        )
        assert "%name%" in " ".join(
            convert_version({**version, "html_content": "Hi %name%"}, generation="legacy").notes
        )

    def test_plain_text_is_built_from_the_html_when_sendgrid_would_build_it(self) -> None:
        html = (
            "<html><head><style>p{color:red}</style></head><body><p>Hi {{ variables.n | raw }}</p>"
            '{% if variables.a > 1 %}<a href="{{ unsubscribe_url }}">Leave</a>{% endif %}<br>Tom &amp; Ann</body></html>'
        )

        assert plain_text_from_html(html) == (
            "Hi {{ variables.n }}\n{% if variables.a > 1 %}Leave ({{ unsubscribe_url }}){% endif %}\nTom & Ann"
        )

    def test_many_unclosed_tags_convert_quickly(self) -> None:
        assert convert_version({"html_content": "{{" * 200_000, "generate_plain_content": False}).html

    def test_scopes_accept_the_broader_suppression_scope(self) -> None:
        assert missing_scopes({"suppression.read"}, ["suppressions", "global_unsubscribes"]) == []
        assert missing_scopes(set(), ["suppressions"])[0] == "suppression.bounces.read"

    def test_client_repr_hides_the_key(self) -> None:
        assert FULL_KEY not in repr(SendGridClient(FULL_KEY, "https://example.com"))
