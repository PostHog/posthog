import re
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.integrations import IntegrationManager, IntegrationRecord

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.cohorts.backend.models.cohort import Cohort
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
from products.messaging.backend.models.transactional_email_key import TransactionalEmailKey
from products.messaging.backend.provider_imports import resend, runs
from products.messaging.backend.provider_imports.base import (
    ImportCredentialsInvalid,
    ImportProviderUnavailable,
    ImportStepBlocked,
)
from products.messaging.backend.provider_imports.resend_templates import convert_template, convert_text
from products.messaging.backend.services.suppression import remove_suppressions
from products.messaging.backend.tests.people_import_recorder import PeopleImportRecorder
from products.workflows.backend.facade.workflows import get_workflow

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "resend_account.json").read_text())
ALL_STEPS = ["topics", "suppressions", "opt_outs", "topic_opt_outs", "templates", "automations", "domains"]
API_KEY = "re_full_access_key"


def _sync_email_template() -> None:
    sync_template_to_db(
        {
            **MOCK_NODE_TEMPLATES[0],
            "id": "template-email",
            "name": "Email",
            "inputs_schema": [{"key": "email", "type": "native_email", "label": "Email", "required": True}],
        }
    )


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
        if path == "/contacts" and (segment_ids := parse_qs(urlparse(url).query).get("segment_id")):
            members = set(self.data["segment_contacts"].get(segment_ids[0], []))
            return self._page([row for row in self.data["contacts"] if row["id"] in members], params)
        if match := re.fullmatch(r"/contacts/([^/]+)/topics", path):
            return self._page(self.data["contact_topics"].get(match.group(1), []), params)
        if match := re.fullmatch(r"/(templates|domains|automations|segments)/([^/]+)", path):
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
        _sync_email_template()
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
        MessageSuppression.objects.for_team(self.team.id).create(
            team=self.team,
            identifier="gone@example.com",
            source=SuppressionSource.COMPLAINT,
            reason="Marked as spam",
            suppressed=True,
        )

        run = self._run(["suppressions"])

        rows = {row.identifier: row for row in MessageSuppression.objects.for_team(self.team.id).filter(deleted=False)}
        assert {identifier: row.source for identifier, row in rows.items()} == {
            "gone@example.com": SuppressionSource.COMPLAINT,
            "mixedcase.bounce@example.com": SuppressionSource.BOUNCE,
            "complainer@example.com": SuppressionSource.COMPLAINT,
            "added-by-team@example.com": SuppressionSource.MANUAL,
            "jürgen+🦔@example.com": SuppressionSource.MANUAL,
        }
        assert rows["gone@example.com"].hard_bounced_at is not None
        assert rows["gone@example.com"].reason == "Marked as spam"
        assert rows["complainer@example.com"].hard_bounced_at is None
        assert rows["added-by-team@example.com"].hard_bounced_at is None
        assert EmailHardBounce.objects.count() == 0
        assert run.progress["suppressions"]["counts"] == {
            "bounced": 1,
            "complained": 1,
            "manual": 2,
            "already_present": 1,
            "invalid": 1,
        }

    def test_opt_outs_read_contacts_without_creating_people(self) -> None:
        run = self._run(["topics", "opt_outs", "topic_opt_outs"])

        assert run.progress["topics"]["counts"] == {"created": 2, "already_present": 0, "private": 1}
        assert not MessageCategory.objects.filter(team_id=self.team.id, name__startswith="Beta invitations").exists()
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

    def test_contacts_wait_for_the_opt_outs_the_run_includes(self) -> None:
        self.resend.failures["/contacts"] = [(500, {})] * 10
        run = runs.start_run(self.team.id, "resend", ["opt_outs", "contacts"], API_KEY, self.user.id)

        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "opt_outs", attempt=1)
        with self.assertRaises(ImportStepBlocked):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert self.resend.calls.count("/contacts") == 4

    @parameterized.expand([("rate_limit", 429, {"retry-after": "7"}, 7.0), ("server_error", 503, {}, 2.0)])
    def test_a_passing_failure_waits_and_the_step_completes(
        self, _name: str, status: int, headers: dict[str, str], waited: float
    ) -> None:
        self.resend.failures["/suppressions"] = [(status, headers)]

        run = self._run(["suppressions"])

        assert waited in [call.args[0] for call in self.sleep.call_args_list]
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
        self.resend.failures["/contacts/c0000000-0000-4000-8000-000000000003/topics"] = [(404, {})]

        run = self._run(["topic_opt_outs"])

        assert "/contacts/c0000000-0000-4000-8000-000000000001/topics" in self.resend.calls
        assert run.status == "completed"

    @parameterized.expand([("same_key", API_KEY, 2), ("another_key", "re_another_account_key", 3)])
    def test_a_new_import_continues_the_step_that_failed(self, _name: str, next_key: str, list_reads: int) -> None:
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

        self._run(["suppressions"], api_key=next_key)

        assert len([call for call in self.resend.calls if call == "/suppressions"]) == list_reads

    def test_opt_outs_reach_a_row_another_request_inserted_first(self) -> None:
        MessageRecipientPreference.objects.create(
            team_id=self.team.id, identifier="unsubscribed@example.com", preferences={}
        )

        self._run(["opt_outs"])

        row = MessageRecipientPreference.objects.get(team_id=self.team.id, identifier="unsubscribed@example.com")
        assert row.preferences == {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"}

    def test_importing_again_keeps_every_change_made_in_posthog(self) -> None:
        self._run()
        remove_suppressions(self.team.id, ["gone@example.com"], confirm_complaints=False)
        MessageRecipientPreference.objects.filter(team_id=self.team.id, identifier="unsubscribed@example.com").update(
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_IN"}
        )
        renamed = MessageCategory.objects.get(team_id=self.team.id, name="Product updates")
        renamed.name = "News"
        renamed.save()
        deleted_category = MessageCategory.objects.get(team_id=self.team.id, name__startswith="Nyheter")
        deleted_category.deleted = True
        deleted_category.save()
        edited = MessageTemplate.objects.get(team_id=self.team.id, key="welcome-email")
        edited.content["email"]["subject"] = "Edited here"
        edited.save()
        MessageTemplate.objects.filter(team_id=self.team.id, key="receipt").update(deleted=True)
        templates_before = MessageTemplate.objects.filter(team_id=self.team.id).count()

        run = self._run()

        assert run.progress["opt_outs"]["counts"] == {"opted_out": 0, "already_present": 2, "subscribed": 2}
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
        assert run.progress["automations"]["counts"] == {"already_present": len(FIXTURES["automations"])}

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
        assert email["design"]["body"]["rows"]
        assert welcome.transactional_hog_flow_id is None
        items = {item["label"]: item for item in run.progress["templates"]["items"]}
        assert items["Welcome email"]["url"] == f"/workflows/library/templates/{welcome.id}"
        assert any("{{#if IS_PRO}}" in note and "{{else}}" in note for note in items["Conditional footer"]["notes"])
        imported_key = MessageTemplate.objects.filter(team_id=self.team.id, name__startswith="Přivítání").get().key
        assert imported_key is not None and imported_key.startswith("resend-")

    def test_sender_on_the_same_domain_sends_with_literal_name_and_reply_to(self) -> None:
        sender = IntegrationManager.email.credentials.create(
            self.team.id,
            external_id="team@example.com",
            config={"email": "team@example.com", "domain": "example.com", "verified": True, "name": "Acme"},
            sensitive_config={},
            created_by_id=self.user.id,
        )
        IntegrationManager.email.credentials.create(
            self.team.id,
            external_id="hello@example.com",
            config={"email": "hello@example.com", "domain": "example.com", "verified": False},
            sensitive_config={},
            created_by_id=self.user.id,
        )
        welcome = {
            **FIXTURES["templates"][0],
            "subject": "",
            "from": '"{{ person.properties.a }}" <hello@example.com>',
            "reply_to": ["{{person.properties.b}}@example.com"],
        }
        receipt = {**self.resend.data["templates"][1], "from": "{{ event.properties.secret }}@example.com"}
        self.resend.data = {**self.resend.data, "templates": [welcome, receipt, *self.resend.data["templates"][2:]]}

        run = self._run(["templates"])

        receipt_from = MessageTemplate.objects.get(team_id=self.team.id, key=receipt["alias"]).content["email"]["from"]
        assert receipt_from["email"] == '{{ "{{" }} event.properties.secret }}@example.com'
        email = MessageTemplate.objects.get(team_id=self.team.id, key="welcome-email").content["email"]
        assert (email["from"]["integrationId"], email["from"]["email"]) == (sender.id, "hello@example.com")
        assert email["from"]["name"] == '{{ "{{" }} person.properties.a }}'
        items = {item["label"]: item for item in run.progress["templates"]["items"]}
        assert any("no subject" in note for note in items["Welcome email"]["notes"])
        assert email["replyTo"] == '{{ "{{" }}person.properties.b}}@example.com'

    def test_a_key_a_code_email_sends_under_is_left_to_it(self) -> None:
        TransactionalEmailKey.objects.for_team(self.team.id).create(
            team=self.team, key="welcome-email", hog_flow_id=uuid4()
        )

        run = self._run(["templates"])

        assert not MessageTemplate.objects.filter(team_id=self.team.id, key="welcome-email").exists()
        assert run.progress["templates"]["counts"]["already_present"] == 1
        items = {item["label"]: item for item in run.progress["templates"]["items"]}
        assert items["Welcome email"]["notes"] == [
            "Your app already sends email under the key welcome-email, so this template wasn't imported."
        ]

    def test_automations_become_drafts_with_notes(self) -> None:
        run = self._run(["automations"])

        items = {item["label"]: item for item in run.progress["automations"]["items"]}
        assert items["Welcome series"]["status"] == "created"
        workflow_id = items["Welcome series"]["url"].split("/")[2]
        workflow = get_workflow(
            team_id=self.team.id, workflow_id=workflow_id, user_access_control=None, required_level=None
        )
        assert workflow.status == "draft"
        actions = cast(list[dict[str, Any]], workflow.actions)
        action_types = {action["id"]: action["type"] for action in actions}
        assert action_types["welcome"] == "function_email"
        assert action_types["wait"] == "delay"
        assert action_types["is_pro"] == "conditional_branch"
        is_pro_filters = next(a for a in actions if a["id"] == "is_pro")["config"]["conditions"][0]["filters"]
        # A draft keeps a filter that fails to compile, just without bytecode.
        assert is_pro_filters.get("bytecode")
        is_pro = is_pro_filters["properties"]
        assert is_pro[1] == {
            "key": "toFloat(properties.`min-spend`) IS NOT NULL AND "
            "toFloat(person.properties.`lifetime-spend`) >= toFloat(properties.`min-spend`)",
            "type": "hogql",
        }
        assert action_types["wait_upgrade"] == "wait_until_condition"
        assert action_types["update"] == "function"
        update = next(a for a in actions if a["id"] == "update")["config"]
        assert update["inputs"]["set_properties"]["value"] == {"first_name": "{event.properties['first_name']}"}
        edges = {(edge["from"], edge["to"], edge["type"]) for edge in cast(list[dict[str, Any]], workflow.edges)}
        assert ("wait_upgrade", "receipt", "branch") in edges
        html = next(a for a in actions if a["id"] == "welcome")["config"]["inputs"]["email"]["value"]["html"]
        assert "event.properties.name" in html
        assert '"free"' in html
        assert any("user.created" in note for note in items["Welcome series"]["notes"])
        assert any("couldn't read this email's template" in note for note in items["Re-engagement"]["notes"])
        receipt = next(a for a in actions if a["id"] == "receipt")["config"]["inputs"]["email"]["value"]
        assert receipt["subject"] == "Thanks for upgrading"
        opt_out = next(a for a in actions if a["id"] == "update_opt_out")["config"]
        assert opt_out["template_id"] == "template-posthog-opt-out-of-messages"
        reads = [call for call in self.resend.calls if call.startswith(("/templates/", "/segments/"))]
        assert len(reads) == len(set(reads))

    def test_segments_become_one_static_cohort_that_later_imports_respect(self) -> None:
        run = self._run(["automations"])
        cohort = Cohort.objects.get(team_id=self.team.id, description="Imported from Resend segment seg-1.")
        assert cohort.is_static
        assert cohort.name == "Pro customers (from Resend)"
        items = {item["label"]: item for item in run.progress["automations"]["items"]}
        workflow = get_workflow(
            team_id=self.team.id,
            workflow_id=items["Welcome series"]["url"].split("/")[2],
            user_access_control=None,
            required_level=None,
        )
        tag = next(action for action in cast(list[dict[str, Any]], workflow.actions) if action["id"] == "tag")
        assert tag["config"]["inputs"]["cohort_id"]["value"] == cohort.id

        # A new automation naming the same segment reuses the cohort, and a deleted one stays deleted.
        second = {**FIXTURES["automations"][0], "id": "a0000000-0000-4000-8000-000000000003", "name": "Copy"}
        third = {**FIXTURES["automations"][0], "id": "a0000000-0000-4000-8000-000000000004", "name": "Another copy"}
        self.resend.data = {**self.resend.data, "automations": [*self.resend.data["automations"], second]}
        self._run(["automations"])
        assert Cohort.objects.filter(team_id=self.team.id, description=cohort.description).count() == 1
        Cohort.objects.filter(id=cohort.id).update(deleted=True)
        self.resend.data = {**self.resend.data, "automations": [*self.resend.data["automations"], third]}
        run = self._run(["automations"])

        items = {item["label"]: item for item in run.progress["automations"]["items"]}
        assert any("stays deleted" in note for note in items["Another copy"]["notes"])
        assert Cohort.objects.filter(team_id=self.team.id, description=cohort.description).count() == 1

    def test_step_and_template_senders_stay_literal(self) -> None:
        template = {
            **FIXTURES["templates"][0],
            "from": '"{{ person.properties.a }}" <{{ event.properties.c }}@example.com>',
        }
        step = {"from": '"{{ person.properties.b }}" <{{ event.properties.d }}@example.com>', "subject": "Hi"}

        imported, step_email = resend._imported_email(template, {}), resend._step_email(step, {})
        assert (imported.from_name, imported.from_email) == (
            '{{ "{{" }} person.properties.a }}',
            '{{ "{{" }} event.properties.c }}@example.com',
        )
        assert (step_email.from_name, step_email.from_email) == (
            '{{ "{{" }} person.properties.b }}',
            '{{ "{{" }} event.properties.d }}@example.com',
        )
        assert resend._step_email({**step, "reply_to": ["{{x}}@example.com", "b@example.com"]}, {}).reply_to == (
            '{{ "{{" }}x}}@example.com, b@example.com'
        )

    @parameterized.expand(
        [
            ("unknown_sender", {}, "isn't a PostHog sender yet"),
            ("unverified_sender", {"x@example.com": {"verified": False}}, "isn't verified in PostHog yet"),
            ("verified_sender", {"x@example.com": {"verified": True}}, None),
        ]
    )
    def test_a_step_sender_names_what_to_fix(self, _name: str, configs: dict[str, Any], note: str | None) -> None:
        senders = {
            address: cast(IntegrationRecord, SimpleNamespace(id=7, config={"email": address, **config}))
            for address, config in configs.items()
        }

        notes = resend._step_email({"from": "x@example.com"}, senders).notes

        if note:
            assert len(notes) == 1 and note in notes[0]
        else:
            assert notes == ()

    def test_a_template_keeps_subject_and_sender_notes_apart(self) -> None:
        imported = resend._imported_email({**FIXTURES["templates"][0], "subject": "", "from": ""}, {})

        assert ["no subject" in note for note in imported.subject_notes] == [True]
        assert ["no sender" in note for note in imported.sender_notes] == [True]

    def test_a_template_without_a_display_name_uses_the_senders_name(self) -> None:
        sender = cast(IntegrationRecord, SimpleNamespace(id=7, config={"name": "Acme team", "verified": True}))
        template = {**FIXTURES["templates"][0], "from": "hello@example.com"}

        assert resend._imported_email(template, {"hello@example.com": sender}).from_name == "Acme team"

    def test_a_segment_resend_no_longer_has_leaves_the_step_to_fill_in(self) -> None:
        self.resend.data = {**self.resend.data, "segments": []}
        run = self._run(["automations"])

        items = {item["label"]: item for item in run.progress["automations"]["items"]}
        assert items["Welcome series"]["status"] == "created"
        assert any("no longer exists in Resend" in note for note in items["Welcome series"]["notes"])
        assert not Cohort.objects.filter(team_id=self.team.id, is_static=True).exists()

        self.resend.data = {**self.resend.data, "segments": FIXTURES["segments"]}
        run = self._run(["automations"])

        assert run.progress["automations"]["counts"] == {"already_present": len(FIXTURES["automations"])}
        assert not Cohort.objects.filter(team_id=self.team.id, is_static=True).exists()

    def test_run_state_exposes_summary_for_the_ui(self) -> None:
        run = self._run(["suppressions", "domains"])

        state = get_provider_import_run(self.team.id, run.id)
        assert state is not None
        suppressions, domains = state.steps
        assert [count.key for count in suppressions.counts] == ["bounced", "complained", "manual", "invalid"]
        assert [item.label for item in domains.items] == [domain["name"] for domain in FIXTURES["domains"]]
        org_domain = next(item for item in domains.items if item.label == "mail.example.org")
        assert any("feedback" in note for note in org_domain.notes)


class TestResendContacts(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.resend = FakeResend()
        _sync_email_template()
        client = "products.messaging.backend.services.resend_client"
        for target, kwargs in (
            (f"{client}.requests.get", {"side_effect": self.resend.get}),
            (f"{client}.REQUESTS_PER_SECOND", {"new": 100000}),
            ("products.messaging.backend.provider_imports.runs.start_provider_import_workflow", {}),
        ):
            patcher = patch(target, **kwargs)
            self.addCleanup(patcher.stop)
            patcher.start()
        self.people = PeopleImportRecorder(self)

    @parameterized.expand(
        [
            (
                "with_new_people",
                ["contacts", "new_people", "automations"],
                [
                    ("send Resend contacts", ["unsubscribed@example.com", "left-a-topic@example.com", "user-hal"]),
                    ("fill Pro customers (from Resend)", ["user-hal"]),
                ],
                # The people import only takes addresses Django validates, which leaves out Björk's.
                {"people": 3, "new_people": 2, "skipped_new_people": 0, "dropped": 1},
            ),
            (
                "matching_people_only",
                ["contacts", "automations"],
                [("send Resend contacts", ["user-hal"]), ("fill Pro customers (from Resend)", ["user-hal"])],
                {"people": 1, "new_people": 0, "skipped_new_people": 2, "dropped": 1},
            ),
        ]
    )
    def test_contacts_become_people_once_and_fill_the_cohort_automations_use(
        self, _name: str, steps: list[str], sent: list[tuple[str, list[str]]], counts: dict[str, int]
    ) -> None:
        _create_person(team=self.team, distinct_ids=["user-hal"], properties={"email": "Happy@Example.com"})
        flush_persons_and_events()

        run = runs.start_run(self.team.id, "resend", steps, API_KEY, self.user.id)
        with self.captureOnCommitCallbacks(execute=True):
            for step in run.steps:
                runs.run_step(self.team.id, run.id, step, attempt=1)
        runs.finish_run(self.team.id, run.id)
        run.refresh_from_db()

        assert self.people.imports == sent
        assert self.people.properties["user-hal"] == {
            "email": "happy@example.com",
            "first_name": "Hal",
            "last_name": "Happy",
        }
        assert run.progress["contacts"]["counts"] == counts
        segment_cohorts = Cohort.objects.filter(team_id=self.team.id, description="Imported from Resend segment seg-1.")
        assert segment_cohorts.count() == 1
        workflow = get_workflow(
            team_id=self.team.id,
            workflow_id=next(
                item["url"].split("/")[2]
                for item in run.progress["automations"]["items"]
                if item["label"] == "Welcome series"
            ),
            user_access_control=None,
            required_level=None,
        )
        tag = next(action for action in cast(list[dict[str, Any]], workflow.actions) if action["id"] == "tag")
        assert tag["config"]["inputs"]["cohort_id"]["value"] == segment_cohorts.get().id


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
            ("Hi {{FIRST, {{{NAME|there}}}", False, 'Hi {{ "{{" }}FIRST, {{ variables.NAME | default: "there" }}'),
            ("{{{NAME|a\\b}}}", False, "{{ variables.NAME }}"),
            ("{{{NAME|Tom &amp; Ann}}}", False, "{{ variables.NAME }}"),
            ("{{{NAME|Tom & Ann}}}", False, '{{ variables.NAME | default: "Tom & Ann" }}'),
            ("plain 🦔 text", True, "plain 🦔 text"),
        ]
    )
    def test_converts_tags(self, source: str, is_html: bool, expected: str) -> None:
        assert convert_text(source, {}, is_html=is_html).text == expected

    @parameterized.expand(
        [
            ("integer", 3, "{{ variables.N | default: 3 }}"),
            ("tiny_float", 0.000001, "{{ variables.N | default: 0.000001 }}"),
            ("huge_float", 1e21, "{{ variables.N | default: 1000000000000000000000 }}"),
            ("not_a_number", float("nan"), "{{ variables.N }}"),
        ]
    )
    def test_numeric_fallbacks_stay_valid_liquid(self, _name: str, fallback: float, expected: str) -> None:
        assert convert_text("{{N}}", {"N": fallback}, is_html=False).text == expected

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
