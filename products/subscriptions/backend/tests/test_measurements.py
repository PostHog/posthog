from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from products.product_analytics.backend.facade.contracts import SavedInsightIdentity
from products.subscriptions.backend.facade.contracts import Recommendation
from products.subscriptions.backend.facade.measurements import canonicalize_measurement
from products.tasks.backend.facade.staged_evidence import CompletedMCPCallEvidence

_SAVED_INSIGHT = SavedInsightIdentity(
    id=42,
    short_id="signup-rate",
    team_id=17,
    last_modified_at=datetime(2026, 9, 8, 10, 30, tzinfo=UTC),
)


def _recommendation(*, measurement_call_id: str | None = "mcp:insight", direction: str = "increase") -> Recommendation:
    return Recommendation(
        kind="investigation",
        title="Improve activation",
        rationale="Activation needs attention",
        target="activation",
        why_now="This week",
        confidence=0.8,
        effort="small",
        metric_name="Activation count",
        metric_direction=direction,
        expected_metric_movement="Increase activation",
        citation_ids=("report", "mcp:insight"),
        semantic_key="activation",
        measurement_call_id=measurement_call_id,
    )


def _query(*, series: object | None = None, **overrides: object) -> dict[str, object]:
    query: dict[str, object] = {
        "kind": "TrendsQuery",
        "series": [series if series is not None else {"kind": "EventsNode", "event": "signed_up", "math": "total"}],
        "interval": "day",
        "dateRange": {"date_from": "2026-09-01", "date_to": "2026-09-07"},
    }
    query.update(overrides)
    return query


def _call(
    *,
    arguments: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
    citation_id: str = "mcp:insight",
    tool_name: str = "insight-query",
) -> CompletedMCPCallEvidence:
    return CompletedMCPCallEvidence(
        citation_id=citation_id,
        tool_name=tool_name,
        arguments=arguments if arguments is not None else {"insightId": "signup-rate", "output_format": "json"},
        result=result
        if result is not None
        else {
            "insight": {"id": 42, "short_id": "signup-rate"},
            "query": _query(),
            "results": [{"count": 0}],
        },
    )


def _resolver(
    identity: SavedInsightIdentity | None = _SAVED_INSIGHT,
) -> Callable[[int, str | int], SavedInsightIdentity | None]:
    return lambda _team_id, _reference: identity


@pytest.mark.parametrize(
    ("series", "count", "expected_series"),
    [
        ({"kind": "EventsNode", "event": "signed_up", "math": "total"}, 0, {"event": "signed_up"}),
        ({"kind": "ActionsNode", "id": 7, "math": "total"}, 3, {"id": 7}),
        ({"kind": "EventsNode", "event": "signed_up"}, 0, {"event": "signed_up"}),
        ({"kind": "ActionsNode", "id": 7}, 3, {"id": 7}),
    ],
)
def test_canonicalize_measurement_freezes_supported_total_baselines(
    series: dict[str, object], count: int, expected_series: dict[str, object]
) -> None:
    measurement = canonicalize_measurement(
        team_id=17,
        recommendation=_recommendation(),
        completed_mcp_calls=(
            _call(
                result={
                    "insight": {"id": 42, "short_id": "signup-rate"},
                    "query": _query(series=series),
                    "results": [{"count": count}],
                }
            ),
        ),
        resolve_insight=_resolver(),
    )

    assert measurement is not None
    assert measurement["source_call_id"] == "mcp:insight"
    assert measurement["saved_insight"] == {
        "id": 42,
        "short_id": "signup-rate",
        "last_modified_at": "2026-09-08T10:30:00+00:00",
    }
    query = measurement["query"]
    assert isinstance(query, dict)
    assert query["series"] == [{"kind": series["kind"], "math": "total", **expected_series}]
    assert measurement["baseline"] == {"value": count, "date_from": "2026-09-01", "date_to": "2026-09-07"}
    assert measurement["metric"] == {
        "name": "Activation count",
        "expected_movement": "Increase activation",
        "direction": "increase",
    }


def test_canonicalize_measurement_has_stable_compact_canonical_form_and_hash() -> None:
    call = _call(
        result={
            "insight": {"short_id": "signup-rate", "id": 42},
            "query": _query(response={"results": [{"count": 99}]}, tags={"name": "ignore"}),
            "results": [{"count": 3}],
        }
    )

    first = canonicalize_measurement(
        team_id=17, recommendation=_recommendation(), completed_mcp_calls=(call,), resolve_insight=_resolver()
    )
    second = canonicalize_measurement(
        team_id=17, recommendation=_recommendation(), completed_mcp_calls=(call,), resolve_insight=_resolver()
    )

    assert first == second
    assert first is not None
    assert set(first) == {"version", "source_call_id", "saved_insight", "query", "baseline", "metric", "hash"}
    query = first["query"]
    measurement_hash = first["hash"]
    assert isinstance(query, dict)
    assert isinstance(measurement_hash, str)
    assert "response" not in query
    assert "tags" not in query
    assert len(measurement_hash) == 64


