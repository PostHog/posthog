import json

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.test import Client
from django.urls import reverse

from parameterized import parameterized
from requests import Response
from rest_framework import status

import posthog.plugins.plugin_server_api as plugin_server_api
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    EMAIL_TRACKING_PREFERENCE_ID,
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

    def _enable_engagement_events(self):
        config = self.team.workflows_config
        config.capture_workflows_engagement_events = True
        config.save()

    @patch("posthog.views.capture_internal")
    @patch("posthog.views.validate_messaging_preferences_token")
    def test_one_click_unsubscribe_emits_unsubscribed_event(
        self, mock_validate_messaging_preferences_token, mock_capture_internal
    ):
        self._enable_engagement_events()
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )

        response = self.client.get(
            reverse("message_preferences", kwargs={"token": self.token}),
            {"one_click_unsubscribe": "1"},
        )

        self.assertEqual(response.status_code, 200)
        mock_capture_internal.assert_called_once_with(
            token=self.team.api_token,
            event_name="$workflows_email_unsubscribed",
            event_source="workflows_unsubscribe",
            distinct_id=self.recipient.identifier,
            properties={
                "$email": self.recipient.identifier,
                "category": ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
                "source": "one_click",
            },
        )

        # A replay (scanner prefetch, reused token) is not a transition and must not emit again
        mock_capture_internal.reset_mock()
        response = self.client.get(
            reverse("message_preferences", kwargs={"token": self.token}),
            {"one_click_unsubscribe": "1"},
        )
        self.assertEqual(response.status_code, 200)
        mock_capture_internal.assert_not_called()

    @patch("posthog.views.capture_internal")
    @patch("posthog.views.validate_messaging_preferences_token")
    def test_update_preferences_emits_only_for_newly_opted_out(
        self, mock_validate_messaging_preferences_token, mock_capture_internal
    ):
        self._enable_engagement_events()
        # category is already opted out, so only category2 and $all are genuine transitions;
        # the bogus id must be dropped because it isn't one of the team's categories
        self.recipient.preferences = {
            str(self.category.id): PreferenceStatus.OPTED_OUT.value,
            str(self.category2.id): PreferenceStatus.OPTED_IN.value,
        }
        self.recipient.save()
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )

        data = {
            "token": self.token,
            "preferences[]": [
                f"{self.category.id}:false",
                f"{self.category2.id}:false",
                "not-a-real-category:false",
            ],
        }
        response = self.client.post(reverse("message_preferences_update"), data)

        self.assertEqual(response.status_code, 200)
        emitted_categories = [call.kwargs["properties"]["category"] for call in mock_capture_internal.call_args_list]
        self.assertEqual(
            sorted(emitted_categories), sorted([str(self.category2.id), ALL_MESSAGE_PREFERENCE_CATEGORY_ID])
        )
        for call in mock_capture_internal.call_args_list:
            self.assertEqual(call.kwargs["properties"]["source"], "preferences_page")

    @parameterized.expand(["one_click", "preferences_form"])
    @patch("posthog.views.capture_internal")
    @patch("posthog.views.validate_messaging_preferences_token")
    def test_no_unsubscribed_event_when_flag_off(
        self, code_path, mock_validate_messaging_preferences_token, mock_capture_internal
    ):
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )

        if code_path == "one_click":
            response = self.client.get(
                reverse("message_preferences", kwargs={"token": self.token}),
                {"one_click_unsubscribe": "1"},
            )
        else:
            response = self.client.post(
                reverse("message_preferences_update"),
                {"token": self.token, "preferences[]": [f"{self.category.id}:false"]},
            )

        self.assertEqual(response.status_code, 200)
        mock_capture_internal.assert_not_called()

    def _set_tracking_consent_mode(self, mode: str):
        config = self.team.workflows_config
        config.email_tracking_consent_mode = mode
        config.save()

    @parameterized.expand(
        [
            # (consent mode, stored preference, section shown, toggle checked)
            ("off", None, False, None),
            ("opt_out", None, True, True),
            ("opt_out", PreferenceStatus.OPTED_OUT, True, False),
            ("opt_in", None, True, False),
            ("opt_in", PreferenceStatus.OPTED_IN, True, True),
        ]
    )
    @patch("posthog.views.validate_messaging_preferences_token")
    def test_preferences_page_tracking_section_per_mode(
        self, mode, stored_preference, section_shown, toggle_checked, mock_validate_messaging_preferences_token
    ):
        self._set_tracking_consent_mode(mode)
        if stored_preference is not None:
            self.recipient.preferences = {EMAIL_TRACKING_PREFERENCE_ID: stored_preference.value}
            self.recipient.save()
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )

        response = self.client.get(reverse("message_preferences", kwargs={"token": self.token}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["email_tracking_consent_enabled"], section_shown)
        if section_shown:
            self.assertEqual(response.context["email_tracking_allowed"], toggle_checked)
            self.assertContains(response, "Open and click tracking")
        else:
            self.assertNotContains(response, "Open and click tracking")

    @patch("posthog.views.validate_messaging_preferences_token")
    def test_tracking_opt_out_alone_does_not_unsubscribe(self, mock_validate_messaging_preferences_token):
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )

        response = self.client.post(
            reverse("message_preferences_update"),
            {"token": self.token, "preferences[]": [f"{EMAIL_TRACKING_PREFERENCE_ID}:false"]},
        )

        self.assertEqual(response.status_code, 200)
        self.recipient.refresh_from_db()
        prefs = self.recipient.get_all_preferences()
        self.assertEqual(prefs[EMAIL_TRACKING_PREFERENCE_ID], PreferenceStatus.OPTED_OUT)
        self.assertNotIn(ALL_MESSAGE_PREFERENCE_CATEGORY_ID, prefs)

    @patch("posthog.views.validate_messaging_preferences_token")
    def test_tracking_only_save_preserves_stored_all_opt_out(self, mock_validate_messaging_preferences_token):
        # A tracking-only payload (no category toggles rendered) must not rebuild
        # subscription state and silently resubscribe a one-click-unsubscribed recipient
        self.recipient.preferences = {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value}
        self.recipient.save()
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )

        response = self.client.post(
            reverse("message_preferences_update"),
            {"token": self.token, "preferences[]": [f"{EMAIL_TRACKING_PREFERENCE_ID}:false"]},
        )

        self.assertEqual(response.status_code, 200)
        self.recipient.refresh_from_db()
        prefs = self.recipient.get_all_preferences()
        self.assertEqual(prefs[ALL_MESSAGE_PREFERENCE_CATEGORY_ID], PreferenceStatus.OPTED_OUT)
        self.assertEqual(prefs[EMAIL_TRACKING_PREFERENCE_ID], PreferenceStatus.OPTED_OUT)

    @patch("posthog.views.validate_messaging_preferences_token")
    def test_tracking_opt_in_does_not_block_all_unsubscribe(self, mock_validate_messaging_preferences_token):
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )

        response = self.client.post(
            reverse("message_preferences_update"),
            {
                "token": self.token,
                "preferences[]": [
                    f"{self.category.id}:false",
                    f"{self.category2.id}:false",
                    f"{EMAIL_TRACKING_PREFERENCE_ID}:true",
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.recipient.refresh_from_db()
        prefs = self.recipient.get_all_preferences()
        self.assertEqual(prefs[ALL_MESSAGE_PREFERENCE_CATEGORY_ID], PreferenceStatus.OPTED_OUT)
        self.assertEqual(prefs[EMAIL_TRACKING_PREFERENCE_ID], PreferenceStatus.OPTED_IN)

    @parameterized.expand(["one_click", "preferences_form"])
    @patch("posthog.views.validate_messaging_preferences_token")
    def test_stored_tracking_consent_survives_writes_that_omit_it(
        self, code_path, mock_validate_messaging_preferences_token
    ):
        # Both write paths rebuild the preferences dict wholesale — a stored tracking-consent
        # answer must not be erased by an unsubscribe or a category-only save
        self.recipient.preferences = {EMAIL_TRACKING_PREFERENCE_ID: PreferenceStatus.OPTED_OUT.value}
        self.recipient.save()
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )

        if code_path == "one_click":
            response = self.client.get(
                reverse("message_preferences", kwargs={"token": self.token}),
                {"one_click_unsubscribe": "1"},
            )
        else:
            response = self.client.post(
                reverse("message_preferences_update"),
                {"token": self.token, "preferences[]": [f"{self.category.id}:true"]},
            )

        self.assertEqual(response.status_code, 200)
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.get_all_preferences()[EMAIL_TRACKING_PREFERENCE_ID], PreferenceStatus.OPTED_OUT)

    @patch("posthog.views.capture_internal")
    @patch("posthog.views.validate_messaging_preferences_token")
    def test_tracking_consent_change_emits_event_only_on_transition(
        self, mock_validate_messaging_preferences_token, mock_capture_internal
    ):
        self._enable_engagement_events()
        mock_validate_messaging_preferences_token.return_value = mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )
        data = {"token": self.token, "preferences[]": [f"{EMAIL_TRACKING_PREFERENCE_ID}:false"]}

        response = self.client.post(reverse("message_preferences_update"), data)

        self.assertEqual(response.status_code, 200)
        mock_capture_internal.assert_called_once_with(
            token=self.team.api_token,
            event_name="$workflows_email_tracking_consent_updated",
            event_source="workflows_preferences",
            distinct_id=self.recipient.identifier,
            properties={
                "$email": self.recipient.identifier,
                "status": PreferenceStatus.OPTED_OUT.value,
                "source": "preferences_page",
            },
        )

        # A repeated save with the same value is not a transition and must not emit again
        mock_capture_internal.reset_mock()
        response = self.client.post(reverse("message_preferences_update"), data)
        self.assertEqual(response.status_code, 200)
        mock_capture_internal.assert_not_called()


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

    def test_opt_outs_search_filters_by_identifier(self):
        for identifier in ["alice@example.com", "bob@example.com", "Alice.Smith@other.io"]:
            MessageRecipientPreference.objects.create(
                team=self.team,
                identifier=identifier,
                preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
            )
        # Opted out of a category only, so a global-list search must not surface them
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="alice@category-only.com",
            preferences={str(self.category.id): PreferenceStatus.OPTED_OUT.value},
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/messaging_preferences/opt_outs/", {"search": "ALICE"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)
        identifiers = {item["identifier"] for item in data["results"]}
        self.assertEqual(identifiers, {"alice@example.com", "Alice.Smith@other.io"})

    def test_opt_outs_search_term_too_long(self):
        response = self.client.get(
            f"/api/environments/{self.team.id}/messaging_preferences/opt_outs/", {"search": "a" * 513}
        )
        self.assertEqual(response.status_code, 400)

    def test_add_opt_out_global(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_preferences/add_opt_out/",
            {"identifier": "new@example.com"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["identifier"], "new@example.com")
        self.assertEqual(data["preferences"][ALL_MESSAGE_PREFERENCE_CATEGORY_ID], PreferenceStatus.OPTED_OUT.value)

        pref = MessageRecipientPreference.objects.get(team=self.team, identifier="new@example.com")
        self.assertEqual(pref.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID), PreferenceStatus.OPTED_OUT)

    def test_add_opt_out_specific_category(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_preferences/add_opt_out/",
            {"identifier": "user@example.com", "category_key": self.category.key},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["identifier"], "user@example.com")
        self.assertEqual(data["preferences"][str(self.category.id)], PreferenceStatus.OPTED_OUT.value)

    def test_add_opt_out_nonexistent_category(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_preferences/add_opt_out/",
            {"identifier": "user@example.com", "category_key": "does_not_exist"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "Category not found")

    def test_add_opt_out_duplicate_identifier_updates_existing(self):
        existing = MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="existing@example.com",
            preferences={str(self.category.id): PreferenceStatus.OPTED_IN.value},
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_preferences/add_opt_out/",
            {"identifier": "existing@example.com"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        existing.refresh_from_db()
        self.assertEqual(existing.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID), PreferenceStatus.OPTED_OUT)
        # existing category preference is preserved
        self.assertEqual(existing.get_preference(str(self.category.id)), PreferenceStatus.OPTED_IN)

    @parameterized.expand(
        [
            ("missing_identifier", {}, 400),
            ("blank_identifier", {"identifier": "   "}, 400),
            ("empty_string", {"identifier": ""}, 400),
        ]
    )
    def test_add_opt_out_invalid_identifier(self, _name, payload, expected_status):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_preferences/add_opt_out/",
            payload,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, expected_status)

    @parameterized.expand(
        [
            ("leading_trailing", "  trimmed@example.com  ", "trimmed@example.com"),
            ("leading_only", "  leading@example.com", "leading@example.com"),
            ("trailing_only", "trailing@example.com  ", "trailing@example.com"),
            ("no_whitespace", "clean@example.com", "clean@example.com"),
        ]
    )
    def test_add_opt_out_identifier_normalization(self, _name, raw_identifier, expected_identifier):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_preferences/add_opt_out/",
            {"identifier": raw_identifier},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["identifier"], expected_identifier)

    def test_add_opt_out_team_isolation(self):
        other_team = self.organization.teams.create(name="Other Team")
        self.client.post(
            f"/api/environments/{self.team.id}/messaging_preferences/add_opt_out/",
            {"identifier": "isolated@example.com"},
            content_type="application/json",
        )
        self.assertTrue(
            MessageRecipientPreference.objects.filter(team=self.team, identifier="isolated@example.com").exists()
        )
        self.assertFalse(
            MessageRecipientPreference.objects.filter(team=other_team, identifier="isolated@example.com").exists()
        )

    def _remove_opt_out(self, payload: dict):
        return self.client.post(
            f"/api/environments/{self.team.id}/messaging_preferences/remove_opt_out/",
            payload,
            content_type="application/json",
        )

    def test_remove_opt_out_global_clears_the_all_block(self):
        recipient = MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user@example.com",
            preferences={
                ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value,
                str(self.category.id): PreferenceStatus.OPTED_OUT.value,
            },
        )

        response = self._remove_opt_out({"identifier": "user@example.com"})

        self.assertEqual(response.status_code, 200)
        recipient.refresh_from_db()
        self.assertEqual(
            recipient.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID),
            PreferenceStatus.OPTED_IN,
        )
        # A per-category opt-out the recipient never lifted stays in place
        self.assertEqual(recipient.get_preference(str(self.category.id)), PreferenceStatus.OPTED_OUT)

        listed = self.client.get(f"/api/environments/{self.team.id}/messaging_preferences/opt_outs/")
        self.assertEqual(listed.json()["count"], 0)

    def test_remove_opt_out_for_unknown_recipient_records_the_opt_in(self):
        response = self._remove_opt_out({"identifier": "never-seen@example.com"})

        self.assertEqual(response.status_code, 201)
        preference = MessageRecipientPreference.objects.get(team=self.team, identifier="never-seen@example.com")
        self.assertEqual(
            preference.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID),
            PreferenceStatus.OPTED_IN,
        )

    @parameterized.expand(
        [
            ("sibling_without_stored_preference", None),
            ("sibling_with_stale_opt_in", PreferenceStatus.OPTED_IN.value),
        ]
    )
    def test_remove_opt_out_for_category_lifts_all_without_widening_consent(self, _name, sibling_status):
        # A globally unsubscribed recipient: opting them back in to one category has to clear
        # $all (or the send is still blocked) without turning the other marketing categories
        # back on. That includes a sibling holding a stale explicit opt-in (e.g. recorded by a
        # Customer.io webhook before the global unsubscribe): it was inert while $all was opted
        # out, so it must be pinned to opted out rather than resurrected.
        preferences = {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value}
        if sibling_status is not None:
            preferences[str(self.category2.id)] = sibling_status
        recipient = MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user@example.com",
            preferences=preferences,
        )

        response = self._remove_opt_out({"identifier": "user@example.com", "category_key": self.category.key})

        self.assertEqual(response.status_code, 200)
        recipient.refresh_from_db()
        prefs = recipient.get_all_preferences()
        self.assertEqual(prefs[str(self.category.id)], PreferenceStatus.OPTED_IN)
        self.assertEqual(prefs[ALL_MESSAGE_PREFERENCE_CATEGORY_ID], PreferenceStatus.OPTED_IN)
        self.assertEqual(prefs[str(self.category2.id)], PreferenceStatus.OPTED_OUT)

    def test_remove_opt_out_for_transactional_category_leaves_all_block_alone(self):
        transactional = MessageCategory.objects.create(
            team=self.team,
            key="receipts",
            name="Receipts",
            category_type=MessageCategoryType.TRANSACTIONAL,
        )
        recipient = MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="user@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
        )

        response = self._remove_opt_out({"identifier": "user@example.com", "category_key": transactional.key})

        self.assertEqual(response.status_code, 200)
        recipient.refresh_from_db()
        prefs = recipient.get_all_preferences()
        self.assertEqual(prefs[str(transactional.id)], PreferenceStatus.OPTED_IN)
        self.assertEqual(prefs[ALL_MESSAGE_PREFERENCE_CATEGORY_ID], PreferenceStatus.OPTED_OUT)

    def test_remove_opt_out_nonexistent_category(self):
        response = self._remove_opt_out({"identifier": "user@example.com", "category_key": "does_not_exist"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "Category not found")

    @parameterized.expand(
        [
            ("add_opt_out", PreferenceStatus.OPTED_OUT),
            ("remove_opt_out", PreferenceStatus.OPTED_IN),
        ]
    )
    @patch("products.messaging.backend.tasks.sync_preferences_to_customerio")
    def test_opt_out_writes_are_synced_to_customerio(self, endpoint, expected_status, mock_sync):
        # Exercises the whole dispatch chain: the view enqueues the task on commit, and the
        # task (eager in tests) reads the row back and calls the sync service.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/environments/{self.team.id}/messaging_preferences/{endpoint}/",
                {"identifier": "user@example.com"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201)
        mock_sync.assert_called_once_with(
            self.team.id,
            "user@example.com",
            {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: expected_status.value},
        )

    @patch("posthog.plugins.plugin_server_api.generate_messaging_preferences_token", return_value="tok-123")
    def test_generate_link_defaults_to_the_callers_email(self, mock_token):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_preferences/generate_link/",
            {},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["preferences_url"].endswith("/messaging-preferences/tok-123/"))
        mock_token.assert_called_once_with(self.team.id, self.user.email)

    @parameterized.expand(
        [
            ("too_long", "a" * 513),
            ("not_a_string", ["not", "a", "string"]),
        ]
    )
    @patch("posthog.plugins.plugin_server_api.generate_messaging_preferences_token")
    def test_generate_link_rejects_invalid_recipient(self, _name, recipient, mock_token):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_preferences/generate_link/",
            {"recipient": recipient},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        mock_token.assert_not_called()


