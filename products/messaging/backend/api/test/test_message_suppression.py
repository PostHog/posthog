from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.messaging.backend.api.message_suppression import MessageSuppressionViewSet
from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource


class TestMessageSuppressionViewSetScope(SimpleTestCase):
    """
    Guards against the viewset silently reverting to scope_object='INTERNAL', which would bypass
    hog_flow RBAC and let any project member manage suppressions regardless of workflow permissions.
    """

    def test_scope_object_is_hog_flow(self) -> None:
        assert MessageSuppressionViewSet.scope_object == "hog_flow"

    def test_mutating_actions_are_declared_as_writes(self) -> None:
        # `add_suppression` and `remove_suppression` are custom @action endpoints; without being
        # listed here they'd default to a read scope and slip past hog_flow:write enforcement.
        assert set(MessageSuppressionViewSet.scope_object_write_actions) == {
            "add_suppression",
            "remove_suppression",
        }


class TestSuppressionListPersonalAPIKeyAccess(APIBaseTest):
    """
    Guards the token scopes on the read action. It needs both hog_flow:read and person:read, so
    neither alone opens up the recipient addresses and SMTP diagnostics the rows carry. Session auth
    skips scope checks entirely, so only a token exercises this.
    """

    def _key(self, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=scopes,
        )
        return value

    @parameterized.expand(
        [
            (["hog_flow:read", "person:read"], 200),
            (["hog_flow:read"], 403),
            (["person:read"], 403),
        ]
    )
    def test_suppressions_read_requires_both_scopes(self, scopes: list[str], expected_status: int) -> None:
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.id}/messaging_suppressions/suppressions/",
            HTTP_AUTHORIZATION=f"Bearer {self._key(scopes)}",
        )

        assert response.status_code == expected_status, response.json()
        if expected_status == 200:
            assert set(response.json()) == {"count", "next", "previous", "results"}


class TestSuppressionListSearch(APIBaseTest):
    def test_search_filters_by_identifier_within_suppressed_rows(self) -> None:
        for identifier in ["alice@example.com", "bob@example.com"]:
            MessageSuppression.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                identifier=identifier,
                source=SuppressionSource.MANUAL,
                suppressed=True,
            )
        # Bounce-counting row that hasn't crossed the threshold: matches the search term but must
        # stay off the list because it isn't suppressed
        MessageSuppression.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            identifier="alice@not-suppressed.com",
            source=SuppressionSource.BOUNCE,
            suppressed=False,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/messaging_suppressions/suppressions/", {"search": "ALICE"}
        )

        assert response.status_code == 200, response.json()
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["identifier"] == "alice@example.com"

    def test_search_term_too_long(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/messaging_suppressions/suppressions/", {"search": "a" * 513}
        )
        assert response.status_code == 400


class TestRemoveSuppressionResetsSource(APIBaseTest):
    """
    Guards against a regression where remove_suppression keeps source='MANUAL' on the removed row.
    The node upserts preserve suppressed/deleted `WHEN source = 'MANUAL'`, so a manual entry that
    was removed via the API would never be auto-suppressed again — not even by a hard bounce —
    and would stay hidden from the UI (which filters deleted=false).
    """

    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/messaging_suppressions/{action}/"

    def test_remove_resets_source_to_bounce_so_future_auto_suppression_can_run(self) -> None:
        # Manual add → row exists as MANUAL, suppressed.
        response = self.client.post(self._url("add_suppression"), {"identifier": "user@example.com"}, format="json")
        assert response.status_code in (200, 201)

        row = MessageSuppression.objects.for_team(self.team.id).get(identifier="user@example.com")
        assert row.source == SuppressionSource.MANUAL
        assert row.suppressed

        # Remove — the row should be un-suppressed AND its source reset so that the ON CONFLICT
        # branches in the node write path (which skip MANUAL rows) can re-suppress it later.
        response = self.client.post(self._url("remove_suppression"), {"identifier": "user@example.com"}, format="json")
        assert response.status_code == 204

        row.refresh_from_db()
        assert (row.suppressed, row.deleted, row.transient_bounce_count, row.source) == (
            False,
            True,
            0,
            SuppressionSource.BOUNCE,
        ), (
            "remove_suppression must reset the row so the node write path can auto-suppress this address again if it later bounces"
        )
