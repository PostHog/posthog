from unittest.mock import Mock

from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase

from products.signals.backend.admin import SignalReportAdmin, SignalReportStatusFilter
from products.signals.backend.models import SignalReport


class TestReportAdmin(SimpleTestCase):
    def test_status_filter_keeps_monitoring_hidden_and_existing_links_working(self) -> None:
        request = RequestFactory().get("/", {"status__exact": "resolved"})
        model_admin = SignalReportAdmin(SignalReport, admin.site)
        filter_type = model_admin.get_list_filter(request)[0]
        assert isinstance(filter_type, type) and issubclass(filter_type, SignalReportStatusFilter)
        status_filter = filter_type(request, request.GET.copy(), SignalReport, model_admin)

        choices = list(status_filter.choices(Mock(add_facets=False)))
        assert "Monitoring" not in [choice["display"] for choice in choices]
        assert next(choice for choice in choices if choice["display"] == "Resolved")["selected"]
