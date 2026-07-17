from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

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
        assert row.suppressed is True

        # Remove — the row should be un-suppressed AND its source reset so that the ON CONFLICT
        # branches in the node write path (which skip MANUAL rows) can re-suppress it later.
        response = self.client.post(self._url("remove_suppression"), {"identifier": "user@example.com"}, format="json")
        assert response.status_code == 204

        row.refresh_from_db()
        assert row.suppressed is False
        assert row.deleted is True
        assert row.transient_bounce_count == 0
        assert row.source == SuppressionSource.BOUNCE, (
            "remove_suppression must reset source to BOUNCE so the node write path can auto-suppress "
            "this address again if it later bounces"
        )
