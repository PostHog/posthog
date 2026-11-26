import json
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext

import requests
from parameterized import parameterized

from posthog.integrations import IntegrationManager

from products.cohorts.backend.models.cohort import Cohort
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
    ImportStepError,
    ImportTooLarge,
)
from products.messaging.backend.provider_imports.sendgrid import (
    NO_MARKETING_CAMPAIGNS_NOTE,
    OPT_OUT_STEPS,
    SENDERS_NEED_FULL_ACCESS,
    SendGridImportProvider,
    missing_scopes_by_step,
    missing_scopes_message,
)
from products.messaging.backend.services.imported_data import carry_opt_outs
from products.messaging.backend.services.sendgrid_client import SendGridAPIError, SendGridClient, _seconds_until_reset
from products.messaging.backend.services.suppression import remove_suppressions
from products.messaging.backend.tests.fake_sendgrid import (
    EMAIL_API_ONLY_KEY,
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
from products.messaging.backend.tests.people_import_recorder import PeopleImportRecorder

CONTACT_STEPS = ["contacts", "new_people"]
# The steps that need neither object storage nor person lookups.
ALL_STEPS = [spec.key for spec in SendGridImportProvider.steps if spec.key not in CONTACT_STEPS]
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
            "grüße.unsub@example.com": {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"},
            "left-updates@example.com": {
                category_ids["sendgrid_101"]: "OPTED_OUT",
                category_ids["sendgrid_102"]: "OPTED_OUT",
            },
            "Björk.Group@example.com": {category_ids["sendgrid_101"]: "OPTED_OUT"},
            "björk.group@example.com": {category_ids["sendgrid_101"]: "OPTED_OUT"},
        }
        assert run.status == "completed"

    @parameterized.expand([("global", "global_unsubscribes"), ("group", "group_unsubscribes")])
    def test_an_opt_out_reaches_every_spelling_of_the_address(self, _name: str, step: str) -> None:
        if step == "global_unsubscribes":
            self.state.account["unsubscribes"] = [{"created": 1, "email": "Mixed.Case@Example.com"}]
        else:
            self.state.account["group_suppressions"] = {"101": ["Mixed.Case@Example.com"], "102": [], "103": []}
        MessageRecipientPreference.objects.create(
            team_id=self.team.id, identifier="MIXED.case@example.com", preferences={}
        )

        self._run([step])

        preferences = self._preferences()
        assert set(preferences) == {"Mixed.Case@Example.com", "mixed.case@example.com", "MIXED.case@example.com"}
        assert len({json.dumps(value, sort_keys=True) for value in preferences.values()}) == 1
        assert all("OPTED_OUT" in value.values() for value in preferences.values())

    def test_group_category_comes_across_with_its_name(self) -> None:
        run = self._run(["suppression_groups"])

        names = set(MessageCategory.objects.filter(team_id=self.team.id).values_list("name", flat=True))
        assert names == {"Product updates", "Événements 🎉", "Empty group"}
        assert any("default group" in warning for warning in run.progress["suppression_groups"]["warnings"])

    def test_finding_every_spelling_of_an_address_has_an_index(self) -> None:
        with CaptureQueriesContext(connection) as queries:
            carry_opt_outs(self.team.id, ["Mixed.Case@Example.com"], self.user.id)

        lookup = next(query["sql"] for query in queries if "LOWER(" in query["sql"])
        assert 'LOWER("posthog_messagerecipientpreference"."identifier")' in lookup
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'posthog_messagerecipientpreference'")
            definitions = [row[0] for row in cursor.fetchall()]
        assert any("(team_id, lower((identifier)::text))" in definition for definition in definitions)

    def test_a_sender_on_a_verified_domain_is_ready(self) -> None:
        IntegrationManager.email.credentials.create(
            self.team.id,
            external_id="team@example.com",
            config={"email": "team@example.com", "domain": "example.com", "verified": True, "name": "Acme"},
            sensitive_config={},
            created_by_id=self.user.id,
        )

        run = self._run(["senders"])

        senders = {item["label"]: item for item in run.progress["senders"]["items"]}
        assert senders["Acme <hello@example.com>"]["notes"] == []
        assert run.progress["senders"]["counts"] == {"ready": 1, "needs_setup": 1}

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
        assert email["subject"] == 'Your order {{ variables.order.id | join: "," }}'
        assert "Old" not in email["html"]
        assert "{% for raw1 in variables.items %}" in email["html"]
        assert '{{ variables.order.placed_at | date: "%B %d, %Y", "UTC" }}' in email["html"]
        assert "{{ unsubscribe_url }}" in email["html"]
        assert '"first_name": "Ada"' in receipt.description
        assert templates["d-4444444444444444444444444444dddd"].content["email"]["html"] == "<p>Newest</p>"

        items = {item["label"]: item for item in run.progress["templates"]["items"]}
        assert any("Old draft" in note for note in items["Order receipt"]["notes"])
        assert not any("can't convert" in note for note in items["Order receipt"]["notes"])
        assert any("{{customHelper name}}" in note for note in items["Přivítání 🦔"]["notes"])
        assert any("design editor" in note for note in items["Přivítání 🦔"]["notes"])
        assert any("no version" in note for note in items["Empty template"]["notes"])
        assert run.progress["templates"]["counts"]["no_version"] == 1

    def test_a_key_a_code_email_sends_under_is_left_to_it(self) -> None:
        key = "sendgrid-design-eeeeeeee-0000-4000-8000-000000000001"
        TransactionalEmailKey.objects.for_team(self.team.id).create(team=self.team, key=key, hog_flow_id=uuid4())

        self._run(["designs"])

        assert not MessageTemplate.objects.filter(team_id=self.team.id, key=key).exists()

    @parameterized.expand(
        [
            (
                "liquid_in_reply_to",
                "hello@example.com",
                "{{person.properties.b}}@example.com",
                "hello@example.com",
                '{{ "{{" }}person.properties.b}}@example.com',
            ),
            (
                "liquid_in_from",
                "{{person.properties.code}}@example.com",
                "",
                '{{ "{{" }}person.properties.code}}@example.com',
                "",
            ),
            (
                "reply_to_is_the_from_address",
                "hello@example.com",
                "hello@example.com",
                "hello@example.com",
                "hello@example.com",
            ),
        ]
    )
    def test_designs_and_single_sends_become_templates_with_notes(
        self, _name: str, from_email: str, reply_to: str, expected_from: str, expected_reply_to: str
    ) -> None:
        IntegrationManager.email.credentials.create(
            self.team.id,
            external_id=from_email,
            config={"email": from_email, "domain": "example.com", "verified": True, "name": "Acme"},
            sensitive_config={},
            created_by_id=self.user.id,
        )
        sender = self.state.account["verified_senders"][0]
        sender.update(from_name="{{ person.properties.a }}", from_email=from_email, reply_to=reply_to)
        run = self._run(["suppression_groups", "designs", "single_sends"])

        templates = {row.name: row for row in MessageTemplate.objects.filter(team_id=self.team.id)}
        assert templates["Newsletter design"].key == "sendgrid-design-eeeeeeee-0000-4000-8000-000000000001"
        scheduled = templates["November news"]
        assert scheduled.content["email"]["from"]["integrationId"]
        assert scheduled.content["email"]["from"]["email"] == expected_from
        assert scheduled.content["email"]["from"]["name"] == '{{ "{{" }} person.properties.a }}'
        assert scheduled.content["email"].get("replyTo", "") == expected_reply_to
        assert str(scheduled.message_category_id) == str(
            MessageCategory.objects.get(team_id=self.team.id, key="sendgrid_101").id
        )
        assert templates["From a design"].content["email"]["html"] == "<p>News</p>{{ unsubscribe_url }}"
        items = {item["label"]: item for item in run.progress["single_sends"]["items"]}
        assert any("still scheduled" in note for note in items["November news"]["notes"])
        assert any("person's property" in note for note in items["November news"]["notes"])
        assert any("A/B test" in note for note in items["From a design"]["notes"])
        assert any("example.com/leave" in note for note in items["From a design"]["notes"])

    def test_a_single_send_takes_its_own_sender_not_the_first_one_listed(self) -> None:
        self.state.account["single_sends"][0]["email_config"]["sender_id"] = 8

        run = self._run(["single_sends"])

        items = {item["label"]: item for item in run.progress["single_sends"]["items"]}
        notes = " ".join(items["November news"]["notes"])
        assert "new@example.org" in notes
        assert "hello@example.com" not in notes

    def test_senders_domains_and_lists_are_listed_with_what_to_do(self) -> None:
        run = self._run(["lists", "senders", "domains"])

        assert run.progress["lists"]["counts"] == {"lists": 3, "contacts": 7}
        assert [item["label"] for item in run.progress["lists"]["items"]] == [
            "Newsletter",
            "Bêta testeurs",
            "Empty list",
        ]
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
            (
                "too_few_scopes",
                NARROW_KEY,
                ["suppressions", "templates"],
                "missing templates.read and templates.versions.read, which the Dynamic and legacy templates step needs",
            ),
            ("no_scopes", NO_SCOPE_KEY, ["domains"], "whitelabel.read"),
        ]
    )
    def test_a_key_that_cannot_read_stops_before_any_run(
        self, _name: str, key: str, steps: list[str], message: str
    ) -> None:
        with self.assertRaisesRegex(ImportCredentialsInvalid, message):
            self._start(steps, key)

        assert not ProviderImportRun.objects.for_team(self.team.id).exists()

    def test_an_account_without_marketing_campaigns_imports_everything_else(self) -> None:
        run = self._run(api_key=EMAIL_API_ONLY_KEY)

        assert run.status == "completed"
        for step in ("single_sends", "lists"):
            assert run.progress[step]["warnings"] == [NO_MARKETING_CAMPAIGNS_NOTE]
        assert not any(path.startswith("/v3/marketing/") for path in self._paths())
        assert len(self._suppressions()) == 6
        assert MessageTemplate.objects.filter(team_id=self.team.id).exists()

    def test_a_narrow_key_can_run_the_steps_it_covers(self) -> None:
        assert self._run(["suppressions"], NARROW_KEY).status == "completed"

    def test_a_scope_lost_during_the_run_names_what_it_cannot_read(self) -> None:
        run = self._start(["templates"])
        self.state.failures["/v3/templates"] = [403]

        with self.assertRaisesRegex(ImportCredentialsInvalid, "/v3/templates"):
            runs.run_step(self.team.id, run.id, "templates", attempt=1)

    def test_a_group_too_large_for_one_import_stops_the_step_without_retrying(self) -> None:
        run = self._start(["group_unsubscribes"])

        with patch(f"{_CLIENT}.MAX_RESPONSE_BYTES", 10), self.assertRaises(ImportTooLarge):
            runs.run_step(self.team.id, run.id, "group_unsubscribes", attempt=1)

    def test_a_body_cut_off_while_it_streams_is_read_again(self) -> None:
        real_request = requests.request
        cut_off: list[str] = []

        def request(method: str, url: str, **kwargs: Any) -> requests.Response:
            response = real_request(method, url, **kwargs)
            if not cut_off and url.endswith("/v3/asm/groups"):
                cut_off.append(url)
                response.iter_content = MagicMock(side_effect=requests.ConnectionError("reset"))  # type: ignore[method-assign]
            return response

        with patch(f"{_CLIENT}.requests.request", side_effect=request):
            run = self._run(["suppression_groups"])

        assert cut_off and run.progress["suppression_groups"]["status"] == "completed"

    def test_a_passing_server_error_is_retried_inside_the_step(self) -> None:
        self.state.failures["/v3/suppression/bounces"] = [503]

        run = self._run(["suppressions"])

        assert run.status == "completed"
        assert len([r for r in self.state.requests if r["path"] == "/v3/suppression/bounces"]) >= 2

    def test_a_key_that_cannot_read_senders_still_finishes_that_step(self) -> None:
        self.state.failures["/v3/verified_senders"] = [403]

        run = self._run(["senders"])

        assert run.status == "completed"
        assert run.progress["senders"]["warnings"] == [SENDERS_NEED_FULL_ACCESS]

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
        assert offsets == ["499", "998"]
        assert run.progress["suppressions"]["status"] == "completed"
        assert run.progress["suppressions"]["counts"]["bounced"] == 1250
        assert len(self._suppressions()) == 1250 + 3

    @parameterized.expand(
        [
            ("bounce_read_before_the_last", "suppressions", "bounces", 3),
            ("bounce_read_last", "suppressions", "bounces", 499),
            ("global_unsubscribe_read_before_the_last", "global_unsubscribes", "unsubscribes", 3),
            ("global_unsubscribe_read_last", "global_unsubscribes", "unsubscribes", 499),
        ]
    )
    def test_an_entry_deleted_in_sendgrid_after_it_was_read_skips_nothing(
        self, _name: str, step: str, list_name: str, deleted_index: int
    ) -> None:
        path = "/v3/suppression/" + list_name
        self.state.account[list_name] = [{"created": 1, "email": f"x{i}@example.com"} for i in range(501)]
        run = self._start([step])
        self.state.fail_after[path] = (1, 503)
        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, step, attempt=1)

        del self.state.account[list_name][deleted_index]
        self.state.fail_after.clear()
        runs.run_step(self.team.id, run.id, step, attempt=2)

        run.refresh_from_db()
        assert run.progress[step]["status"] == "completed"
        imported = set(self._suppressions()) if step == "suppressions" else set(self._preferences())
        assert {"x499@example.com", "x500@example.com"} <= imported

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

    @parameterized.expand(
        [
            ("reordered", lambda emails: emails),
            ("earlier_member_left", lambda emails: emails[1:]),
        ]
    )
    def test_a_group_larger_than_a_page_resumes_at_the_same_address(
        self, _name: str, on_retry: Callable[[list[str]], list[str]]
    ) -> None:
        emails = [f"g{i:04}@example.com" for i in range(1250)]
        self.state.account["group_suppressions"]["101"] = list(reversed(emails))
        run = self._start(["group_unsubscribes"])
        runs._claim_step(self.team.id, run.id, "group_unsubscribes", 1)
        first_page = next(SendGridImportProvider().run_step("group_unsubscribes", self._context(), None))
        runs._save_page(self.team.id, run.id, "group_unsubscribes", 1, first_page)
        self.state.account["group_suppressions"]["101"] = on_retry(emails)

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
        with patch(f"{_CLIENT}.requests.request", wraps=requests.request) as request:
            self._run(["lists"])

        hosts = {urlparse(call.args[1]).hostname for call in request.call_args_list}
        assert hosts == {"127.0.0.1"}
        assert [r["query"].get("page_token") for r in self.state.requests if r["path"] == "/v3/marketing/lists"] == [
            None,
            "1000",
        ]


