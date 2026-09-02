from collections.abc import Iterator
from typing import Any, cast

from posthog.test.base import APIBaseTest

from django.http import StreamingHttpResponse

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)


class TestOptOuts(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.category = MessageCategory.objects.create(
            team=self.team, key="newsletter", name="Newsletter", description="Weekly updates"
        )
        self.base_url = f"/api/environments/{self.team.id}/messaging_preferences"

    def _bulk(self, opt_outs: list[dict[str, Any]], **data):
        return self.client.post(
            f"{self.base_url}/bulk_add_opt_outs/",
            {"opt_outs": opt_outs, **data},
            format="json",
        )

    def _export(self, **params) -> str:
        response = self.client.get(f"{self.base_url}/export_opt_outs_csv/", params)
        self.assertEqual(response.status_code, 200)
        streamed = cast(StreamingHttpResponse, response).streaming_content
        return b"".join(cast(Iterator[bytes], streamed)).decode("utf-8")

    def test_bulk_opts_recipients_out_of_all_marketing_by_default(self):
        response = self._bulk([{"identifier": "ally@example.com"}, {"identifier": "sam@example.com"}])

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["opted_out"], 2)
        self.assertEqual(result["skipped"], 0)
        for identifier in ("ally@example.com", "sam@example.com"):
            preference = MessageRecipientPreference.objects.get(team=self.team, identifier=identifier)
            self.assertEqual(preference.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID), PreferenceStatus.OPTED_OUT)

    def test_bulk_entry_category_overrides_the_request_default(self):
        other = MessageCategory.objects.create(team=self.team, key="product_updates", name="Product updates")

        response = self._bulk(
            [
                {"identifier": "ally@example.com"},
                {"identifier": "sam@example.com", "category_key": "product_updates"},
            ],
            category_key="newsletter",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["opted_out"], 2)
        ally = MessageRecipientPreference.objects.get(team=self.team, identifier="ally@example.com")
        sam = MessageRecipientPreference.objects.get(team=self.team, identifier="sam@example.com")
        self.assertEqual(ally.get_preference(str(self.category.id)), PreferenceStatus.OPTED_OUT)
        self.assertEqual(sam.get_preference(str(other.id)), PreferenceStatus.OPTED_OUT)

    def test_bulk_keeps_preferences_the_request_does_not_mention(self):
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="ally@example.com",
            preferences={str(self.category.id): PreferenceStatus.OPTED_IN.value},
        )

        self._bulk([{"identifier": "ally@example.com"}])

        preference = MessageRecipientPreference.objects.get(team=self.team, identifier="ally@example.com")
        self.assertEqual(preference.get_preference(str(self.category.id)), PreferenceStatus.OPTED_IN)
        self.assertEqual(preference.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID), PreferenceStatus.OPTED_OUT)

    def test_bulk_skips_unknown_entry_categories_without_failing_the_request(self):
        response = self._bulk(
            [
                {"identifier": "ally@example.com", "category_key": "nope"},
                {"identifier": "sam@example.com", "category_key": "newsletter"},
            ]
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["opted_out"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("nope", result["errors"][0])
        self.assertTrue(
            MessageRecipientPreference.objects.filter(team=self.team, identifier="sam@example.com").exists()
        )
        self.assertFalse(
            MessageRecipientPreference.objects.filter(team=self.team, identifier="ally@example.com").exists()
        )

    def test_bulk_rejects_an_unknown_default_category(self):
        response = self._bulk([{"identifier": "ally@example.com"}], category_key="nope")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(MessageRecipientPreference.objects.filter(team=self.team).exists())

    def test_bulk_counts_a_repeated_recipient_and_category_pair_once(self):
        response = self._bulk([{"identifier": "ally@example.com"}, {"identifier": "ally@example.com"}])

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["opted_out"], 1)
        self.assertEqual(MessageRecipientPreference.objects.filter(team=self.team).count(), 1)

    def test_bulk_rejects_an_empty_list(self):
        response = self._bulk([])

        self.assertEqual(response.status_code, 400)

    def test_bulk_rejects_more_entries_than_the_per_request_limit(self):
        response = self._bulk([{"identifier": f"user{i}@example.com"} for i in range(1001)])

        self.assertEqual(response.status_code, 400)
        self.assertFalse(MessageRecipientPreference.objects.filter(team=self.team).exists())

    def test_export_returns_importable_header_and_only_the_requested_category(self):
        self._bulk([{"identifier": "ally@example.com"}], category_key="newsletter")
        self._bulk([{"identifier": "sam@example.com"}])

        newsletter_csv = self._export(category_key="newsletter")
        marketing_csv = self._export()

        self.assertTrue(newsletter_csv.startswith("identifier,category_key,updated_at"))
        self.assertIn("ally@example.com", newsletter_csv)
        self.assertNotIn("sam@example.com", newsletter_csv)
        self.assertIn("sam@example.com", marketing_csv)
        self.assertNotIn("ally@example.com", marketing_csv)

    def test_export_neutralizes_formula_leading_identifiers(self):
        self._bulk([{"identifier": "=SUM(A1:B1)"}, {"identifier": "ally@example.com"}])

        exported = self._export()

        self.assertIn("'=SUM(A1:B1)", exported)
        self.assertIn("\nally@example.com,", exported)

    def test_export_does_not_leak_opt_outs_from_another_team(self):
        other_team = self.create_team_with_organization(self.organization)
        MessageRecipientPreference.objects.create(
            team=other_team,
            identifier="someone-else@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
        )

        self.assertNotIn("someone-else@example.com", self._export())

    def test_export_rejects_an_unknown_category(self):
        response = self.client.get(f"{self.base_url}/export_opt_outs_csv/", {"category_key": "nope"})

        self.assertEqual(response.status_code, 404)