class TestMessagePreferencesAPIKeyAccess(APIBaseTest):
    """
    The opt-out endpoints were `scope_object = "INTERNAL"`, a scope no personal API key can ever
    be granted, so an app with its own subscribe toggle had no way to record a preference change.
    """

    def _create_api_key(self, scopes: list[str]) -> str:
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=scopes,
        )
        return key_value

    @parameterized.expand(
        [
            (["insight:read"], "get", "opt_outs", status.HTTP_403_FORBIDDEN),
            (["hog_flow:read"], "get", "opt_outs", status.HTTP_200_OK),
            (["hog_flow:read"], "post", "remove_opt_out", status.HTTP_403_FORBIDDEN),
            (["hog_flow:write"], "post", "add_opt_out", status.HTTP_201_CREATED),
            (["hog_flow:write"], "post", "remove_opt_out", status.HTTP_201_CREATED),
        ]
    )
    def test_personal_api_key_access(self, scopes, http_method, endpoint, expected_status):
        api_key = self._create_api_key(scopes)
        self.client.logout()

        url = f"/api/projects/{self.team.id}/messaging_preferences/{endpoint}/"
        if http_method == "post":
            response = self.client.post(
                url,
                {"identifier": "api-key@example.com"},
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {api_key}",
            )
        else:
            response = self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {api_key}")

        self.assertEqual(response.status_code, expected_status)
