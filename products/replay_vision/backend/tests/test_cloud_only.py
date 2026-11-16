from typing import Any, cast

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework.viewsets import ViewSetMixin

from products.replay_vision.backend.api.cloud_only import ReplayVisionCloudOnly
from products.replay_vision.backend.routes import register_routes


class _RouteCollector:
    def __init__(self) -> None:
        self.projects = self
        self.viewsets: list[type[ViewSetMixin]] = []

    def register(
        self, _prefix: str, viewset: type[ViewSetMixin], _basename: str, _parents: list[str]
    ) -> "_RouteCollector":
        self.viewsets.append(viewset)
        return self


class TestReplayVisionCloudOnly(SimpleTestCase):
    @parameterized.expand(
        [
            ("us_cloud", "US", False, False, True),
            ("eu_cloud", "EU", False, False, True),
            ("local_dev", None, True, False, True),
            ("test_run", None, False, True, True),
            ("self_hosted", None, False, False, False),
        ]
    )
    def test_allows_every_deployment_except_self_hosted(
        self, _name: str, cloud_deployment: str | None, debug: bool, test: bool, allowed: bool
    ) -> None:
        with override_settings(CLOUD_DEPLOYMENT=cloud_deployment, DEBUG=debug, TEST=test):
            assert ReplayVisionCloudOnly().has_permission(cast(Any, None), cast(Any, None)) is allowed

    def test_every_registered_viewset_is_cloud_only(self) -> None:
        routes = _RouteCollector()
        register_routes(cast(Any, routes))

        ungated = [
            viewset.__name__
            for viewset in routes.viewsets
            if ReplayVisionCloudOnly not in getattr(viewset, "permission_classes", [])
        ]

        assert routes.viewsets
        assert ungated == []
