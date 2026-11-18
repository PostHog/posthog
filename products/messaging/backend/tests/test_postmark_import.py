import json
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

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
    ImportAccessLost,
    ImportCredentialsInvalid,
    ImportProviderUnavailable,
    ImportTooLarge,
)
from products.messaging.backend.provider_imports.postmark import _merge
from products.messaging.backend.services.postmark_client import PostmarkAPIError, _parse
from products.messaging.backend.services.suppression import remove_suppressions
from products.messaging.backend.temporal.workflow import STEP_RETRY_POLICY
from products.messaging.backend.tests.postmark_fake_server import FIXTURE, FakePostmark, start_server

ALL_STEPS = ["streams", "suppressions", "domains", "webhooks"]
ACCOUNT_TOKEN = "account-token-1111"
PRODUCTION_TOKEN = "server-token-production"


class TestSuppressionMerge(SimpleTestCase):
    @parameterized.expand([("unsubscribe_first", False), ("block_first", True)])
    def test_a_team_block_beats_an_unsubscribe_on_another_stream(self, _name: str, block_first: bool) -> None:
        unsubscribe = {"EmailAddress": "a@example.com", "SuppressionReason": "ManualSuppression", "Origin": "Recipient"}
        block = {**unsubscribe, "Origin": "Customer"}
        merged: dict[str, Any] = {}

        for row in [block, unsubscribe] if block_first else [unsubscribe, block]:
            _merge(merged, [row], is_transactional=False)

        assert merged["a@example.com"].origin == "Customer"

    def test_the_address_budget_stops_a_dump_before_it_holds_more_addresses(self) -> None:
        rows = [
            {"EmailAddress": f"a{index}@example.com", "SuppressionReason": "HardBounce", "Origin": "Recipient"}
            for index in range(5)
        ]
        merged: dict[str, Any] = {}

        with patch("products.messaging.backend.provider_imports.postmark.MAX_SUPPRESSED_ADDRESSES", 2):
            _merge(merged, rows[:2], is_transactional=False)
            _merge(merged, rows[:2], is_transactional=True)
            with self.assertRaises(ImportTooLarge):
                _merge(merged, rows, is_transactional=False)

        assert len(merged) == 2


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
            "/webhooks",
        } <= server
        assert "/message-streams/inbound/suppressions/dump" not in server
        assert "/message-streams/old-news/suppressions/dump" not in server
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
        self._run(["suppressions", "streams"])
        remove_suppressions(self.team.id, ["gone@example.com"], confirm_complaints=False)
        MessageCategory.objects.filter(team_id=self.team.id).update(name="Renamed")

        rerun = self._run(["suppressions", "streams"])

        assert "gone@example.com" not in self._sources()
        assert not MessageCategory.objects.filter(team_id=self.team.id).exclude(name="Renamed").exists()
        assert rerun.progress["suppressions"]["imported"] == 0

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
            runs.start_run(self.team.id, "postmark", ["suppressions"], token, self.user.id)

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
            ("told an hour", {"Retry-After": "3600"}, [3600.0]),
            ("told too long", {"Retry-After": "9000"}, [3600.0]),
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

    @parameterized.expand([("deactivated", "is_active"), ("left_the_organization", "membership")])
    def test_a_starter_who_lost_access_stops_the_step_before_it_writes(self, _name: str, lost: str) -> None:
        run = runs.start_run(self.team.id, "postmark", ["suppressions"], PRODUCTION_TOKEN, self.user.id)
        if lost == "is_active":
            self.user.is_active = False
            self.user.save()
        else:
            self.organization_membership.delete()

        with self.assertRaises(ImportAccessLost):
            runs.run_step(self.team.id, run.id, "suppressions", attempt=1)

        assert not MessageSuppression.objects.for_team(self.team.id).exists()

    def test_a_revoked_token_during_a_step_stops_it_without_a_retry(self) -> None:
        self.fake.fail("/webhooks", 401, body={"ErrorCode": 10, "Message": "Bad token"})
        run = runs.start_run(self.team.id, "postmark", ["webhooks"], PRODUCTION_TOKEN, self.user.id)

        with self.assertRaises(ImportCredentialsInvalid):
            runs.run_step(self.team.id, run.id, "webhooks", attempt=1)

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

        assert "ImportTooLarge" in (STEP_RETRY_POLICY.non_retryable_error_types or [])
        assert self._sources() == {}

    def test_an_unsubscribe_counts_each_recipient_once_however_many_spellings_it_has(self) -> None:
        data = json.loads(FIXTURE.read_text())
        data["servers"] = data["servers"][:1]
        unsubscribe = {"SuppressionReason": "ManualSuppression", "Origin": "Recipient", "CreatedAt": ""}
        data["servers"][0]["suppressions"] = {
            "broadcast": [
                {**unsubscribe, "EmailAddress": "New.Reader@example.com"},
                {**unsubscribe, "EmailAddress": "new.reader@example.com"},
                {**unsubscribe, "EmailAddress": "old.reader@example.com"},
            ]
        }
        self.fake.data = data
        MessageRecipientPreference.objects.create(
            team_id=self.team.id,
            identifier="old.reader@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: "OPTED_OUT"},
        )

        run = self._run(["suppressions"], token=PRODUCTION_TOKEN)

        counts = run.progress["suppressions"]["counts"]
        assert (counts["unsubscribed"], counts["already_present"]) == (1, 1)

    def test_a_passing_server_error_is_retried_inside_the_step(self) -> None:
        self.fake.fail("/webhooks", 503)

        run = self._run(["webhooks"], token=PRODUCTION_TOKEN)

        assert run.status == "completed"
        assert 2 in [call.args[0] for call in self.sleep.call_args_list]

    def test_a_successful_response_that_is_not_json_is_an_error(self) -> None:
        response = requests.Response()
        response.status_code = 200
        response._content = b"<html>maintenance</html>"

        with self.assertRaisesRegex(PostmarkAPIError, "couldn't read"):
            _parse(response)

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
        assert self._sources() == {}

    def test_headers_use_the_kind_the_token_turned_out_to_be(self) -> None:
        self._run(["webhooks"], token=PRODUCTION_TOKEN)

        assert self.fake.requests[0]["server_token"] == PRODUCTION_TOKEN
        assert all(r["account_token"] is None for r in self.fake.requests)
