"""Shared metric attribute builders for the Signals grouping pipeline.

All Signals workflow metrics go through these helpers so label keys / types
stay in sync across `buffer.py`, `grouping_v2.py`, and `grouping.py`.
"""


def team_meter_attrs(team_id: int) -> dict[str, str]:
    return {"team_id": str(team_id)}


def source_meter_attrs(team_id: int, source_product: str, source_type: str) -> dict[str, str]:
    return {
        "team_id": str(team_id),
        "source_product": source_product,
        "source_type": source_type,
    }