class TestSendGridContacts(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.state = FakeSendGridState()
        self.server = FakeSendGridServer(self.state, "global")
        self.server.start()
        self.addCleanup(self.server.shutdown)
        settings_override = override_settings(MESSAGING_SENDGRID_API_URL=self.server.url)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        replacements: tuple[tuple[str, dict[str, Any]], ...] = (
            (f"{_CLIENT}.time.sleep", {}),
            (f"{_CLIENT}.REQUESTS_PER_SECOND", {"new": 100000}),
            ("products.messaging.backend.provider_imports.runs.start_provider_import_workflow", {}),
        )
        for target, kwargs in replacements:
            patcher = patch(target, **kwargs)
            self.addCleanup(patcher.stop)
            patcher.start()
        self.people = PeopleImportRecorder(self)

    def _start(self, api_key: str = FULL_KEY) -> ProviderImportRun:
        steps = [*OPT_OUT_STEPS, "contacts", "new_people"]
        run = runs.start_run(self.team.id, "sendgrid", steps, api_key, self.user.id)
        for step in OPT_OUT_STEPS:
            runs.run_step(self.team.id, run.id, step, attempt=1)
        return run

    def _cohorts(self, run: ProviderImportRun) -> dict[str, dict[str, list[str]]]:
        """Each cohort's people, split into its members and those it only sends."""
        run.refresh_from_db()
        progress = run.progress["contacts"]
        plans = {f"/cohorts/{plan['cohort_id']}": plan for plan in progress["people_imports"]}
        cohorts = {}
        for item in progress["items"]:
            if item["url"] not in plans:
                continue
            people = self.people.people(plans[item["url"]])
            cohorts[item["label"]] = {
                "members": sorted(p["properties"]["email"] for p in people if p.get("member", True)),
                "others": sorted(p["properties"]["email"] for p in people if not p.get("member", True)),
            }
        return cohorts

    def _export_requests(self) -> list[dict[str, Any]]:
        return [r for r in self.state.requests if r["path"] == "/v3/marketing/contacts/exports"]

    def test_each_list_fills_a_cohort_without_those_who_unsubscribed(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-ada"], properties={"email": "Ada@example.com"})
        flush_persons_and_events()

        run = self._start()
        runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert self._cohorts(run) == {
            "SendGrid contacts (full-read-key-user)": {
                "members": [
                    "ada@example.com",
                    "gone@example.com",
                    "left-updates@example.com",
                    "nolist@example.com",
                    "zoe@example.com",
                ],
                "others": ["unsubscribed@example.com"],
            },
            "Newsletter (from SendGrid)": {
                "members": ["ada@example.com", "gone@example.com", "left-updates@example.com", "zoe@example.com"],
                "others": ["unsubscribed@example.com"],
            },
            "Bêta testeurs (from SendGrid)": {"members": ["ada@example.com"], "others": ["unsubscribed@example.com"]},
            "Pro plan 🦔 (segment from SendGrid)": {
                "members": ["ada@example.com"],
                "others": ["unsubscribed@example.com"],
            },
        }
        plan = run.progress["contacts"]["people_imports"][0]
        people = {person["properties"]["email"]: person for person in self.people.people(plan)}
        assert people["ada@example.com"]["distinct_id"] == "user-ada"
        assert people["ada@example.com"]["properties"] == {
            "email": "ada@example.com",
            "first_name": "Ada",
            "last_name": "Byron",
            "city": "Springfield",
            "Plan": "pro",
        }
        assert people["zoe@example.com"]["properties"]["last_name"] == 'O\'Neil, "Zo"\nJr'
        assert run.progress["contacts"]["counts"]["invalid_skipped"] == 1
        assert [request["body"] for request in self._export_requests()] == [
            {"file_type": "csv", "notifications": {"email": False}},
            {
                "file_type": "csv",
                "notifications": {"email": False},
                "list_ids": ["11111111-0000-4000-8000-000000000001"],
            },
            {
                "file_type": "csv",
                "notifications": {"email": False},
                "list_ids": ["11111111-0000-4000-8000-000000000002"],
            },
            {
                "file_type": "csv",
                "notifications": {"email": False},
                "list_ids": ["11111111-0000-4000-8000-000000000003"],
            },
            {
                "file_type": "csv",
                "notifications": {"email": False},
                "segment_ids": ["22222222-0000-4000-8000-000000000001"],
            },
        ]
        downloads = [r for r in self.state.requests if r["path"] == "/__exports"]
        assert [(r["authorization"], r["query"]) for r in downloads] == [("", {"signature": "secret", "part": "0"})] * 5

    @parameterized.expand(
        [
            (answer,)
            for answer in ("no_files", "failure", "refused", "empty_file", "header_only", "pending", "unreadable")
        ]
    )
    def test_a_segment_sendgrid_sends_nothing_for_keeps_its_cohort_and_lets_the_rest_import(self, answer: str) -> None:
        run = self._import_twice({"empty_segment": answer, "count": "missing"}, members=False)

        assert self.segment_label not in self._cohorts(run)
        assert "Newsletter (from SendGrid)" in self._cohorts(run)
        assert "Pro plan 🦔 wasn't imported, so its cohort stays as it was" in run.progress["contacts"]["warnings"][0]

    def test_a_segment_export_that_holds_nearly_the_whole_account_keeps_its_cohort(self) -> None:
        for number in range(30):
            self.state.account["contacts"].append(
                {"id": f"x{number}", "email": f"x{number}@example.com", "list_ids": []}
            )
        self.state.account["contact_count"] = {"contact_count": 37}
        run = self._import_twice({"ignores_segments": True, "short_segments": 1}, members=True)

        assert self.segment_label not in self._cohorts(run)
        assert "holds every contact" in run.progress["contacts"]["warnings"][0]

    def test_a_segment_past_the_membership_limit_is_skipped(self) -> None:
        # Every contact, then each list's.
        with patch("products.messaging.backend.provider_imports.sendgrid.MAX_CONTACT_MEMBERSHIPS", 14):
            run = self._start()
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert "Newsletter (from SendGrid)" in self._cohorts(run)
        assert self.segment_label not in self._cohorts(run)
        assert "more contacts than this import has room for" in run.progress["contacts"]["warnings"][0]

    def test_a_segment_past_the_list_limit_is_skipped(self) -> None:
        with patch("products.messaging.backend.provider_imports.sendgrid.MAX_LISTS", 3):
            run = self._start()
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert "Newsletter (from SendGrid)" in self._cohorts(run)
        assert "Pro plan 🦔 wasn't imported" in run.progress["contacts"]["warnings"][0]

    def test_a_segment_export_that_holds_the_whole_account_keeps_its_cohort(self) -> None:
        run = self._import_twice({"ignores_segments": True}, members=True)

        assert self.segment_label not in self._cohorts(run)
        assert "holds every contact" in run.progress["contacts"]["warnings"][0]

    def test_a_segment_export_far_below_its_count_keeps_its_cohort(self) -> None:
        self.state.account["segments"][0]["contacts_count"] = 100
        run = self._import_twice({"count": "missing"}, members=True)

        assert self.segment_label not in self._cohorts(run)
        assert "far fewer contacts" in run.progress["contacts"]["warnings"][0]

    def test_a_skipped_segment_adds_nobody_and_is_not_asked_for_again(self) -> None:
        self.state.export_shape = {"damaged_segment": "late@example.com"}
        run = self._start()
        self.state.fail_after["/v3/suppression/unsubscribes"] = (0, 503)
        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)
        started = len(self.state.exports)
        self.state.fail_after.clear()
        runs.run_step(self.team.id, run.id, "contacts", attempt=2)

        assert len(self.state.exports) == started
        cohorts = self._cohorts(run)
        assert "wasn't imported" in run.progress["contacts"]["warnings"][0]
        assert all("late@example.com" not in cohort["members"] for cohort in cohorts.values())

    def test_a_segment_with_a_long_name_fills_a_cohort(self) -> None:
        self.state.account["segments"][0]["name"] = "S" * 400
        run = self._start()
        runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert f"{'S' * 376} (segment from SendGrid)" in self._cohorts(run)

    def test_a_segment_sendgrid_counts_as_empty_empties_its_cohort(self) -> None:
        run = self._import_twice({"empty_segment": "counted"}, members=False)

        assert self._cohorts(run)[self.segment_label] == {"members": [], "others": []}

    segment_label = "Pro plan 🦔 (segment from SendGrid)"

    def _import_twice(self, shape: dict[str, Any], *, members: bool) -> ProviderImportRun:
        """The second run, after a first one gave the segment's cohort its people."""
        first = self._start()
        runs.run_step(self.team.id, first.id, "contacts", attempt=1)
        assert "ada@example.com" in self._cohorts(first)[self.segment_label]["members"]
        runs.finish_run(self.team.id, first.id)
        for contact in self.state.account["contacts"]:
            if not members:
                contact.pop("segment_ids", None)
        self.state.export_shape = shape
        run = self._start()
        with patch("products.messaging.backend.provider_imports.sendgrid.EXPORT_TIMEOUT_SECONDS", 0.2):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)
        run.refresh_from_db()
        return run

    def test_a_segment_of_the_first_version_fills_a_cohort_too(self) -> None:
        del self.state.account["segments"][0]["query_version"]
        run = self._start()
        runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert "ada@example.com" in self._cohorts(run)["Pro plan 🦔 (segment from SendGrid)"]["members"]

    def test_a_second_account_fills_a_cohort_of_its_own(self) -> None:
        self.state.second_account.update(
            contacts=[{"id": "s1", "email": "second@example.com", "first_name": "", "last_name": "", "list_ids": []}],
            contact_count={"contact_count": 1},
        )
        first = self._start()
        runs.run_step(self.team.id, first.id, "contacts", attempt=1)
        runs.finish_run(self.team.id, first.id)
        second = self._start(SECOND_ACCOUNT_KEY)
        runs.run_step(self.team.id, second.id, "contacts", attempt=1)

        assert list(self._cohorts(second)) == ["SendGrid contacts (second-account-key-user)"]
        first.refresh_from_db()
        assert {plan["cohort_id"] for plan in first.progress["contacts"]["people_imports"]}.isdisjoint(
            plan["cohort_id"] for plan in second.progress["contacts"]["people_imports"]
        )

    def test_someone_who_leaves_after_the_opt_out_steps_is_not_mailable(self) -> None:
        run = self._start()
        self.state.account["unsubscribes"].append({"created": 1700005000, "email": "Ada@example.com"})
        self.state.account["spam_reports"].append({"created": 1700005000, "email": "zoe@example.com"})
        self.state.account["group_suppressions"]["103"].append("nolist@example.com")
        runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert MessageSuppression.objects.for_team(self.team.id).filter(identifier="zoe@example.com").exists()
        category = MessageCategory.objects.get(team_id=self.team.id, key="sendgrid_103")
        left = MessageRecipientPreference.objects.get(team_id=self.team.id, identifier="nolist@example.com")
        assert left.preferences == {str(category.id): "OPTED_OUT"}
        assert (
            "bounced"
            not in ProviderImportRun.objects.for_team(self.team.id).get(id=run.id).progress["contacts"]["counts"]
        )

        assert all("ada@example.com" not in cohort["members"] for cohort in self._cohorts(run).values())
        opted_out = MessageRecipientPreference.objects.filter(
            team_id=self.team.id, preferences__contains={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"}
        ).values_list("identifier", flat=True)
        assert {"ada@example.com", "Ada@example.com"} <= set(opted_out)

    def test_a_list_sendgrid_wrongly_counts_as_empty_still_fills_its_cohort(self) -> None:
        self.state.account["lists"][1]["contact_count"] = 0
        run = self._start()
        runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert self._cohorts(run)["Bêta testeurs (from SendGrid)"]["members"] == ["ada@example.com"]

    def test_an_empty_list_with_an_unreadable_export_lets_the_rest_import(self) -> None:
        self.state.export_shape = {"empty_list": "unreadable"}
        run = self._start()
        runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert "Newsletter (from SendGrid)" in self._cohorts(run)
        assert "Empty list wasn't imported" in run.progress["contacts"]["warnings"][0]

    def test_an_account_without_contacts_keeps_every_cohort(self) -> None:
        self.state.account["contact_count"] = {"contact_count": 0}
        for row in self.state.account["lists"]:
            row["contact_count"] = 0
        self.state.export_status = "failure"
        run = self._start()
        runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        run.refresh_from_db()
        assert "every cohort stays as it was" in run.progress["contacts"]["warnings"][0]
        assert not self.people.stored

    def test_an_empty_export_of_an_account_whose_count_lags_empties_nothing(self) -> None:
        run = self._start()
        self.state.account["contact_count"] = {"contact_count": 0}
        self.state.export_damage = "empty"

        with self.assertRaisesRegex(ImportProviderUnavailable, "holds none of 6 contacts"):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

    def test_a_retry_downloads_the_exports_that_started_and_starts_only_the_rest(self) -> None:
        run = self._start()
        self.state.fail_after["/v3/marketing/contacts/exports"] = (2, 503)
        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)
        assert not self.people.stored
        started = len(self.state.exports)

        self.state.fail_after.clear()
        runs.run_step(self.team.id, run.id, "contacts", attempt=2)

        assert (started, len(self.state.exports)) == (2, 5)
        assert len(self._cohorts(run)) == 4

    @parameterized.expand(
        [
            ("cut_off_file", {"export_damage": "bytes"}, "arrived incomplete"),
            ("cut_off_connection", {"export_damage": "connection"}, "arrived incomplete"),
            ("nothing_exported", {"export_damage": "empty"}, "holds none of 7 contacts"),
            ("extra_rows", {"export_damage": "extra"}, "holds 8 contacts, but says it holds 7"),
            ("missing_rows", {"export_damage": "rows"}, "holds 6 contacts, but says it holds 7"),
            ("failed_export", {"export_status": "failure"}, "couldn't export your contacts"),
        ]
    )
    def test_a_partial_export_leaves_every_cohort_alone_and_a_retry_can_finish(
        self, _name: str, damage: dict[str, str], message: str
    ) -> None:
        run = self._start()
        for name, value in damage.items():
            setattr(self.state, name, value)
        with self.assertRaisesRegex(ImportStepError, message):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)
        assert not self.people.stored
        assert not Cohort.objects.filter(team_id=self.team.id).exists()

        self.state.export_damage, self.state.export_status = None, "ready"
        runs.run_step(self.team.id, run.id, "contacts", attempt=2)

        assert len(self._cohorts(run)) == 4

    @parameterized.expand(
        [
            ("plain", {"packed": False}),
            ("bom", {"packed": False, "bom": True}),
            ("several_files", {"files": 3}),
            ("several_files_with_one_header", {"files": 3, "header_in_each_file": False}),
            ("more_files_than_contacts", {"files": 9, "header_in_each_file": False}),
            ("lowercase_headers", {"header": "lower"}),
            ("spaced_headers", {"header": "spaced"}),
            ("custom_fields_by_id", {"header": "field_ids"}),
            ("columns_in_another_order", {"reversed": True}),
            ("every_column", {"all_columns": True}),
            ("no_count", {"count": "missing"}),
            ("null_count", {"count": "null"}),
        ]
    )
    def test_every_shape_an_export_can_have_imports_the_same_people(self, _name: str, shape: dict[str, Any]) -> None:
        self.state.account["contacts"][0].update(
            alternate_emails=["other@example.com"], list_ids=["11111111-0000-4000-8000-000000000001"], external_id="x"
        )
        self.state.account["lists"][1]["contact_count"] = 1
        self.state.account["contacts"][1]["custom_fields"]["Plan"] = "email"
        self.state.export_shape = shape
        run = self._start()
        runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        cohorts = self._cohorts(run)
        assert len(cohorts) == 4
        assert "ada@example.com" in cohorts["Newsletter (from SendGrid)"]["members"]
        assert cohorts["Bêta testeurs (from SendGrid)"] == {"members": [], "others": ["unsubscribed@example.com"]}
        people = {
            p["properties"]["email"]: p for p in self.people.people(run.progress["contacts"]["people_imports"][0])
        }
        assert len(people) == 6
        assert people["ada@example.com"]["properties"] == {
            "email": "ada@example.com",
            "first_name": "Ada",
            "last_name": "Byron",
            "city": "Springfield",
            "Plan": "pro",
        }

    @parameterized.expand([("small_account", 5, 2), ("large_account", 30, 2), ("uncounted_list", 5, None)])
    def test_a_list_export_that_holds_the_whole_account_leaves_every_cohort_alone(
        self, _name: str, others: int, list_count: int | None
    ) -> None:
        for number in range(others):
            self.state.account["contacts"].append(
                {"id": f"x{number}", "email": f"x{number}@example.com", "list_ids": []}
            )
        self.state.account["contact_count"] = {"contact_count": len(self.state.account["contacts"])}
        for row in self.state.account["lists"]:
            row["contact_count"] = list_count
        self.state.export_shape = {"ignores_filter": True}
        self._assert_fails_without_saving("SendGrid counts|SendGrid doesn't count")

    @parameterized.expand([("with_a_count", "stated", 40), ("without_a_count", "missing", 9)])
    def test_a_list_export_far_below_its_count_leaves_every_cohort_alone(
        self, _name: str, stated: str, list_count: int
    ) -> None:
        self.state.account["lists"][0]["contact_count"] = list_count
        self.state.account["contact_count"] = {}
        self.state.export_shape = {"count": stated}
        self._assert_fails_without_saving("but SendGrid counts")

    @parameterized.expand(
        [
            ("too_many", {"lists": 3}),
            ("uncounted_list", {"lists": None}),
            ("account_slightly_short", {"account": 20}),
        ]
    )
    def test_an_export_near_its_count_is_still_refused_when_nothing_else_vouches_for_it(
        self, _name: str, counts: dict[str, int | None]
    ) -> None:
        if "lists" in counts:
            self.state.account["lists"][0]["contact_count"] = counts["lists"]
        else:
            self.state.account["contact_count"] = {"contact_count": counts["account"]}
        self.state.export_shape = {"count": "missing"}
        self._assert_fails_without_saving("SendGrid counts|SendGrid doesn't count")

    def test_an_account_export_below_its_count_is_refused_even_when_it_counts_itself(self) -> None:
        self.state.account["contact_count"] = {"contact_count": 13}
        self._assert_fails_without_saving("holds 7 contacts, but SendGrid counts 13")

    def test_an_empty_export_of_an_account_without_counts_leaves_every_cohort_alone(self) -> None:
        self.state.account["contact_count"] = {}
        for row in self.state.account["lists"]:
            row["contact_count"] = None
        self.state.export_damage = "empty"
        self._assert_fails_without_saving("holds no contacts")

    def test_an_export_without_a_valid_email_leaves_every_cohort_alone(self) -> None:
        for contact in self.state.account["contacts"]:
            contact["email"] = "not an email"
        self._assert_fails_without_saving("no valid email")

    def _assert_fails_without_saving(self, message: str) -> None:
        run = self._start()
        with self.assertRaisesRegex(ImportStepError, message):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)
        assert not self.people.stored
        assert not Cohort.objects.filter(team_id=self.team.id).exists()

    def test_a_list_without_emails_keeps_its_cohort_and_lets_the_rest_import(self) -> None:
        first = self._start()
        runs.run_step(self.team.id, first.id, "contacts", attempt=1)
        runs.finish_run(self.team.id, first.id)
        for contact in self.state.account["contacts"]:
            contact["list_ids"] = [i for i in contact["list_ids"] if i != "11111111-0000-4000-8000-000000000002"]
        self.state.account["contacts"][6]["list_ids"].append("11111111-0000-4000-8000-000000000002")
        run = self._start()
        runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert "Bêta testeurs (from SendGrid)" not in self._cohorts(run)
        assert "Newsletter (from SendGrid)" in self._cohorts(run)
        assert "Bêta testeurs wasn't imported" in run.progress["contacts"]["warnings"][0]

    def test_a_redirected_download_is_never_followed(self) -> None:
        run = self._start()
        self.state.failures["/__exports"] = [302]
        with self.assertRaisesRegex(ImportProviderUnavailable, "HTTP 302") as raised:
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)
        assert "signature" not in str(raised.exception)

        runs.run_step(self.team.id, run.id, "contacts", attempt=2)

        assert len(self._cohorts(run)) == 4

    def test_exports_that_expired_are_all_started_again_in_one_attempt(self) -> None:
        run = self._start()
        self.state.failures["/__exports"] = [403, 200, 403, 200, 403, 200]
        runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert len(self.state.exports) == 5 + 3
        assert len(self._cohorts(run)) == 4

    def test_a_download_that_trickles_stops_at_its_deadline(self) -> None:
        self.state.trickle_seconds = 0.1
        started = time.monotonic()
        with (
            patch(f"{_CLIENT}.MAX_DOWNLOAD_SECONDS", 0.3),
            self.assertRaisesRegex(SendGridAPIError, "took too long"),
            SendGridClient(FULL_KEY, self.server.url).download(f"{self.server.url}/__trickle"),
        ):
            pass

        # The whole file takes 4 seconds.
        assert time.monotonic() - started < 2

    def test_an_export_past_the_size_limit_stops_the_step_without_a_retry(self) -> None:
        run = self._start()
        with patch(f"{_CLIENT}.MAX_DOWNLOAD_BYTES", 300), self.assertRaises(ImportTooLarge):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        assert len([r for r in self.state.requests if r["path"] == "/__exports"]) == 1

    def test_an_export_that_stays_pending_is_checked_again_rather_than_started_again(self) -> None:
        run = self._start()
        self.state.export_pending_checks = 5
        with (
            patch("products.messaging.backend.provider_imports.sendgrid.EXPORT_TIMEOUT_SECONDS", 0),
            self.assertRaisesRegex(ImportProviderUnavailable, "hasn't finished"),
        ):
            runs.run_step(self.team.id, run.id, "contacts", attempt=1)

        runs.run_step(self.team.id, run.id, "contacts", attempt=2)

        assert len(self.state.exports) == 5

    @parameterized.expand(
        [
            ("http", "http://example.com/x.csv"),
            ("private_address", "https://127.0.0.1/x.csv"),
            ("malformed", "https://[x"),
        ]
    )
    def test_a_link_to_an_unsafe_address_is_refused(self, _name: str, url: str) -> None:
        with self.assertRaisesRegex(SendGridAPIError, "won't follow"):
            with SendGridClient(FULL_KEY, self.server.url).download(url):
                pass

    def test_a_new_run_with_contacts_reads_opt_outs_from_the_start(self) -> None:
        failed = runs.start_run(
            self.team.id, "sendgrid", [*OPT_OUT_STEPS, "contacts", "new_people"], FULL_KEY, self.user.id
        )
        self.state.fail_after["/v3/asm/groups/102/suppressions"] = (0, 503)
        with self.assertRaises(ImportProviderUnavailable):
            runs.run_step(self.team.id, failed.id, "group_unsubscribes", attempt=1)
        runs.finish_run(self.team.id, failed.id)
        self.state.fail_after.clear()
        # Sorts before the address the failed run stopped at.
        self.state.account["group_suppressions"]["101"].append("ada@example.com")

        self._start()

        preferences = MessageRecipientPreference.objects.get(team_id=self.team.id, identifier="ada@example.com")
        category = MessageCategory.objects.get(team_id=self.team.id, key="sendgrid_101")
        assert preferences.preferences == {str(category.id): "OPTED_OUT"}

    def test_a_key_without_marketing_campaigns_imports_no_contacts(self) -> None:
        steps = [*OPT_OUT_STEPS, "contacts", "new_people"]
        run = runs.start_run(self.team.id, "sendgrid", steps, EMAIL_API_ONLY_KEY, self.user.id)
        for step in steps:
            runs.run_step(self.team.id, run.id, step, attempt=1)

        run.refresh_from_db()
        assert run.progress["contacts"]["warnings"] == [NO_MARKETING_CAMPAIGNS_NOTE]
        assert not self.people.stored
        assert not self._export_requests()


