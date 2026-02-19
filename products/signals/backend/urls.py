from rest_framework_extensions.routers import ExtendedDefaultRouter

from .views import SignalReportViewSet


def register_signal_report_routes(router: ExtendedDefaultRouter):
    """Register signal report routes on the given router."""
    router.register(r"signal_reports", SignalReportViewSet, basename="signal_reports")