@pytest.mark.parametrize(
    "identity",
    [
        SavedInsightIdentity(
            id=42, short_id="signup-rate", team_id=18, last_modified_at=_SAVED_INSIGHT.last_modified_at
        ),
        SavedInsightIdentity(
            id=43, short_id="signup-rate", team_id=17, last_modified_at=_SAVED_INSIGHT.last_modified_at
        ),
        SavedInsightIdentity(id=42, short_id="other", team_id=17, last_modified_at=_SAVED_INSIGHT.last_modified_at),
        None,
    ],
)
def test_canonicalize_measurement_rejects_missing_or_mismatched_saved_insight(
    identity: SavedInsightIdentity | None,
) -> None:
    assert (
        canonicalize_measurement(
            team_id=17,
            recommendation=_recommendation(),
            completed_mcp_calls=(_call(),),
            resolve_insight=_resolver(identity),
        )
        is None
    )


@pytest.mark.parametrize(
    "recommendation,calls",
    [
        (_recommendation(measurement_call_id=None), (_call(),)),
        (_recommendation(), (_call(citation_id="mcp:other"),)),
        (_recommendation(), (_call(), _call())),
        (_recommendation(), (_call(tool_name="query-trends"),)),
        (
            _recommendation(),
            (
                CompletedMCPCallEvidence(
                    citation_id="mcp:insight", tool_name="insight-query", result=_call().result, arguments=None
                ),
            ),
        ),
        (_recommendation(), (_call(arguments={"insightId": "signup-rate", "filters_override": {}}),)),
        (_recommendation(), (_call(arguments={"insightId": "signup-rate", "variables_override": {}}),)),
        (_recommendation(), (_call(arguments={"insightId": "signup-rate", "query": _query()}),)),
        (_recommendation(), (_call(arguments={"insightId": "signup-rate", "metric": "activation"}),)),
    ],
)
def test_canonicalize_measurement_accepts_only_one_cited_unmodified_insight_call(
    recommendation: Recommendation, calls: tuple[CompletedMCPCallEvidence, ...]
) -> None:
    assert (
        canonicalize_measurement(
            team_id=17, recommendation=recommendation, completed_mcp_calls=calls, resolve_insight=_resolver()
        )
        is None
    )


@pytest.mark.parametrize(
    "query",
    [
        {"kind": "FunnelsQuery", "series": []},
        _query(series={"kind": "EventsNode", "event": "", "math": "total"}),
        _query(series={"kind": "ActionsNode", "id": 0, "math": "total"}),
        _query(series={"kind": "EventsNode", "event": "signed_up", "math": "dau"}),
        _query(
            series=[
                {"kind": "EventsNode", "event": "signed_up", "math": "total"},
                {"kind": "EventsNode", "event": "logged_in", "math": "total"},
            ]
        ),
        _query(interval="week"),
        _query(dateRange={"date_from": "-7d", "date_to": "2026-09-08"}),
        _query(dateRange={"date_from": "2026-09-08", "date_to": "2026-09-01"}),
        _query(dateRange={"date_from": "2026-09-01", "date_to": "2026-09-08"}),
        _query(dateRange={"date_from": "2026-09-01", "date_to": "2026-09-07", "explicitDate": True}),
        _query(breakdownFilter={"breakdown": "browser"}),
        _query(compareFilter={"compare": True}),
        _query(trendsFilter={"formula": "A/B"}),
        _query(samplingFactor=0.1),
        _query(trendsFilter={"display": "ActionsLineGraphCumulative"}),
        _query(trendsFilter={"display": "BoldNumber"}),
        _query(trendsFilter={"display": "ActionsTable"}),
        _query(trendsFilter={"display": "ActionsBarValue"}),
        _query(trendsFilter={"smoothingIntervals": 2}),
        _query(modifiers={"debug": True}),
    ],
)
def test_canonicalize_measurement_rejects_unsupported_query_families(query: dict[str, object]) -> None:
    assert (
        canonicalize_measurement(
            team_id=17,
            recommendation=_recommendation(),
            completed_mcp_calls=(
                _call(
                    result={"insight": {"id": 42, "short_id": "signup-rate"}, "query": query, "results": [{"count": 3}]}
                ),
            ),
            resolve_insight=_resolver(),
        )
        is None
    )


@pytest.mark.parametrize("results", [[], [{"count": 1}, {"count": 2}], [{}], [{"count": "3"}], [{"count": math.inf}]])
def test_canonicalize_measurement_requires_one_finite_numeric_result(results: list[dict[str, object]]) -> None:
    assert (
        canonicalize_measurement(
            team_id=17,
            recommendation=_recommendation(),
            completed_mcp_calls=(
                _call(result={"insight": {"id": 42, "short_id": "signup-rate"}, "query": _query(), "results": results}),
            ),
            resolve_insight=_resolver(),
        )
        is None
    )


def test_canonicalize_measurement_leaves_unknown_direction_unavailable() -> None:
    assert (
        canonicalize_measurement(
            team_id=17,
            recommendation=_recommendation(direction="flat"),
            completed_mcp_calls=(_call(),),
            resolve_insight=_resolver(),
        )
        is None
    )
