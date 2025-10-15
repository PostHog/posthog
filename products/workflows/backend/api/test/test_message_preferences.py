import json

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.test import Client
from django.urls import reverse

from requests import Response

import posthog.plugins.plugin_server_api as plugin_server_api
from posthog.models.message_category import MessageCategory
from posthog.models.message_preferences import (
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
        self.assertEqual(len(response.context["categories"]), 2)
        self.assertEqual(response.context["token"], self.token)

        # Verify categories are ordered by name
        categories = response.context["categories"]
        self.assertEqual(categories[0]["name"], "Newsletter Updates")
        self.assertEqual(categories[1]["name"], "Product Updates")

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

    def test_update_preferences_missing_token(self):
        response = self.client.post(
            reverse("message_preferences_update"),
            {"preferences[]": [f"{self.category.id}:true"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content), {"error": "Missing token"})

    @patch("posthog.views.validate_messaging_preferences_token")
    def test_update_preferences_invalid_token(self, mock_validate_messaging_preferences_token):
        data = {"token": "invalid-token", "preferences[]": [f"{self.category.id}:true"]}
        mock_validate_messaging_preferences_token.return_value = mock_response(400, {"error": "Invalid token"})
        response = self.client.post(reverse("message_preferences_update"), data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", json.loads(response.content))

    @patch("posthog.views.validate_messaging_preferences_token")
    def test_update_preferences_invalid_preference_format(self, mock_validate_messaging_preferences_token):
        data = {"token": self.token, "preferences[]": ["invalid:format"]}
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
        self.assertEqual(len(data), 0)

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
        self.assertEqual(len(data), 2)

        # Check that the correct recipients are returned
        identifiers = [item["identifier"] for item in data]
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
        self.assertEqual(len(data), 2)

        # Check that only recipients opted out from the specific category are returned
        identifiers = [item["identifier"] for item in data]
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
        self.assertEqual(len(data), 1)

        # Check that all expected fields are present
        item = data[0]
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
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["identifier"], "user1@example.com")
