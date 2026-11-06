import re
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.integrations import IntegrationManager

from products.messaging.backend.facade.provider_imports import get_provider_import_run
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
from products.messaging.backend.provider_imports.resend_templates import convert_template, convert_text
from products.messaging.backend.services.suppression import remove_suppression

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "resend_account.json").read_text())
ALL_STEPS = ["topics", "suppressions", "opt_outs", "topic_opt_outs", "templates", "domains"]
API_KEY = "re_full_access_key"


class FakeResend:
    """Answers `requests.get` the way Resend's public API docs describe, from the invented fixtures."""

    def __init__(self, page_size: int = 100) -> None:
        self.data: dict[str, Any] = {
            key: list(value) if isinstance(value, list) else value for key, value in FIXTURES.items()
        }
        self.page_size = page_size
        self.calls: list[str] = []
        # Path to a queue of status codes to answer with before the normal response.
        self.failures: dict[str, list[tuple[int, dict[str, str]]]] = {}

    def get(self, url: str, params: dict | None = None, **_: Any) -> MagicMock:
        path = urlparse(url).path
        params = params or {}
        self.calls.append(path)
        if self.failures.get(path):
            status, headers = self.failures[path].pop(0)
            return self._response(status, {"name": "rate_limit_exceeded", "message": "Too many"}, headers)
        if match := re.fullmatch(r"/contacts/([^/]+)/topics", path):
            return self._page(self.data["contact_topics"].get(match.group(1), []), params)
        if match := re.fullmatch(r"/(templates|domains|automations)/([^/]+)", path):
            for row in self.data[match.group(1)]:
                if match.group(2) in (row["id"], row.get("alias")):
                    return self._response(200, row)
            return self._response(404, {"name": "not_found", "message": "Not found"})
        return self._page(self.data[path.strip("/")], params)

    def _page(self, rows: list[dict], params: dict) -> MagicMock:
        ids = [row["id"] for row in rows]
        start = ids.index(params["after"]) + 1 if params.get("after") else 0
        limit = min(params.get("limit", 20), self.page_size)
        return self._response(
            200, {"object": "list", "has_more": start + limit < len(rows), "data": rows[start : start + limit]}
        )

    @staticmethod
    def _response(status: int, body: dict, headers: dict[str, str] | None = None) -> MagicMock:
        response = MagicMock(status_code=status, ok=status < 400, headers=headers or {})
        response.json.return_value = body
        return response


