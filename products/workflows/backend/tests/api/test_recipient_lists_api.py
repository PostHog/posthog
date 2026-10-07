from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt

from products.workflows.backend.services import recipient_lists

SECRET = "test-workflow-recipient-list-jwt"
OTHER_LIST_ID = "01970000-0000-0000-0000-000000000000"


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, str] = {}

    def write(self, key: str, content: str) -> None:
        self.objects[key] = content

    def read(self, key: str, *, missing_ok: bool = False) -> str | None:
        return self.objects.get(key)


def _token(team_id: int, list_id: str | None) -> str:
    claims: dict[str, Any] = {"team_id": team_id}
    if list_id is not None:
        claims["recipient_list_id"] = list_id
    return encode_jwt(claims, timedelta(minutes=5), PosthogJwtAudience.WORKFLOW_RECIPIENT_LIST, signing_key=SECRET)


@override_settings(WORKFLOW_RECIPIENT_LIST_JWT_SECRETS=[SECRET])
class TestRecipientListsAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch.object(recipient_lists, "object_storage", _MemoryStorage())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _upload(self) -> dict[str, Any]:
        rows = [{"email": "ada@example.com", "org": "Hedgebox"}, {"email": "grace@example.com", "org": "Hogflix"}]
        response = self.client.post(
            f"/api/projects/{self.team.id}/workflow_recipient_lists/", {"rows": rows}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def _page(self, token: str) -> Any:
        self.client.logout()
        return self.client.post(
            f"/api/projects/{self.team.id}/workflow_recipient_list_pages/",
            {},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_uploaded_list_is_previewed_and_paged(self) -> None:
        uploaded = self._upload()
        assert (uploaded["row_count"], uploaded["columns"]) == (2, ["email", "org"])
        url = f"/api/projects/{self.team.id}/workflow_recipient_lists/{uploaded['id']}/"
        assert self.client.get(url).json() == uploaded

        page = self._page(_token(self.team.id, uploaded["id"]))
        assert page.status_code == status.HTTP_200_OK, page.json()
        assert page.json() == {
            "recipients": [
                {
                    "email": "ada@example.com",
                    "person_id": None,
                    "distinct_id": None,
                    "variables": {"email": "ada@example.com", "org": "Hedgebox"},
                },
                {
                    "email": "grace@example.com",
                    "person_id": None,
                    "distinct_id": None,
                    "variables": {"email": "grace@example.com", "org": "Hogflix"},
                },
            ],
            "cursor": None,
            "has_more": False,
        }

    @parameterized.expand(
        [
            ("token_for_another_list", OTHER_LIST_ID, status.HTTP_404_NOT_FOUND),
            ("token_without_a_list", None, status.HTTP_401_UNAUTHORIZED),
        ]
    )
    def test_page_needs_a_token_for_that_list(self, _name: str, list_id: str | None, expected: int) -> None:
        self._upload()
        assert self._page(_token(self.team.id, list_id)).status_code == expected

    def test_rejects_a_list_without_an_email_column(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/workflow_recipient_lists/", {"rows": [{"name": "Ada"}]}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'column named "email"' in response.json()["detail"]