class TestSendGridKeys(SimpleTestCase):
    def test_scopes_need_the_broad_suppression_scope(self) -> None:
        assert missing_scopes_by_step({"suppression.read"}, ["suppressions", "global_unsubscribes"]) == {}
        per_list = {"suppression.bounces.read", "suppression.invalid_emails.read", "suppression.spam_reports.read"}
        assert missing_scopes_by_step(per_list, ["suppressions"]) == {"suppression.read": ["suppressions"]}
        assert missing_scopes_by_step({"asm.groups.read"}, ["group_unsubscribes"]) == {
            "suppression.read": ["group_unsubscribes"]
        }
        assert missing_scopes_by_step({"marketing.read"}, ["single_sends"]) == {"design_library.read": ["single_sends"]}

    @parameterized.expand(
        [
            # A key with any marketing scope belongs to a Marketing Campaigns account, so the missing one can be added.
            ("partial_marketing", {"marketing.automation.read"}, ["lists"], {"marketing.read": ["lists"]}),
            (
                "account_name",
                {"marketing.read", "suppression.read", "asm.groups.read"},
                ["contacts"],
                {"user.username.read": ["contacts"]},
            ),
            ("no_marketing_campaigns", {"design_library.read"}, ["single_sends", "lists"], {}),
            ("design_still_needed", set(), ["single_sends", "designs"], {"design_library.read": ["designs"]}),
        ]
    )
    def test_marketing_steps_only_need_a_scope_the_account_can_grant(
        self, _name: str, scopes: set[str], steps: list[str], expected: dict[str, list[str]]
    ) -> None:
        assert missing_scopes_by_step(scopes, steps) == expected

    @parameterized.expand(
        [
            (
                "one_scope_one_step",
                {"whitelabel.read": ["domains"]},
                "This SendGrid API key is missing whitelabel.read, which the Authenticated domains step needs. Add it "
                "in SendGrid, or turn off that step.",
            ),
            (
                "one_scope_two_steps",
                {"suppression.read": ["suppressions", "global_unsubscribes"]},
                "This SendGrid API key is missing suppression.read, which the Bounces, invalid addresses and spam "
                "reports and Global unsubscribes steps need. Add it in SendGrid, or turn off those steps.",
            ),
            (
                "scopes_for_different_steps",
                {"suppression.read": ["suppressions"], "whitelabel.read": ["domains"]},
                "This SendGrid API key is missing suppression.read (for Bounces, invalid addresses and spam reports) "
                "and whitelabel.read (for Authenticated domains). Add them in SendGrid, or turn off the steps that need "
                "them.",
            ),
        ]
    )
    def test_missing_scope_message_names_the_steps(
        self, _name: str, missing: dict[str, list[str]], expected: str
    ) -> None:
        assert missing_scopes_message(missing, SendGridImportProvider.steps) == expected

    @parameterized.expand([("seconds_left", "37", 37.0), ("unix_time", "1700000060", 60.0)])
    def test_rate_limit_reset_reads_both_header_formats(self, _name: str, header: str, expected: float) -> None:
        response = requests.Response()
        response.headers["X-RateLimit-Reset"] = header
        with patch(f"{_CLIENT}.time.time", return_value=1700000000.0):
            assert _seconds_until_reset(response) == expected

    def test_client_repr_hides_the_key(self) -> None:
        assert FULL_KEY not in repr(SendGridClient(FULL_KEY, "https://example.com"))
