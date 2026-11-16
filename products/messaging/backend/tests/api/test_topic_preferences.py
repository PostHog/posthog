from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import ProjectSecretAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)

OPTED_IN = PreferenceStatus.OPTED_IN.value
OPTED_OUT = PreferenceStatus.OPTED_OUT.value


@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
class TestTopicPreferences(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.newsletter = MessageCategory.objects.create(team=self.team, key="newsletter", name="Newsletter")
        self.product_updates = MessageCategory.objects.create(
            team=self.team, key="product-updates", name="Product updates"
        )
        self.psak = self._psak_client(["messaging_preference:write"])

    def _psak_client(self, scopes: list[str], team: Any = None) -> APIClient:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=team or self.team,
            label=f"preferences {ProjectSecretAPIKey.objects.count()}",
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return client

    def _set(self, body: dict[str, Any], client: APIClient | None = None):
        return (client or self.psak).post(f"/api/projects/{self.team.id}/messaging/preferences/", body, format="json")

    def _stored(self, identifier: str = "jane@example.com") -> dict[str, str]:
        return MessageRecipientPreference.objects.get(team=self.team, identifier=identifier).preferences

    def _seed(self, preferences: dict[str, str]) -> None:
        MessageRecipientPreference.objects.create(
            team=self.team, identifier="jane@example.com", preferences=preferences
        )

    @parameterized.expand([("plain", "jane@example.com"), ("surrounding_whitespace", " jane@example.com ")])
    def test_opts_a_recipient_out_of_one_topic(self, _flag: MagicMock, _name: str, identifier: str) -> None:
        response = self._set({"identifier": identifier, "topics": {"newsletter": False}})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "identifier": identifier,
            "all_marketing": None,
            "topics": {"newsletter": False},
        }
        assert self._stored(identifier) == {str(self.newsletter.id): OPTED_OUT}

    def test_applies_all_marketing_before_the_topics(self, _flag: MagicMock) -> None:
        response = self._set({"identifier": "jane@example.com", "all_marketing": False, "topics": {"newsletter": True}})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["all_marketing"] is True
        assert response.json()["topics"] == {"newsletter": True, "product-updates": False}

    def test_opting_back_in_to_one_topic_keeps_the_others_out(self, _flag: MagicMock) -> None:
        self._seed({ALL_MESSAGE_PREFERENCE_CATEGORY_ID: OPTED_OUT})

        response = self._set({"identifier": "jane@example.com", "topics": {"newsletter": True}})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._stored() == {
            ALL_MESSAGE_PREFERENCE_CATEGORY_ID: OPTED_IN,
            str(self.newsletter.id): OPTED_IN,
            str(self.product_updates.id): OPTED_OUT,
        }

    def test_keeps_choices_the_call_does_not_name(self, _flag: MagicMock) -> None:
        self._seed({str(self.product_updates.id): OPTED_OUT})

        response = self._set({"identifier": "jane@example.com", "all_marketing": True})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["topics"] == {"product-updates": False}
        assert self._stored() == {
            ALL_MESSAGE_PREFERENCE_CATEGORY_ID: OPTED_IN,
            str(self.product_updates.id): OPTED_OUT,
        }

    @parameterized.expand(
        [
            ("unknown", lambda test: "does-not-exist"),
            ("deleted", lambda test: test._deleted_topic().key),
            ("other_team", lambda test: test._other_team_topic().key),
        ]
    )
    def test_refuses_a_topic_the_project_does_not_have_and_changes_nothing(
        self, _flag: MagicMock, _name: str, topic_key: Any
    ) -> None:
        self._seed({str(self.product_updates.id): OPTED_OUT})

        response = self._set(
            {
                "identifier": "jane@example.com",
                "all_marketing": False,
                "topics": {"product-updates": True, topic_key(self): False},
            }
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()
        assert response.json()["code"] == "unknown_topic"
        assert topic_key(self) in response.json()["detail"]
        assert self._stored() == {str(self.product_updates.id): OPTED_OUT}

    def _deleted_topic(self) -> MessageCategory:
        return MessageCategory.objects.get_or_create(
            team=self.team, key="retired", defaults={"name": "Retired", "deleted": True}
        )[0]

    def _other_team_topic(self) -> MessageCategory:
        other_team = self.organization.teams.create(name="Other")
        return MessageCategory.objects.get_or_create(team=other_team, key="theirs", defaults={"name": "Theirs"})[0]

    def test_refuses_a_call_that_changes_nothing(self, _flag: MagicMock) -> None:
        response = self._set({"identifier": "jane@example.com", "topics": {}})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert not MessageRecipientPreference.objects.filter(team=self.team).exists()

    def test_opts_out_of_a_transactional_topic_like_any_other(self, _flag: MagicMock) -> None:
        receipts = MessageCategory.objects.create(
            team=self.team, key="receipts", name="Receipts", category_type=MessageCategoryType.TRANSACTIONAL
        )

        response = self._set({"identifier": "jane@example.com", "topics": {"receipts": False}})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._stored() == {str(receipts.id): OPTED_OUT}

    @patch("products.messaging.backend.services.preferences.sync_preferences_to_customerio_task.delay")
    def test_syncs_the_change_to_customerio_once_after_commit(self, sync: MagicMock, _flag: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            response = self._set(
                {"identifier": "jane@example.com", "all_marketing": False, "topics": {"newsletter": False}}
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        sync.assert_called_once_with(self.team.id, "jane@example.com")

    @parameterized.expand(
        [
            ("preference_scope", ["messaging_preference:write"], "messaging_preference"),
            ("workflow_scope", ["hog_flow:write"], "hog_flow"),
            ("both_scopes", ["hog_flow:write", "messaging_preference:write"], "messaging_preference"),
        ]
    )
    def test_accepts_either_write_scope_and_reports_which_one_authorized(
        self, _flag: MagicMock, _name: str, scopes: list[str], authorized_by: str
    ) -> None:
        with patch("posthog.event_usage.posthoganalytics.capture") as capture:
            response = self._set(
                {"identifier": "jane@example.com", "topics": {"newsletter": False}}, self._psak_client(scopes)
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._stored() == {str(self.newsletter.id): OPTED_OUT}
        reports = [
            call.kwargs["properties"]
            for call in capture.call_args_list
            if call.kwargs["event"] == "messaging preferences api set"
        ]
        assert [report["authorized_by"] for report in reports] == [authorized_by]

    @parameterized.expand(
        [
            ("read_only_workflow_key", ["hog_flow:read"]),
            ("read_only_preference_key", ["messaging_preference:read"]),
            ("unrelated_scope", ["feature_flag:read"]),
        ]
    )
    def test_refuses_a_project_secret_key_without_a_write_scope(
        self, _flag: MagicMock, _name: str, scopes: list[str]
    ) -> None:
        response = self._set({"identifier": "jane@example.com", "all_marketing": False}, self._psak_client(scopes))

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert not MessageRecipientPreference.objects.filter(team=self.team).exists()

    def test_refuses_another_projects_key(self, _flag: MagicMock) -> None:
        other_team = self.organization.teams.create(name="Other")

        response = self._set(
            {"identifier": "jane@example.com", "all_marketing": False},
            self._psak_client(["messaging_preference:write"], team=other_team),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert not MessageRecipientPreference.objects.filter(team=self.team).exists()

    def test_refuses_a_logged_in_user(self, _flag: MagicMock) -> None:
        response = self._set({"identifier": "jane@example.com", "all_marketing": False}, self.client)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED, response.json()

    def test_is_not_found_while_the_email_api_flag_is_off(self, flag: MagicMock) -> None:
        flag.return_value = False

        response = self._set({"identifier": "jane@example.com", "all_marketing": False})

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not MessageRecipientPreference.objects.filter(team=self.team).exists()

    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_reports_each_call_with_its_outcome(self, capture: MagicMock, _flag: MagicMock) -> None:
        self._set({"identifier": "jane@example.com", "topics": {"newsletter": False, "product-updates": True}})
        self._set({"identifier": "jane@example.com", "topics": {"nope": False}})

        outcomes = [call.kwargs["properties"] for call in capture.call_args_list]
        assert [call.kwargs["event"] for call in capture.call_args_list] == ["messaging preferences api set"] * 2
        assert [(o["outcome"], o["topic_count"], o["sets_all_marketing"]) for o in outcomes] == [
            ("applied", 2, False),
            ("unknown_topic", 1, False),
        ]
