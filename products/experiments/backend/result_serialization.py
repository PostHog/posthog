"""Shared helpers for shaping ExperimentMetricResult payloads before they leave the backend."""

from collections.abc import Mapping
from typing import Any


def strip_step_sessions(result: Any) -> Any:
    """Remove the per-session funnel actors payload from a stored experiment metric result.

    `step_sessions` powers the frontend's "view sessions per step" affordance off
    a separate per-metric query, not this timeseries endpoint. Carrying it through
    here multiplies the response by sessions × steps × variants and pushes MCP
    consumers past their context window with no benefit.
    """
    if not isinstance(result, Mapping):
        return result
    cleaned = {k: v for k, v in result.items() if k != "step_sessions"}
    baseline = cleaned.get("baseline")
    if isinstance(baseline, dict):
        cleaned["baseline"] = {k: v for k, v in baseline.items() if k != "step_sessions"}
    variants = cleaned.get("variant_results")
    if isinstance(variants, list):
        cleaned["variant_results"] = [
            {k: v for k, v in variant.items() if k != "step_sessions"} if isinstance(variant, dict) else variant
            for variant in variants
        ]
    return cleaned