class TestResendImport(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.resend = FakeResend()
        client = "products.messaging.backend.services.resend_client"
        self.sleep = self._patch(f"{client}.time.sleep")
        self.start_workflow = self._patch(
            "products.messaging.backend.provider_imports.runs.start_provider_import_workflow"
        )
        self._patch(f"{client}.requests.get", self.resend.get)
        self._patch(f"{client}.REQUESTS_PER_SECOND", 100000)

    def _patch(self, target: str, *replacement: Any) -> Any:
        patcher = patch(target, *replacement)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def _run(self, steps: list[str] | None = None, api_key: str = API_KEY) -> ProviderImportRun:
        run = runs.start_run(self.team.id, "resend", steps or ALL_STEPS, api_key, self.user.id)
        for step in run.steps:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        runs.finish_run(self.team.id, run.id)
        run.refresh_from_db()
        return run

    def test_suppressions_map_by_origin_and_never_reach_the_global_list(self) -> None:
        run = self._run(["suppressions"])

        rows = {row.identifier: row for row in MessageSuppression.objects.for_team(self.team.id).filter(deleted=False)}
        assert {identifier: row.source for identifier, row in rows.items()} == {
            "gone@example.com": SuppressionSource.BOUNCE,
            "mixedcase.bounce@example.com": SuppressionSource.BOUNCE,
            "complainer@example.com": SuppressionSource.COMPLAINT,
            "added-by-team@example.com": SuppressionSource.MANUAL,
            "jürgen+🦔@example.com": SuppressionSource.MANUAL,
        }
        assert rows["gone@example.com"].hard_bounced_at is not None
        assert rows["complainer@example.com"].hard_bounced_at is None
        assert rows["added-by-team@example.com"].hard_bounced_at is None
        assert EmailHardBounce.objects.count() == 0
        assert run.progress["suppressions"]["counts"] == {
            "bounced": 2,
            "complained": 1,
            "manual": 2,
            "already_present": 0,
            "invalid": 1,
        }

    def test_opt_outs_read_contacts_without_creating_people(self) -> None:
        self._run(["topics", "opt_outs", "topic_opt_outs"])

        preferences = {
            row.identifier: row.preferences for row in MessageRecipientPreference.objects.filter(team_id=self.team.id)
        }
        category = MessageCategory.objects.get(team_id=self.team.id, name="Product updates")
        assert preferences == {
            "unsubscribed@example.com": {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"},
            "Björk.Unsub@example.com": {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"},
            "left-a-topic@example.com": {str(category.id): "OPTED_OUT"},
        }
        assert "/contacts/c0000000-0000-4000-8000-000000000001/topics" not in self.resend.calls

    @parameterized.expand([("completed", True), ("failed_step", False)])
    def test_key_is_gone_when_the_run_ends(self, _name: str, completes: bool) -> None:
        run = runs.start_run(self.team.id, "resend", ["suppressions"], API_KEY, self.user.id)
        assert ProviderImportRun.objects.for_team(self.team.id).get(id=run.id).temporary_api_key == API_KEY
        if completes:
            runs.run_step(self.team.id, run.id, "suppressions", attempt=1)
        runs.finish_run(self.team.id, run.id)

        run = ProviderImportRun.objects.for_team(self.team.id).get(id=run.id)
        assert run.temporary_api_key is None
        assert run.status == ("completed" if completes else "failed")

    def test_key_is_gone_when_the_workflow_cannot_start(self) -> None:
        self.start_workflow.side_effect = ConnectionError("Temporal is down")
        with self.assertRaises(ConnectionError):
            runs.start_run(self.team.id, "resend", ["suppressions"], API_KEY, self.user.id)

        run = ProviderImportRun.objects.for_team(self.team.id).get()
        assert run.temporary_api_key is None and run.status == "failed"

    def test_key_is_gone_after_a_workflow_that_never_finished(self) -> None:
        run = runs.start_run(self.team.id, "resend", ["suppressions"], API_KEY, self.user.id)
        ProviderImportRun.objects.for_team(self.team.id).filter(id=run.id).update(
            created_at=timezone.now() - runs.STALE_RUN_AGE * 2
        )

        assert runs.close_stale_runs() == 1

        run = ProviderImportRun.objects.for_team(self.team.id).get(id=run.id)
        assert run.temporary_api_key is None and run.status == "failed"

    @parameterized.expand(
        [
            ("sending_only", 401, {"name": "restricted_api_key", "message": "Only send"}, "can only send email"),
            ("wrong_key", 400, {"name": "validation_error", "message": "API key is invalid"}, "rejected this API key"),
            ("revoked", 403, {"name": "restricted_api_key", "message": "Not active"}, "rejected this API key"),
        ]
    )
    def test_a_key_that_cannot_read_stops_before_any_run(
        self, _name: str, status: int, body: dict, message: str
    ) -> None:
        response = FakeResend._response(status, body)
        with patch("products.messaging.backend.services.resend_client.requests.get", return_value=response):
            with self.assertRaisesRegex(ImportCredentialsInvalid, message):
                runs.start_run(self.team.id, "resend", ["suppressions"], API_KEY, self.user.id)

        assert not ProviderImportRun.objects.for_team(self.team.id).exists()

    def test_a_rate_limit_waits_as_long_as_resend_says(self) -> None:
        self.resend.failures["/suppressions"] = [(429, {"retry-after": "7"})]

        run = self._run(["suppressions"])

        assert 7.0 in [call.args[0] for call in self.sleep.call_args_list]
        assert run.status == "completed"

    def test_a_retry_after_an_outage_continues_from_the_saved_page(self) -> None:
        self.resend.page_size = 2
        run = runs.start_run(self.team.id, "resend", ["suppressions"], API_KEY, self.user.id)
        read_first_page = self.resend.get

        def fail_second_page(url: str, params: dict | None = None, **kwargs: Any) -> MagicMock:
            if params and params.get("after"):
                return FakeResend._response(503, {"name": "service_unavailable", "message": "Down"})
            return read_first_page(url, params, **kwargs)

        with patch("products.messaging.backend.services.resend_client.requests.get", fail_second_page):
            with self.assertRaises(ImportProviderUnavailable):
                runs.run_step(self.team.id, run.id, "suppressions", attempt=1)
        run.refresh_from_db()
        assert run.progress["suppressions"]["checkpoint"] == {"after": FIXTURES["suppressions"][1]["id"]}
        assert run.progress["suppressions"]["last_error"] == "Resend returned HTTP 503."

        self.resend.calls.clear()
        runs.run_step(self.team.id, run.id, "suppressions", attempt=2)

        run.refresh_from_db()
        assert run.progress["suppressions"]["status"] == "completed"
        assert run.progress["suppressions"]["processed"] == len(FIXTURES["suppressions"])
        assert len(self.resend.calls) == 2

    def test_topic_choices_are_read_when_the_unsubscribes_step_did_not_run(self) -> None:
        self._run(["topic_opt_outs"])

        assert "/contacts/c0000000-0000-4000-8000-000000000001/topics" in self.resend.calls

    def test_a_new_import_continues_the_step_that_failed(self) -> None:
        self.resend.page_size = 2
        run = runs.start_run(self.team.id, "resend", ["suppressions"], API_KEY, self.user.id)
        read = self.resend.get

        def fail_second_page(url: str, params: dict | None = None, **kwargs: Any) -> MagicMock:
            if params and params.get("after"):
                return FakeResend._response(503, {"name": "service_unavailable", "message": "Down"})
            return read(url, params, **kwargs)

        with patch("products.messaging.backend.services.resend_client.requests.get", fail_second_page):
            with self.assertRaises(ImportProviderUnavailable):
                runs.run_step(self.team.id, run.id, "suppressions", attempt=1)
        runs.finish_run(self.team.id, run.id)
        self.resend.calls.clear()

        self._run(["suppressions"])

        assert len([call for call in self.resend.calls if call == "/suppressions"]) == 2

    def test_opt_outs_reach_a_row_another_request_inserted_first(self) -> None:
        MessageRecipientPreference.objects.create(
            team_id=self.team.id, identifier="unsubscribed@example.com", preferences={}
        )

        self._run(["opt_outs"])

        row = MessageRecipientPreference.objects.get(team_id=self.team.id, identifier="unsubscribed@example.com")
        assert row.preferences == {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"}

    def test_importing_again_keeps_every_change_made_in_posthog(self) -> None:
        self._run()
        remove_suppression(self.team.id, "gone@example.com")
        MessageRecipientPreference.objects.filter(team_id=self.team.id, identifier="unsubscribed@example.com").update(
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_IN"}
        )
        renamed = MessageCategory.objects.get(team_id=self.team.id, name="Product updates")
        renamed.name = "News"
        renamed.save()
        deleted_category = MessageCategory.objects.get(team_id=self.team.id, name__startswith="Beta invitations")
        deleted_category.deleted = True
        deleted_category.save()
        edited = MessageTemplate.objects.get(team_id=self.team.id, key="welcome-email")
        edited.content["email"]["subject"] = "Edited here"
        edited.save()
        MessageTemplate.objects.filter(team_id=self.team.id, key="receipt").update(deleted=True)
        templates_before = MessageTemplate.objects.filter(team_id=self.team.id).count()

        run = self._run()

        assert not MessageSuppression.objects.for_team(self.team.id).get(identifier="gone@example.com").suppressed
        assert (
            MessageRecipientPreference.objects.get(
                team_id=self.team.id, identifier="unsubscribed@example.com"
            ).preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID]
            == "OPTED_IN"
        )
        renamed.refresh_from_db()
        assert renamed.name == "News"
        deleted_category.refresh_from_db()
        assert deleted_category.deleted
        edited.refresh_from_db()
        assert edited.content["email"]["subject"] == "Edited here"
        assert MessageTemplate.objects.filter(team_id=self.team.id).count() == templates_before
        assert run.progress["templates"]["counts"]["already_present"] == len(FIXTURES["templates"])

    def test_templates_carry_sender_key_and_review_notes(self) -> None:
        sender = IntegrationManager.email.credentials.create(
            self.team.id,
            external_id="hello@example.com",
            config={"email": "hello@example.com", "domain": "example.com", "verified": True, "name": "Acme"},
            sensitive_config={},
            created_by_id=self.user.id,
        )
        run = self._run(["templates"])

        welcome = MessageTemplate.objects.get(team_id=self.team.id, key="welcome-email")
        email = welcome.content["email"]
        assert email["from"] == {"integrationId": sender.id, "email": "hello@example.com", "name": "Acme"}
        assert email["replyTo"] == "support@example.com"
        assert welcome.transactional_hog_flow_id is None
        items = {item["label"]: item for item in run.progress["templates"]["items"]}
        assert items["Welcome email"]["url"] == f"/workflows/library/templates/{welcome.id}"
        assert any("{{#if IS_PRO}}" in note and "{{else}}" in note for note in items["Conditional footer"]["notes"])
        imported_key = MessageTemplate.objects.filter(team_id=self.team.id, name__startswith="Přivítání").get().key
        assert imported_key is not None and imported_key.startswith("resend-")

    def test_run_state_exposes_summary_for_the_ui(self) -> None:
        run = self._run(["suppressions", "domains"])

        state = get_provider_import_run(self.team.id, run.id)
        assert state is not None
        suppressions, domains = state.steps
        assert [count.key for count in suppressions.counts] == ["bounced", "complained", "manual", "invalid"]
        assert [item.label for item in domains.items] == [domain["name"] for domain in FIXTURES["domains"]]
        org_domain = next(item for item in domains.items if item.label == "mail.example.org")
        assert any("feedback" in note for note in org_domain.notes)


class TestResendTemplateConversion(SimpleTestCase):
    @parameterized.expand(
        [
            ("{{{NAME}}}", True, "{{ variables.NAME | raw }}"),
            ("{{NAME}}", True, "{{ variables.NAME }}"),
            ("{{{NAME}}}", False, "{{ variables.NAME }}"),
            ("{{{NAME|there}}}", True, '{{ variables.NAME | default: "there" | raw }}'),
            ("{{{NAME|it's}}}", False, '{{ variables.NAME | default: "it\'s" }}'),
            ("{{{RESEND_UNSUBSCRIBE_URL}}}", True, "{{ unsubscribe_url }}"),
            ("{{{contact.first_name|friend}}}", False, '{{ variables.first_name | default: "friend" }}'),
            ("{{#if X}}", True, "{% raw %}{{#if X}}{% endraw %}"),
            ("{{else}}", True, "{% raw %}{{else}}{% endraw %}"),
            ("{% assign a = 1 %}", True, "{% raw %}{% assign a = 1 %}{% endraw %}"),
            ("{% endraw %}", True, '{{ "{%" }} endraw %}'),
            ("{{ a endraw }}", True, '{{ "{{" }} a endraw }}'),
            ("{{{ a endraw }}}", True, '{{ "{{" }}{ a endraw }}}'),
            ("Hi {{NAME", True, 'Hi {{ "{{" }}NAME'),
            ("{% if", True, '{{ "{%" }} if'),
            ("{{{NAME|a\\b}}}", False, "{{ variables.NAME }}"),
            ("{{{NAME|Tom &amp; Ann}}}", False, "{{ variables.NAME }}"),
            ("{{{NAME|Tom & Ann}}}", False, '{{ variables.NAME | default: "Tom & Ann" }}'),
            ("plain 🦔 text", True, "plain 🦔 text"),
        ]
    )
    def test_converts_tags(self, source: str, is_html: bool, expected: str) -> None:
        assert convert_text(source, {}, is_html=is_html).text == expected

    def test_unclosed_braces_scan_in_linear_time(self) -> None:
        assert convert_text("{{" * 200_000, {}, is_html=True).text.startswith('{{ "{{" }}')

    def test_notes_name_what_to_review(self) -> None:
        converted = convert_template(
            {
                "status": "draft",
                "subject": "Hi {{{FIRST_NAME}}}",
                "html": "{{{ORDER}}} {{#each X}}",
                "variables": [{"key": "ORDER", "fallback_value": None}],
            }
        )
        joined = " ".join((*converted.notes, *converted.send_notes))
        assert "{{#each X}}" in joined
        assert "FIRST_NAME" in joined
        assert "ORDER" in joined
        assert "isn't published" in joined
