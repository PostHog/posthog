import copy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.messaging.backend.models.email_hard_bounce import EmailHardBounce
from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
)
from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.provider_import_run import ProviderImportRun
from products.messaging.backend.models.transactional_email_key import TransactionalEmailKey
from products.messaging.backend.provider_imports import runs
from products.messaging.backend.provider_imports.base import (
    ImportCredentialsInvalid,
    ImportProviderUnavailable,
    ImportTooLarge,
)
from products.messaging.backend.provider_imports.postmark import _merge
from products.messaging.backend.provider_imports.postmark_templates import convert_template, convert_text
from products.messaging.backend.services.suppression import remove_suppressions
from products.messaging.backend.temporal.workflow import STEP_RETRY_POLICY
from products.messaging.backend.tests.postmark_fake_server import FIXTURE, FakePostmark, start_server

ALL_STEPS = ["streams", "suppressions", "templates", "domains", "webhooks"]
ACCOUNT_TOKEN = "account-token-1111"
PRODUCTION_TOKEN = "server-token-production"
RENDER_CASES = json.loads((Path(__file__).parent / "fixtures" / "postmark_render_cases.json").read_text())


class TestSuppressionMerge(SimpleTestCase):
    @parameterized.expand([("unsubscribe_first", False), ("block_first", True)])
    def test_a_team_block_beats_an_unsubscribe_on_another_stream(self, _name: str, block_first: bool) -> None:
        unsubscribe = {"EmailAddress": "a@example.com", "SuppressionReason": "ManualSuppression", "Origin": "Recipient"}
        block = {**unsubscribe, "Origin": "Customer"}
        merged: dict[str, Any] = {}

        for row in [block, unsubscribe] if block_first else [unsubscribe, block]:
            _merge(merged, [row], is_transactional=False)

        assert merged["a@example.com"].origin == "Customer"


class TestMustachioToLiquid(SimpleTestCase):
    @parameterized.expand([(case["name"], case) for case in RENDER_CASES])
    def test_output_matches_the_case_checked_against_both_engines(self, _name: str, case: dict[str, Any]) -> None:
        assert convert_text(case["mustachio"], is_html=case["part"] == "html").text == case["liquid"]

    @parameterized.expand(
        [
            ("partial", "{{> footer }}"),
            ("space in name", "{{ first name }}"),
            ("unknown pm tag", "{{{ pm:other }}}"),
            ("unmatched close", "{{/nope}}"),
            ("each without a path", "{{#each}}"),
        ]
    )
    def test_what_mustachio_would_refuse_stays_visible_and_is_named(self, _name: str, tag: str) -> None:
        converted = convert_template({"Subject": "s", "HtmlBody": f"<p>{tag}</p>", "Active": True})

        assert any(tag in note for note in converted.notes)

    @parameterized.expand(
        [
            ("nested_sections", "{{#a}}{{#b}}" * 500 + "{{x}}" + "{{/b}}{{/a}}" * 500),
            ("one_long_path", "{{" + "a." * 40_000 + "a}}"),
        ]
    )
    def test_deep_nesting_stays_within_the_output_budget(self, _name: str, html: str) -> None:

        converted = convert_template({"Subject": "s", "HtmlBody": html, "Active": True})

        assert len(converted.html) < 1_000_000
        assert any("nest too deeply" in note for note in converted.notes)

    def test_an_unclosed_block_still_parses_as_liquid(self) -> None:
        converted = convert_text("{{#a}}x{{#each b}}y", is_html=True)

        assert converted.text.endswith("{% endfor %}{% endif %}")
        assert converted.unsupported_tags

    @parameterized.expand(
        [
            (
                "href double quote",
                '<a href="{{{ pm:unsubscribe }}}">Stop</a>',
                '<a href="{{ unsubscribe_url }}">Stop</a>',
            ),
            ("href escaped quote", '<a href=\\"{{{ pm:unsubscribe }}}\\">Stop</a>', None),
            ("bare", "<p>{{{ pm:unsubscribe }}}</p>", '<p><a href="{{ unsubscribe_url }}">Unsubscribe</a></p>'),
        ]
    )
    def test_unsubscribe_placeholder(self, _name: str, html: str, expected: str | None) -> None:
        converted = convert_text(html, is_html=True)

        assert converted.uses_unsubscribe_link
        if expected:
            assert converted.text == expected
        else:
            assert '<a href=\\"{{ unsubscribe_url }}\\">' in converted.text

    def test_unsubscribe_placeholder_in_text_is_the_url(self) -> None:
        assert convert_text("Stop: {{{ pm:unsubscribe }}}", is_html=False).text == "Stop: {{ unsubscribe_url }}"

    @parameterized.expand(
        [
            ("at sign triple", "<b>{{{ @content }}}</b>"),
            ("no spaces", "<b>{{{@content}}}</b>"),
            ("from the layouts page", "<b>{{{ content }}}</b>"),
            ("double", "<b>{{ @content }}</b>"),
        ]
    )
    def test_layout_placeholder_forms(self, _name: str, layout_html: str) -> None:
        template = {"Subject": "s", "HtmlBody": "<i>{{ a }}</i>", "LayoutTemplate": "l", "Active": True}

        converted = convert_template(template, {"HtmlBody": layout_html, "TextBody": None})

        assert converted.html == "<b><i>{{ variables.a }}</i></b>"

    def test_layout_scope_applies_to_the_template_inside_it(self) -> None:
        layout = {"HtmlBody": "{{#site}}{{{ @content }}}{{/site}}"}
        template = {"Subject": "s", "HtmlBody": "{{ name }}", "LayoutTemplate": "l", "Active": True}

        converted = convert_template(template, layout)

        assert "{{ variables.site.name }}" in converted.html

    def test_notes_name_each_loss(self) -> None:
        template = {
            "Subject": "s",
            "HtmlBody": "<style>a{}</style>{{#if x}}y{{/if}}{{this.z}}",
            "LayoutTemplate": "gone",
            "Active": False,
        }

        notes = " ".join(convert_template(template, None).notes)

        for expected in ("layout gone", "{{#if}}", "`this`", "style block", "unsubscribe link", "inactive"):
            assert expected in notes


