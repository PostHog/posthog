from typing import Any, cast

from django.test import SimpleTestCase

from rest_framework.viewsets import ViewSetMixin

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.permissions import ScopeBasePermission

from products.error_tracking.backend.routes import register_routes


class _RouteCollector:
    def __init__(self) -> None:
        self.projects = self
        self.viewsets: list[type[ViewSetMixin]] = []

    def register(self, _prefix: str, viewset: type[ViewSetMixin], _basename: str, _parents: list[str]) -> None:
        self.viewsets.append(viewset)


class TestErrorTrackingAPIScopes(SimpleTestCase):
    def test_all_registered_actions_support_scoped_authentication(self) -> None:
        routes = _RouteCollector()
        register_routes(cast(Any, routes))

        missing_actions: list[str] = []
        standard_actions = set(ScopeBasePermission.read_actions + ScopeBasePermission.write_actions)

        for viewset in routes.viewsets:
            actions = {action.__name__ for action in viewset.get_extra_actions()}
            actions.update(action for action in standard_actions if callable(getattr(viewset, action, None)))

            read_actions = set(getattr(viewset, "scope_object_read_actions", ScopeBasePermission.read_actions))
            write_actions = set(getattr(viewset, "scope_object_write_actions", ScopeBasePermission.write_actions))

            for action in actions:
                action_method: Any = getattr(viewset, action)
                if action_method is ForbidDestroyModel.destroy:
                    continue
                required_scopes = getattr(action_method, "kwargs", {}).get("required_scopes")
                if action not in read_actions | write_actions and not required_scopes:
                    missing_actions.append(f"{viewset.__name__}.{action}")

        self.assertEqual(missing_actions, [])
