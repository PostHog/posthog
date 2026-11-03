"""Report charts for products that show the reports their scouts filed."""

from typing import Any

from products.signals.backend import report_chart_rendering

# Registered by the Signals report endpoints. A second serializer with this component name breaks the schema.
REPORT_CHART_SCHEMA = {"$ref": "#/components/schemas/ReportChart"}


def render_report_charts(charts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Render the stored charts of a `ScoutReport` in the `REPORT_CHART_SCHEMA` shape."""
    return report_chart_rendering.render_report_charts(charts)
