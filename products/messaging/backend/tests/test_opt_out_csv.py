from io import BytesIO

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)


def csv_upload(content: str, name: str = "opt-outs.csv") -> BytesIO:
    upload = BytesIO(content.encode("utf-8"))
    upload.name = name
    return upload


class TestOptOutCsv(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.category = MessageCategory.objects.create(
            team=self.team, key="newsletter", name="Newsletter", description="Weekly updates"
        )
        self.base_url = f"/api/environments/{self.team.id}/messaging_preferences"

    def _import(self, content: str, **data):
        return self.client.post(
            f"{self.base_url}/import_opt_outs_csv/",
            {"csv_file": csv_upload(content), **data},
            format="multipart",
        )

    def _export(self, **params) -> str:
        response = self.client.get(f"{self.base_url}/export_opt_outs_csv/", params)
        self.assertEqual(response.status_code, 200)
        return b"".join(response.streaming_content).decode("utf-8")

    @parameterized.expand(["identifier", "email", "recipient", "email_address"])
    def test_import_accepts_common_recipient_column_names(self, column: str):
        response = self._import(f"{column}\nally@example.com\n")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["opted_out"], 1)
        preference = MessageRecipientPreference.objects.get(team=self.team, identifier="ally@example.com")
        self.assertEqual(preference.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID), PreferenceStatus.OPTED_OUT)

    def test_import_uses_the_category_named_on_each_row(self):
        other = MessageCategory.objects.create(team=self.team, key="product_updates", name="Product updates")

        response = self._import("email,category_key\nally@example.com,newsletter\nsam@example.com,product_updates\n")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["opted_out"], 2)
        ally = MessageRecipientPreference.objects.get(team=self.team, identifier="ally@example.com")
        sam = MessageRecipientPreference.objects.get(team=self.team, identifier="sam@example.com")
        self.assertEqual(ally.get_preference(str(self.category.id)), PreferenceStatus.OPTED_OUT)
        self.assertEqual(sam.get_preference(str(other.id)), PreferenceStatus.OPTED_OUT)

    def test_import_keeps_preferences_the_file_does_not_mention(self):
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="ally@example.com",
            preferences={str(self.category.id): PreferenceStatus.OPTED_IN.value},
        )

        self._import("email\nally@example.com\n")

        preference = MessageRecipientPreference.objects.get(team=self.team, identifier="ally@example.com")
        self.assertEqual(preference.get_preference(str(self.category.id)), PreferenceStatus.OPTED_IN)
        self.assertEqual(preference.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID), PreferenceStatus.OPTED_OUT)

    def test_import_skips_bad_rows_without_failing_the_whole_file(self):
        response = self._import("email,category_key\nally@example.com,nope\n,newsletter\nsam@example.com,newsletter\n")

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["total_rows"], 3)
        self.assertEqual(result["opted_out"], 1)
        self.assertEqual(result["skipped_rows"], 2)
        self.assertEqual(len(result["errors"]), 2)
        self.assertTrue(
            MessageRecipientPreference.objects.filter(team=self.team, identifier="sam@example.com").exists()
        )
        self.assertFalse(
            MessageRecipientPreference.objects.filter(team=self.team, identifier="ally@example.com").exists()
        )

    def test_import_rejects_an_unknown_default_category(self):
        response = self._import("email\nally@example.com\n", category_key="nope")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(MessageRecipientPreference.objects.filter(team=self.team).exists())

    def test_import_rejects_a_non_csv_file(self):
        response = self.client.post(
            f"{self.base_url}/import_opt_outs_csv/",
            {"csv_file": csv_upload("email\nally@example.com\n", name="opt-outs.txt")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)

    def test_exported_csv_imports_back_unchanged(self):
        self._import("email,category_key\nally@example.com,newsletter\nsam@example.com,newsletter\n")
        exported = self._export(category_key="newsletter")

        MessageRecipientPreference.objects.filter(team=self.team).delete()
        response = self._import(exported)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["opted_out"], 2)
        for identifier in ("ally@example.com", "sam@example.com"):
            preference = MessageRecipientPreference.objects.get(team=self.team, identifier=identifier)
            self.assertEqual(preference.get_preference(str(self.category.id)), PreferenceStatus.OPTED_OUT)

    def test_export_only_returns_opt_outs_for_the_requested_category(self):
        self._import("email,category_key\nally@example.com,newsletter\n")
        self._import("email\nsam@example.com\n")

        newsletter_csv = self._export(category_key="newsletter")
        marketing_csv = self._export()

        self.assertIn("ally@example.com", newsletter_csv)
        self.assertNotIn("sam@example.com", newsletter_csv)
        self.assertIn("sam@example.com", marketing_csv)
        self.assertNotIn("ally@example.com", marketing_csv)

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
