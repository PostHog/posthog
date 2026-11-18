from typing import Any


def trends_metric_query(*, series: list[dict[str, Any]], date_from: str = "-30d") -> dict[str, Any]:
    return {
        "kind": "InsightVizNode",
        "source": {
            "kind": "TrendsQuery",
            "dateRange": {"date_from": date_from},
            "series": series,
        },
    }
