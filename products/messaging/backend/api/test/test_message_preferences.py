import io
import csv
import json

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.test import Client
from django.urls import reverse

from parameterized import parameterized
from requests import Response

import posthog.plugins.plugin_server_api as plugin_server_api

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)


def mock_response(status_code: int, response_json: dict):
    response = Response()
    response.status_code = status_code
    response.json = lambda: response_json  # type: ignore
    return response


class TestMessagePreferencesViews(BaseTest):
    def setUp(self):
        super().setUp()
        team = self.organization.teams.first()
        if not team:
            raise ValueError("Test requires a team")
        self.team = team
        self.category = MessageCategory.objects.create(
            team=self.team, key="newsletter", name="Newsletter Updates", description="Weekly product updates"
        )
        self.category2 = MessageCategory.objects.create(
            team=self.team, key="product_updates", name="Product Updates", description="Product release notes"
        )
        self.recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test@example.com", preferences={}
        )
        self.client = Client()
        self._token_patch = patch.object(
            plugin_server_api, "generate_messaging_preferences_token", return_value="dummy-token"
        )
        self._token_patch.start()
        self.token = plugin_server_api.generate_messaging_preferences_token(self.team.id, self.recipient.identifier)

    def tearDown(self):
        self._token_patch.stop()
        super().tearDown()

    @patch("posthog.views.validate_messaging_preferences_token")
    def test_preferences_page_valid_token(self, mock_validate_messaging_preferences_token):
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )
        response = self.client.get(reverse("message_preferences", kwargs={"token": self.token}))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "message_preferences/preferences.html")

        # Check context
        self.assertEqual(response.context["recipient"], self.recipient)
        self.assertEqual(len(response.context["categories"]), 3)
        self.assertEqual(response.context["token"], self.token)

        # Verify categories are ordered by name
        categories = response.context["categories"]
        self.assertEqual(categories[0]["name"], "Newsletter Updates")
        self.assertEqual(categories[1]["name"], "Product Updates")
        self.assertEqual(categories[2]["name"], "All marketing communications")
        self.assertEqual(categories[2]["id"], ALL_MESSAGE_PREFERENCE_CATEGORY_ID)

    @patch("posthog.views.validate_messaging_preferences_token")
    def test_preferences_page_one_click_unsubscribe_get(self, mock_validate_messaging_preferences_token):
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )

        response = self.client.get(
            reverse("message_preferences", kwargs={"token": self.token}),
            {"one_click_unsubscribe": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "message_preferences/one_click_unsubscribe_success.html")

        self.recipient.refresh_from_db()
        prefs = self.recipient.get_all_preferences()
        self.assertEqual(prefs[str(self.category.id)], PreferenceStatus.OPTED_OUT)
        self.assertEqual(prefs[str(self.category2.id)], PreferenceStatus.OPTED_OUT)
        self.assertEqual(prefs[ALL_MESSAGE_PREFERENCE_CATEGORY_ID], PreferenceStatus.OPTED_OUT)

    @patch("posthog.views.validate_messaging_preferences_token")
    def test_preferences_page_one_click_unsubscribe_post(self, mock_validate_messaging_preferences_token):
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )

        response = self.client.post(
            reverse("message_preferences", kwargs={"token": self.token}),
            {"one_click_unsubscribe": "1"},
        )

        self.assertEqual(response.status_code, 200)

        self.recipient.refresh_from_db()
        prefs = self.recipient.get_all_preferences()
        self.assertEqual(prefs[str(self.category.id)], PreferenceStatus.OPTED_OUT)
        self.assertEqual(prefs[str(self.category2.id)], PreferenceStatus.OPTED_OUT)
        self.assertEqual(prefs[ALL_MESSAGE_PREFERENCE_CATEGORY_ID], PreferenceStatus.OPTED_OUT)

    @patch("posthog.views.validate_messaging_preferences_token")
    def test_preferences_page_invalid_token(self, mock_validate_messaging_preferences_token):
        mock_validate_messaging_preferences_token.return_value = mock_response(400, {"error": "Invalid token"})
        response = self.client.get(reverse("message_preferences", kwargs={"token": "invalid-token"}))
        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, "message_preferences/error.html")

    @patch("posthog.views.validate_messaging_preferences_token")
    def test_update_preferences_valid(self, mock_validate_messaging_preferences_token):
        data = {"token": self.token, "preferences[]": [f"{self.category.id}:true", f"{self.category2.id}:false"]}
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )
        response = self.client.post(reverse("message_preferences_update"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {"success": True})

        # Verify preferences were updated
        self.recipient.refresh_from_db()
        prefs = self.recipient.get_all_preferences()
        self.assertEqual(prefs[str(self.category.id)], PreferenceStatus.OPTED_IN)
        self.assertEqual(prefs[str(self.category2.id)], PreferenceStatus.OPTED_OUT)

    @patch("posthog.views.validate_messaging_preferences_token")
    def test_update_preferences_all_opted_out_adds_all(self, mock_validate_messaging_preferences_token):
        data = {"token": self.token, "preferences[]": [f"{self.category.id}:false", f"{self.category2.id}:false"]}
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )

        response = self.client.post(reverse("message_preferences_update"), data)

        self.assertEqual(response.status_code, 200)
        self.recipient.refresh_from_db()
        prefs = self.recipient.get_all_preferences()
        self.assertEqual(prefs[str(self.category.id)], PreferenceStatus.OPTED_OUT)
        self.assertEqual(prefs[str(self.category2.id)], PreferenceStatus.OPTED_OUT)
        self.assertEqual(prefs[ALL_MESSAGE_PREFERENCE_CATEGORY_ID], PreferenceStatus.OPTED_OUT)

    def test_update_preferences_missing_token(self):
        response = self.client.post(
            reverse("message_preferences_update"),
            {"preferences[]": [f"{self.category.id}:true"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content), {"error": "Missing token"})

    @parameterized.expand(
        [
            ("invalid-token", mock_response(400, {"error": "Invalid token"})),
            ("invalid-token", mock_response(200, {"valid": False})),
        ]
    )
    @patch("posthog.views.validate_messaging_preferences_token")
    def test_update_preferences_invalid_token(
        self, token, mock_response_value, mock_validate_messaging_preferences_token
    ):
        data = {"token": token, "preferences[]": [f"{self.category.id}:true"]}
        mock_validate_messaging_preferences_token.return_value = mock_response_value
        response = self.client.post(reverse("message_preferences_update"), data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", json.loads(response.content))

    @parameterized.expand(["invalid", "TRUE", "", "1"])
    @patch("posthog.views.validate_messaging_preferences_token")
    def test_update_preferences_invalid_preference_format(
        self, invalid_value, mock_validate_messaging_preferences_token
    ):
        data = {"token": self.token, "preferences[]": [f"{self.category.id}:{invalid_value}"]}
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )
        response = self.client.post(reverse("message_preferences_update"), data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content), {"error": "Preference values must be 'true' or 'false'"})


class TestMessagePreferencesAPIViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.category = MessageCategory.objects.create(
            team=self.team, key="newsletter", name="Newsletter Updates", description="Weekly product updates"
        )
        self.category2 = MessageCategory.objects.create(
            team=self.team, key="product_updates", name="Product Updates", description="Product release notes"
        )

    def test_opt_outs_no_category_no_opt_outs(self):
        """Test opt_outs endpoint with no category and no recipients opted out"""
        response = self.client.get(f"/api/environments/{self.team.id}/messaging_preferences/opt_outs/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(len(data["results"]), 0)

    def test_opt_outs_no_category_with_global_opt_outs(self):
        """Test opt_outs endpoint with no category and recipients opted out globally"""
        # Create recipients with global opt-out (using ALL_MESSAGE_PREFERENCE_CATEGORY_ID)
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user1@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
        )
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user2@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
        )
        # Create a recipient who hasn't opted out globally
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user3@example.com",
            preferences={str(self.category.id): PreferenceStatus.OPTED_OUT.value},
        )

        response = self.client.get(f"/api/environments/{self.team.id}/messaging_preferences/opt_outs/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["results"]), 2)

        # Check that the correct recipients are returned
        identifiers = [item["identifier"] for item in data["results"]]
        self.assertIn("user1@example.com", identifiers)
        self.assertIn("user2@example.com", identifiers)
        self.assertNotIn("user3@example.com", identifiers)

    def test_opt_outs_with_specific_category(self):
        """Test opt_outs endpoint with a specific category"""
        # Create recipients with various opt-out preferences
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user1@example.com",
            preferences={str(self.category.id): PreferenceStatus.OPTED_OUT.value},
        )
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user2@example.com",
            preferences={str(self.category2.id): PreferenceStatus.OPTED_OUT.value},
        )
        # Create a recipient who is opted out from the target category
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user3@example.com",
            preferences={str(self.category.id): PreferenceStatus.OPTED_OUT.value},
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/messaging_preferences/opt_outs/", {"category_key": self.category.key}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["results"]), 2)

        # Check that only recipients opted out from the specific category are returned
        identifiers = [item["identifier"] for item in data["results"]]
        self.assertIn("user1@example.com", identifiers)
        self.assertIn("user3@example.com", identifiers)
        self.assertNotIn("user2@example.com", identifiers)

    def test_opt_outs_with_nonexistent_category(self):
        """Test opt_outs endpoint with a category that doesn't exist"""
        response = self.client.get(
            f"/api/environments/{self.team.id}/messaging_preferences/opt_outs/",
            {"category_key": "nonexistent_category"},
        )
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertEqual(data["error"], "Category not found")

    def test_opt_outs_serializer_fields(self):
        """Test that the opt_outs endpoint returns the expected fields"""
        recipient = MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
        )

        response = self.client.get(f"/api/environments/{self.team.id}/messaging_preferences/opt_outs/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(len(data["results"]), 1)

        # Check that all expected fields are present
        item = data["results"][0]
        expected_fields = ["id", "identifier", "updated_at", "preferences"]
        for field in expected_fields:
            self.assertIn(field, item)

        # Check field values
        self.assertEqual(item["id"], str(recipient.id))
        self.assertEqual(item["identifier"], "user@example.com")
        self.assertIsNotNone(item["updated_at"])
        self.assertEqual(item["preferences"], {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value})

    def test_opt_outs_team_isolation(self):
        """Test that opt_outs only returns recipients from the current team"""
        # Create a recipient in the current team
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user1@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
        )

        # Create another team and recipient
        other_team = self.organization.teams.create(name="Other Team")
        MessageRecipientPreference.objects.create(
            team=other_team,
            identifier="user2@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
        )

        response = self.client.get(f"/api/environments/{self.team.id}/messaging_preferences/opt_outs/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["identifier"], "user1@example.com")

    def _parse_export_csv(self, response) -> list[list[str]]:
        return list(csv.reader(io.StringIO(response.content.decode("utf-8"))))

    def test_export_opt_outs_global(self):
        """Global opt-outs export returns a CSV attachment with header + rows for $all opt-outs."""
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user1@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
        )
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user2@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
        )
        # A category-only opt-out should not appear in the global export
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user3@example.com",
            preferences={str(self.category.id): PreferenceStatus.OPTED_OUT.value},
        )

        response = self.client.get(f"/api/environments/{self.team.id}/messaging_preferences/export_opt_outs/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
        self.assertIn("opt-outs-marketing-", response["Content-Disposition"])
        self.assertTrue(response["Content-Disposition"].rstrip('"').endswith(".csv"))

        rows = self._parse_export_csv(response)
        self.assertEqual(rows[0], ["Recipient", "Opt-out date"])
        identifiers = [r[0] for r in rows[1:]]
        self.assertCountEqual(identifiers, ["user1@example.com", "user2@example.com"])

    def test_export_opt_outs_by_category(self):
        """`?category_key=...` returns only that category's opted-out users."""
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user1@example.com",
            preferences={str(self.category.id): PreferenceStatus.OPTED_OUT.value},
        )
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user2@example.com",
            preferences={str(self.category2.id): PreferenceStatus.OPTED_OUT.value},
        )
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user3@example.com",
            preferences={str(self.category.id): PreferenceStatus.OPTED_OUT.value},
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/messaging_preferences/export_opt_outs/",
            {"category_key": self.category.key},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"opt-outs-{self.category.key}-", response["Content-Disposition"])

        rows = self._parse_export_csv(response)
        self.assertEqual(rows[0], ["Recipient", "Opt-out date"])
        identifiers = [r[0] for r in rows[1:]]
        self.assertCountEqual(identifiers, ["user1@example.com", "user3@example.com"])

    def test_export_opt_outs_team_isolation(self):
        """Other teams' opt-outs are not in the CSV."""
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user1@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
        )
        other_team = self.organization.teams.create(name="Other Team")
        MessageRecipientPreference.objects.create(
            team=other_team,
            identifier="leaked@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
        )

        response = self.client.get(f"/api/environments/{self.team.id}/messaging_preferences/export_opt_outs/")
        self.assertEqual(response.status_code, 200)

        rows = self._parse_export_csv(response)
        identifiers = [r[0] for r in rows[1:]]
        self.assertEqual(identifiers, ["user1@example.com"])
        self.assertNotIn("leaked@example.com", identifiers)

    def test_export_opt_outs_excludes_opted_in(self):
        """Recipients with OPTED_IN or NO_PREFERENCE for the category are excluded."""
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="opted-out@example.com",
            preferences={str(self.category.id): PreferenceStatus.OPTED_OUT.value},
        )
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="opted-in@example.com",
            preferences={str(self.category.id): PreferenceStatus.OPTED_IN.value},
        )
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="no-pref@example.com",
            preferences={str(self.category.id): PreferenceStatus.NO_PREFERENCE.value},
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/messaging_preferences/export_opt_outs/",
            {"category_key": self.category.key},
        )
        self.assertEqual(response.status_code, 200)

        rows = self._parse_export_csv(response)
        identifiers = [r[0] for r in rows[1:]]
        self.assertEqual(identifiers, ["opted-out@example.com"])

    def test_export_opt_outs_empty(self):
        """When no opt-outs exist, returns the header row only."""
        response = self.client.get(f"/api/environments/{self.team.id}/messaging_preferences/export_opt_outs/")
        self.assertEqual(response.status_code, 200)

        rows = self._parse_export_csv(response)
        self.assertEqual(rows, [["Recipient", "Opt-out date"]])

    def test_export_opt_outs_unknown_category(self):
        """An unknown `category_key` returns a 404 (matching the `opt_outs` action)."""
        response = self.client.get(
            f"/api/environments/{self.team.id}/messaging_preferences/export_opt_outs/",
            {"category_key": "nonexistent_category"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "Category not found")
