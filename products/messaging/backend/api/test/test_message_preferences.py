from posthog.models.message_preferences import MessageRecipientPreference
from posthog.models.message_category import MessageCategory
from posthog.models.message_preferences import PreferenceStatus

from posthog.test.base import BaseTest
from django.test import Client
from django.urls import reverse
import json


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
        self.token = self.recipient.generate_preferences_token()

    def test_preferences_page_valid_token(self):
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

    def test_preferences_page_invalid_token(self):
        response = self.client.get(reverse("message_preferences", kwargs={"token": "invalid-token"}))
        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, "message_preferences/error.html")

    def test_update_preferences_valid(self):
        data = {"token": self.token, "preferences[]": [f"{self.category.id}:true", f"{self.category2.id}:false"]}
        response = self.client.post(reverse("message_preferences_update"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {"success": True})

        # Verify preferences were updated
        self.recipient.refresh_from_db()
        prefs = self.recipient.get_all_preference()
        self.assertEqual(prefs[self.category.id], PreferenceStatus.OPTED_IN)
        self.assertEqual(prefs[self.category2.id], PreferenceStatus.OPTED_OUT)

    def test_update_preferences_missing_token(self):
        response = self.client.post(
            reverse("message_preferences_update"),
            {"preferences[]": [f"{self.category.id}:true"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content), {"error": "Missing token"})

    def test_update_preferences_invalid_token(self):
        data = {"token": "invalid-token", "preferences[]": [f"{self.category.id}:true"]}
        response = self.client.post(reverse("message_preferences_update"), data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", json.loads(response.content))

    def test_update_preferences_invalid_preference_format(self):
        data = {"token": self.token, "preferences[]": ["invalid:format"]}
        response = self.client.post(reverse("message_preferences_update"), data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content), {"error": "Failed to update preferences"})