class TestPostmarkImport(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.fake = FakePostmark()
        self._serve(self.fake)
        client = "products.messaging.backend.services.postmark_client"
        self.sleep = self._patch(f"{client}.time.sleep")
        self.start_workflow = self._patch(
            "products.messaging.backend.provider_imports.runs.start_provider_import_workflow"
        )
        self._patch(f"{client}.REQUESTS_PER_SECOND", 100000)

    def _serve(self, fake: FakePostmark) -> None:
        server = start_server(fake)
        self.addCleanup(server.shutdown)
        settings = override_settings(MESSAGING_POSTMARK_API_URL=f"http://127.0.0.1:{server.server_address[1]}")
        settings.enable()
        self.addCleanup(settings.disable)

    def _patch(self, target: str, *replacement: Any) -> Any:
        patcher = patch(target, *replacement)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def _run(self, steps: list[str] | None = None, token: str = ACCOUNT_TOKEN) -> ProviderImportRun:
        run = runs.start_run(self.team.id, "postmark", steps or ALL_STEPS, token, self.user.id)
        for step in run.steps:
            try:
                runs.run_step(self.team.id, run.id, step, attempt=1)
            except (ImportProviderUnavailable, ImportCredentialsInvalid):
                pass
        runs.finish_run(self.team.id, run.id)
        run.refresh_from_db()
        return run

    def _sources(self) -> dict[str, str]:
        return {
            row.identifier: row.source
            for row in MessageSuppression.objects.for_team(self.team.id).filter(deleted=False, suppressed=True)
        }

    def _opted_out(self) -> set[str]:
        return {
            row.identifier
            for row in MessageRecipientPreference.objects.filter(team_id=self.team.id)
            if (row.preferences or {}).get(ALL_MESSAGE_PREFERENCE_CATEGORY_ID) == "OPTED_OUT"
        }

    def test_requests_match_the_documented_endpoints_and_headers(self) -> None:
        self._run()

        assert self.fake.requests
        for request in self.fake.requests:
            assert request["method"] == "GET"
            assert request["accept"] == "application/json"
        account = {r["path"] for r in self.fake.requests if r["account_token"]}
        server = {r["path"] for r in self.fake.requests if r["server_token"]}
        assert {"/servers", "/domains", "/domains/501", "/senders"} <= account
        assert {
            "/message-streams",
            "/message-streams/outbound/suppressions/dump",
            "/templates",
            "/templates/receipt",
            "/webhooks",
        } <= server
        assert "/message-streams/inbound/suppressions/dump" not in server
        assert "/message-streams/old-news/suppressions/dump" not in server
        templates = next(r for r in self.fake.requests if r["path"] == "/templates")
        assert set(templates["query"]) == {"Count", "Offset"}
        domains = next(r for r in self.fake.requests if r["path"] == "/domains")
        assert set(domains["query"]) == {"count", "offset"}

    def test_suppressions_land_on_the_rule_that_matches_each_stream_and_reason(self) -> None:
        run = self._run(["suppressions"])

        assert self._sources() == {
            "gone@example.com": SuppressionSource.BOUNCE,
            "both-streams@example.com": SuppressionSource.BOUNCE,
            "jürgen+🦔@example.com": SuppressionSource.BOUNCE,
            "staging-bounce@example.com": SuppressionSource.BOUNCE,
            # A complaint on one server and a hard bounce on another: the hard bounce wins.
            "complainer@example.com": SuppressionSource.BOUNCE,
            "tx-complainer@example.com": SuppressionSource.COMPLAINT,
            "tx-manual@example.com": SuppressionSource.MANUAL,
            "added-by-team@example.com": SuppressionSource.MANUAL,
            "added-by-postmark@example.com": SuppressionSource.MANUAL,
        }
        assert self._opted_out() == {
            "mixed.case.unsub@example.com",
            "Mixed.Case.Unsub@Example.com",
            "MIXED.case.unsub@example.com",
            "news-only-unsub@example.com",
        }
        rows = MessageSuppression.objects.for_team(self.team.id)
        assert rows.get(identifier="gone@example.com").hard_bounced_at is not None
        assert rows.get(identifier="tx-complainer@example.com").hard_bounced_at is None
        assert (
            rows.get(identifier="added-by-postmark@example.com").reason == "Imported from Postmark (added by Postmark)"
        )
        assert EmailHardBounce.objects.count() == 0
        counts = run.progress["suppressions"]["counts"]
        assert counts["invalid"] == 1
        assert counts["transactional_block_lost"] == 2

    def test_an_edit_in_posthog_survives_importing_again(self) -> None:
        self._run(["suppressions", "templates", "streams"])
        remove_suppressions(self.team.id, ["gone@example.com"], confirm_complaints=False)
        edited = MessageTemplate.objects.get(team_id=self.team.id, key="receipt")
        edited.content = {"templating": "liquid", "email": {"subject": "Mine", "html": "<p>Mine</p>"}}
        edited.save()
        deleted = MessageTemplate.objects.get(team_id=self.team.id, key="password-reset")
        deleted.deleted = True
        deleted.save()
        MessageCategory.objects.filter(team_id=self.team.id).update(name="Renamed")
        templates_before = MessageTemplate.objects.filter(team_id=self.team.id).count()

        rerun = self._run(["suppressions", "templates", "streams"])

        assert "gone@example.com" not in self._sources()
        edited.refresh_from_db()
        assert edited.content["email"]["subject"] == "Mine"
        deleted.refresh_from_db()
        assert deleted.deleted is True
        assert MessageTemplate.objects.filter(team_id=self.team.id).count() == templates_before
        assert not MessageCategory.objects.filter(team_id=self.team.id).exclude(name="Renamed").exists()
        assert rerun.progress["templates"]["imported"] == 0

    def test_templates_copy_their_layout_and_never_become_sendable_on_their_own(self) -> None:
        run = self._run(["templates"], token=PRODUCTION_TOKEN)

        receipt = MessageTemplate.objects.get(team_id=self.team.id, key="receipt")
        email = receipt.content["email"]
        assert receipt.content["templating"] == "liquid"
        assert "from" not in email
        assert email["subject"] == "Receipt for {{ variables.customer.name }}"
        assert "{{ variables.product_name }}" in email["html"]
        assert '<a href="{{ unsubscribe_url }}">Unsubscribe</a>' in email["html"]
        assert "{{ variables.note_html | raw }}" in email["html"]
        assert "{% for item_1 in variables.lines %}{{ item_1.sku }}" not in email["html"]
        assert "{{ item_1.sku }} for {{ variables.currency }}{{ item_1.price }}" in email["html"]
        assert email["text"].startswith("{{ variables.product_name }}\n\nHi {{ variables.customer.name }}")
        assert "layout base-layout" in receipt.description
        assert receipt.draft_content is None
        items = {item["label"]: item for item in run.progress["templates"]["items"]}
        assert "PostHog has no layouts" in items["Base layout (layout)"]["notes"][0]
        assert run.progress["templates"]["counts"]["layouts"] == 1

        dotted = MessageTemplate.objects.get(team_id=self.team.id, key="password-reset")
        assert "the key is password-reset" in dotted.description
        text_only = MessageTemplate.objects.get(team_id=self.team.id, key="postmark-2004")
        assert text_only.content["email"]["html"] == ""
        assert text_only.content["email"]["text"] == "Text only for {{ variables.name }}"
        assert "inactive" in text_only.description
        lost = MessageTemplate.objects.get(team_id=self.team.id, key="lost-layout")
        assert "couldn't find the layout gone-layout" in lost.description
        assert "{{> partial}}" in lost.description

    def test_an_account_token_covers_each_live_server_and_a_repeated_alias_keeps_both(self) -> None:
        run = self._run(["templates", "streams"])

        keys = set(MessageTemplate.objects.filter(team_id=self.team.id).values_list("key", flat=True))
        assert {"receipt", "receipt-1002"} <= keys
        assert "sandbox-template" not in keys
        staging = MessageTemplate.objects.get(team_id=self.team.id, key="receipt-1002")
        assert staging.content["email"]["subject"] == "Staging receipt"
        assert "the key is receipt-1002" in staging.description
        assert run.progress["streams"]["counts"]["servers_skipped"] == 1
        assert "sandbox-only@example.com" not in self._sources()

        rerun = self._run(["templates"])

        assert rerun.progress["templates"]["counts"]["already_present"] == len(
            MessageTemplate.objects.filter(team_id=self.team.id)
        )

    @parameterized.expand([("dotted_alias_first", True), ("exact_alias_first", False)])
    def test_an_alias_that_turns_into_another_templates_alias_gets_its_own_key(
        self, _name: str, dotted_first: bool
    ) -> None:
        data = json.loads(FIXTURE.read_text())
        server = data["servers"][0]
        dotted = next(row for row in server["templates"] if row["Alias"] == "password.reset")
        exact = {**copy.deepcopy(dotted), "TemplateId": 2099, "Alias": "password-reset", "Subject": "Exact"}
        server["templates"] = [dotted, exact] if dotted_first else [exact, dotted]
        self.fake.data = data

        self._run(["templates"], token=PRODUCTION_TOKEN)
        rerun = self._run(["templates"], token=PRODUCTION_TOKEN)

        subjects = {
            row.key: row.content["email"]["subject"] for row in MessageTemplate.objects.filter(team_id=self.team.id)
        }
        assert subjects == {"password-reset": "Exact", "password-reset-2003": "Reset your password"}
        assert rerun.progress["templates"]["counts"]["already_present"] == 2

    def test_a_key_a_code_email_sends_under_is_left_to_it(self) -> None:
        TransactionalEmailKey.objects.for_team(self.team.id).create(team=self.team, key="receipt", hog_flow_id=uuid4())

        self._run(["templates"], token=PRODUCTION_TOKEN)

        assert not MessageTemplate.objects.filter(team_id=self.team.id, key="receipt").exists()

    def test_a_template_someone_else_owns_the_key_of_is_left_alone(self) -> None:
        MessageTemplate.objects.create(team_id=self.team.id, key="receipt", name="Mine", type="email", content={})

        run = self._run(["templates"], token=PRODUCTION_TOKEN)

        assert MessageTemplate.objects.get(team_id=self.team.id, key="receipt").name == "Mine"
        assert run.progress["templates"]["counts"]["already_present"] == 1

    def test_only_a_custom_broadcast_stream_becomes_a_category(self) -> None:
        run = self._run(["streams"], token=PRODUCTION_TOKEN)

        categories = {
            row.key: (row.name, row.public_description) for row in MessageCategory.objects.filter(team_id=self.team.id)
        }
        assert categories == {"postmark_1001_product-news": ("Product news", "")}
        notes = {item["label"]: " ".join(item["notes"]) for item in run.progress["streams"]["items"]}
        assert "SMTP" in notes["Production (server)"]
        assert "Inbound" in notes["Default Inbound Stream (inbound)"]
        assert "archived" in notes["Old news (old-news)"]

    def test_a_server_token_imports_its_server_and_says_what_it_cannot_read(self) -> None:
        run = self._run(token=PRODUCTION_TOKEN)

        assert run.status == "completed"
        domains = run.progress["domains"]
        assert domains["counts"] == {"needs_account_token": 1}
        assert "account token" in domains["warnings"][0]
        assert not {r["path"] for r in self.fake.requests} & {"/domains", "/senders", "/servers"}

    def test_domains_and_senders_list_dns_notes_and_write_nothing(self) -> None:
        run = self._run(["domains"])

        items = {item["label"]: item for item in run.progress["domains"]["items"]}
        assert any("20240101pm._domainkey" in note for note in items["acme.example.com"]["notes"])
        assert any("MAIL FROM" in note for note in items["news.example.com"]["notes"])
        assert any("support@acme.example.com" in note for note in items["Acme Team <hello@acme.example.com>"]["notes"])
        assert any("isn't confirmed" in note for note in items["Zoë 🦔 <zoë@news.example.com>"]["notes"])
        assert run.progress["domains"]["counts"]["needs_setup"] == 2

    def test_no_token_or_webhook_secret_reaches_the_run(self) -> None:
        run = self._run()

        stored = json.dumps(run.progress)
        for secret in (ACCOUNT_TOKEN, PRODUCTION_TOKEN, "server-token-staging", "hook-secret"):
            assert secret not in stored
        assert run.temporary_api_key is None
        items = {item["label"]: item for item in run.progress["webhooks"]["items"]}
        assert "Open, Bounce" in items["Production: outbound to hooks.example.com"]["notes"][0]

    @parameterized.expand(
        [
            ("wrong token", "nope", None, ImportCredentialsInvalid, "rejected this token"),
            ("postmark test token", "POSTMARK_API_TEST", None, ImportCredentialsInvalid, "rejected this token"),
            ("non ascii", "tökén", None, ImportCredentialsInvalid, "rejected this token"),
            ("no access", PRODUCTION_TOKEN, 403, ImportCredentialsInvalid, "can't read all"),
            ("rate limited", PRODUCTION_TOKEN, 429, ImportProviderUnavailable, "slow down"),
            ("outage", PRODUCTION_TOKEN, 503, ImportProviderUnavailable, "HTTP 503"),
        ]
    )
    def test_a_token_that_cannot_work_is_refused_before_a_run_starts(
        self, _name: str, token: str, status: int | None, error: type[Exception], message: str
    ) -> None:
        if status:
            self.fake.fail("/server", status)

        with self.assertRaisesRegex(error, message):
            runs.start_run(self.team.id, "postmark", ["templates"], token, self.user.id)

        assert not ProviderImportRun.objects.for_team(self.team.id).exists()
        self.start_workflow.assert_not_called()

    def test_a_token_without_stream_access_fails_the_step_with_a_clear_message(self) -> None:
        self.fake.fail("/message-streams", 422, times=5, body={"ErrorCode": 1220, "Message": "No permission"})

        run = self._run(["suppressions"], token=PRODUCTION_TOKEN)

        assert run.status == "failed"
        assert "can't read all" in run.progress["suppressions"]["last_error"]
        assert run.temporary_api_key is None

    @parameterized.expand(
        [
            ("told how long", {"Retry-After": "7"}, [7.0]),
            ("not told", {}, [1.0]),
            ("told too long", {"Retry-After": "9000"}, [60.0]),
            ("told nonsense", {"Retry-After": "soon"}, [1.0]),
        ]
    )
    def test_a_rate_limit_waits_and_carries_on(self, _name: str, headers: dict[str, str], waits: list[float]) -> None:
        self.fake.fail("/webhooks", 429, headers=headers)

        run = self._run(["webhooks"], token=PRODUCTION_TOKEN)

        assert run.status == "completed"
        assert [call.args[0] for call in self.sleep.call_args_list if call.args[0] >= 1] == waits

    def test_a_rate_limit_that_never_ends_fails_the_step_and_clears_the_token(self) -> None:
        self.fake.fail("/webhooks", 429, times=100)

        run = self._run(["webhooks"], token=PRODUCTION_TOKEN)

        assert run.status == "failed"
        assert "slow down" in run.progress["webhooks"]["last_error"]
        assert run.temporary_api_key is None
        assert [call.args[0] for call in self.sleep.call_args_list if call.args[0] >= 1] == [1.0, 2.0, 4.0, 8.0, 16.0]

    def test_a_revoked_token_during_a_step_stops_it_without_a_retry(self) -> None:
        self.fake.fail("/templates", 401, body={"ErrorCode": 10, "Message": "Bad token"})
        run = runs.start_run(self.team.id, "postmark", ["templates"], PRODUCTION_TOKEN, self.user.id)

        with self.assertRaises(ImportCredentialsInvalid):
            runs.run_step(self.team.id, run.id, "templates", attempt=1)

    def test_a_large_suppression_list_saves_in_batches_and_resumes_after_the_last_saved_address(self) -> None:
        data = json.loads(FIXTURE.read_text())
        data["servers"] = data["servers"][:1]
        data["servers"][0]["suppressions"] = {
            "broadcast": [
                {
                    "EmailAddress": f"bulk-{index:04d}@example.com",
                    "SuppressionReason": "HardBounce",
                    "Origin": "Recipient",
                    "CreatedAt": "2026-06-01T08:58:33-05:00",
                }
                for index in range(1200)
            ]
        }
        self.fake.data = data
        real_save = runs._save_page
        saves = {"count": 0}

        def fail_on_second_page(*args: Any, **kwargs: Any) -> None:
            saves["count"] += 1
            if saves["count"] == 2:
                raise ImportProviderUnavailable("Worker lost its connection.")
            real_save(*args, **kwargs)

        with patch.object(runs, "_save_page", fail_on_second_page):
            first = self._run(["suppressions"], token=PRODUCTION_TOKEN)

        assert first.status == "failed"
        assert len(self._sources()) == 500
        assert first.progress["suppressions"]["checkpoint"] == {"after_address": "bulk-0499@example.com"}

        second = self._run(["suppressions"], token=PRODUCTION_TOKEN)

        assert second.status == "completed"
        assert second.progress["suppressions"]["processed"] == 700
        assert len(self._sources()) == 1200

    @parameterized.expand([("addresses", "MAX_SUPPRESSED_ADDRESSES", 1000), ("bytes", "MAX_DUMP_BYTES", 50_000)])
    def test_a_suppression_list_over_the_budget_stops_without_a_retry(
        self, _name: str, budget: str, limit: int
    ) -> None:
        data = json.loads(FIXTURE.read_text())
        data["servers"] = data["servers"][:1]
        data["servers"][0]["suppressions"] = {
            "broadcast": [
                {
                    "EmailAddress": f"bulk-{index:04d}@example.com",
                    "SuppressionReason": "HardBounce",
                    "Origin": "Recipient",
                    "CreatedAt": "2026-06-01T08:58:33-05:00",
                }
                for index in range(1200)
            ]
        }
        self.fake.data = data
        run = runs.start_run(self.team.id, "postmark", ["suppressions"], PRODUCTION_TOKEN, self.user.id)

        with patch(f"products.messaging.backend.provider_imports.postmark.{budget}", limit):
            with self.assertRaisesRegex(ImportTooLarge, "more suppressed addresses than PostHog can import"):
                runs.run_step(self.team.id, run.id, "suppressions", attempt=1)

        assert "ImportTooLarge" in STEP_RETRY_POLICY.non_retryable_error_types
        assert self._sources() == {}

    def test_a_new_retry_of_the_same_run_continues_templates_from_the_saved_offset(self) -> None:
        data = json.loads(FIXTURE.read_text())
        server = data["servers"][0]
        server["templates"] = [
            {
                **copy.deepcopy(server["templates"][2]),
                "TemplateId": 9000 + index,
                "Alias": f"page-{index}",
                "LayoutTemplate": None,
            }
            for index in range(150)
        ]
        self.fake.data = data
        self.fake.fail("/templates/page-120", 500)
        run = runs.start_run(self.team.id, "postmark", ["templates"], PRODUCTION_TOKEN, self.user.id)

        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "templates", attempt=1)
        assert MessageTemplate.objects.filter(team_id=self.team.id).count() == 100
        self.fake.requests.clear()

        runs.run_step(self.team.id, run.id, "templates", attempt=2)

        assert MessageTemplate.objects.filter(team_id=self.team.id).count() == 150
        offsets = [r["query"]["Offset"] for r in self.fake.requests if r["path"] == "/templates"]
        assert offsets == ["100"]

    def test_an_empty_account_finishes_with_nothing_written(self) -> None:
        self.fake.data = {
            "account_token": ACCOUNT_TOKEN,
            "domains": [],
            "senders": [],
            "servers": [
                {
                    "ID": 1,
                    "Name": "Empty",
                    "ApiTokens": ["empty-token"],
                    "DeliveryType": "Live",
                    "streams": [],
                    "suppressions": {},
                    "templates": [],
                    "webhooks": [],
                }
            ],
        }

        run = self._run()

        assert run.status == "completed"
        assert not MessageTemplate.objects.filter(team_id=self.team.id).exists()
        assert self._sources() == {}

    def test_headers_use_the_kind_the_token_turned_out_to_be(self) -> None:
        self._run(["webhooks"], token=PRODUCTION_TOKEN)

        assert self.fake.requests[0]["server_token"] == PRODUCTION_TOKEN
        assert all(r["account_token"] is None for r in self.fake.requests)
