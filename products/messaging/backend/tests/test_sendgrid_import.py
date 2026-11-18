import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

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
from products.messaging.backend.models.provider_import_run import ProviderImportRun
from products.messaging.backend.provider_imports import runs
from products.messaging.backend.provider_imports.base import (
    ImportCredentialsInvalid,
    ImportProviderUnavailable,
    ImportTooLarge,
)
from products.messaging.backend.provider_imports.sendgrid import (
    SENDERS_NEED_FULL_ACCESS,
    SendGridImportProvider,
    missing_scopes,
)
from products.messaging.backend.services.sendgrid_client import SendGridClient, _seconds_until_reset
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
)

ALL_STEPS = [spec.key for spec in SendGridImportProvider.steps]
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

    def test_requests_match_the_documented_endpoints_and_headers(self) -> None:
        self._run()

        for request in self.state.requests:
            assert request["authorization"] == f"Bearer {FULL_KEY}"
            assert request["accept"] == "application/json"
            assert request["region"] == "global"
        bounces = next(r for r in self.state.requests if r["path"] == "/v3/suppression/bounces")
        assert bounces["query"]["limit"] == "500"
        assert "end_time" in bounces["query"]

    @parameterized.expand(
        [
            ("wrong_key", "SG.nope", ["suppressions"], "SendGrid rejected this API key"),
            ("too_few_scopes", NARROW_KEY, ["suppressions", "domains"], "whitelabel.read"),
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
        run = self._start(["domains"])
        self.state.failures["/v3/whitelabel/domains"] = [403]

        with self.assertRaisesRegex(ImportCredentialsInvalid, "/v3/whitelabel/domains"):
            runs.run_step(self.team.id, run.id, "domains", attempt=1)

    def test_a_group_too_large_for_one_import_stops_the_step_without_retrying(self) -> None:
        run = self._start(["group_unsubscribes"])

        with patch(f"{_CLIENT}.MAX_RESPONSE_BYTES", 10), self.assertRaises(ImportTooLarge):
            runs.run_step(self.team.id, run.id, "group_unsubscribes", attempt=1)

    def test_a_body_cut_off_while_it_streams_is_read_again(self) -> None:
        real_get = requests.get
        cut_off: list[str] = []

        def get(url: str, **kwargs: Any) -> requests.Response:
            response = real_get(url, **kwargs)
            if not cut_off and url.endswith("/v3/asm/groups"):
                cut_off.append(url)
                response.iter_content = MagicMock(side_effect=requests.ConnectionError("reset"))  # type: ignore[method-assign]
            return response

        with patch(f"{_CLIENT}.requests.get", side_effect=get):
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

        run = self._run()

        assert not MessageSuppression.objects.for_team(self.team.id).get(identifier="gone@example.com").suppressed
        assert self._preferences()["unsubscribed@example.com"][ALL_MESSAGE_PREFERENCE_CATEGORY_ID] == "OPTED_IN"
        renamed.refresh_from_db()
        assert renamed.name == "News"
        deleted_category.refresh_from_db()
        assert deleted_category.deleted
        assert run.status == "completed"

    def test_an_empty_account_completes_with_nothing_imported(self) -> None:
        run = self._run(api_key=EMPTY_ACCOUNT_KEY)

        assert run.status == "completed"
        assert all(run.progress[step]["imported"] == 0 for step in ALL_STEPS)

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


class TestSendGridKeys(SimpleTestCase):
    def test_scopes_need_the_broad_suppression_scope(self) -> None:
        assert missing_scopes({"suppression.read"}, ["suppressions", "global_unsubscribes"]) == []
        per_list = {"suppression.bounces.read", "suppression.invalid_emails.read", "suppression.spam_reports.read"}
        assert missing_scopes(per_list, ["suppressions"]) == ["suppression.read"]
        assert missing_scopes({"asm.groups.read"}, ["group_unsubscribes"]) == ["suppression.read"]

    @parameterized.expand([("seconds_left", "37", 37.0), ("unix_time", "1700000060", 60.0)])
    def test_rate_limit_reset_reads_both_header_formats(self, _name: str, header: str, expected: float) -> None:
        response = requests.Response()
        response.headers["X-RateLimit-Reset"] = header
        with patch(f"{_CLIENT}.time.time", return_value=1700000000.0):
            assert _seconds_until_reset(response) == expected

    def test_client_repr_hides_the_key(self) -> None:
        assert FULL_KEY not in repr(SendGridClient(FULL_KEY, "https://example.com"))
