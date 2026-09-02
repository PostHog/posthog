from posthog.test.base import BaseTest

from django.contrib.admin import AdminSite
from django.test import RequestFactory

from products.growth.backend.admin import IcpScoringConfigAdmin
from products.growth.backend.models import IcpScoringConfig


class TestIcpScoringConfigAdminPermissions(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.admin = IcpScoringConfigAdmin(IcpScoringConfig, AdminSite())
        self.request = RequestFactory().get("/admin/growth/icpscoringconfig/")

    def test_add_is_never_permitted(self) -> None:
        assert self.admin.has_add_permission(self.request) is False

    def test_delete_is_never_permitted(self) -> None:
        config = IcpScoringConfig.objects.create(version="v1", is_active=True)

        assert self.admin.has_delete_permission(self.request, config) is False
        assert self.admin.has_delete_permission(self.request, None) is False
