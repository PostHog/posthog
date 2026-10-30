from typing import Any

from products.signals.backend.serializers import ReportChartSerializer


def render_report_charts(charts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Render a report's stored charts as the Signals report endpoints do."""
    return list(ReportChartSerializer(charts, many=True).data)
