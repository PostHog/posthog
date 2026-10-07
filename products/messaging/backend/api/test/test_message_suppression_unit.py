from django.test import SimpleTestCase

from products.messaging.backend.api.message_suppression import MessageSuppressionViewSet


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
