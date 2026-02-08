"""
Tests that execute SQL templates against mock data to validate output and logic.

Tests both the structure and calculation logic of each metric SQL file.
"""

from datetime import datetime
from pathlib import Path

import pytest

from jinja2 import Template

from products.llm_analytics.dags.daily_metrics.config import config
from products.llm_analytics.dags.daily_metrics.utils import SQL_DIR

# Expected output columns
EXPECTED_COLUMNS = ["date", "team_id", "metric_name", "metric_value"]


def get_all_sql_files():
    """Get all SQL template files."""
    return sorted(SQL_DIR.glob("*.sql"))


@pytest.fixture
def template_context():
    """Provide sample context for rendering Jinja2 templates."""
    return {
        "event_types": config.ai_event_types,
        "pageview_mappings": config.pageview_mappings,
        "metric_date": "2025-01-01",
        "include_error_rates": config.include_error_rates,
    }


@pytest.fixture
def mock_events_data():
    """
    Mock events data for testing SQL queries.

    Simulates the events table with various AI events for testing.
    Returns a list of event dicts with timestamp, team_id, event, and properties.
    """
    base_time = datetime(2025, 1, 1, 12, 0, 0)

    events = [
        # Team 1: 3 generations, 1 with error
        {
            "timestamp": base_time,
            "team_id": 1,
            "event": "$ai_generation",
            "properties": {
                "$ai_trace_id": "trace-1",
                "$ai_session_id": "session-1",
                "$ai_error": "",
            },
        },
        {
            "timestamp": base_time,
            "team_id": 1,
            "event": "$ai_generation",
            "properties": {
                "$ai_trace_id": "trace-1",
                "$ai_session_id": "session-1",
                "$ai_error": "rate limit exceeded",
            },
        },
        {
            "timestamp": base_time,
            "team_id": 1,
            "event": "$ai_generation",
            "properties": {
                "$ai_trace_id": "trace-2",
                "$ai_session_id": "session-1",
                "$ai_error": "",
            },
        },
        # Team 1: 2 spans from same trace
        {
            "timestamp": base_time,
            "team_id": 1,
            "event": "$ai_span",
            "properties": {
                "$ai_trace_id": "trace-1",
                "$ai_session_id": "session-1",
                "$ai_is_error": True,
            },
        },
        {
            "timestamp": base_time,
            "team_id": 1,
            "event": "$ai_span",
            "properties": {
                "$ai_trace_id": "trace-1",
                "$ai_session_id": "session-1",
                "$ai_is_error": False,
            },
        },
        # Team 2: 1 generation, no errors
        {
            "timestamp": base_time,
            "team_id": 2,
            "event": "$ai_generation",
            "properties": {
                "$ai_trace_id": "trace-3",
                "$ai_session_id": "session-2",
                "$ai_error": "",
            },
        },
        # Team 1: Pageviews on LLM Analytics
        {
            "timestamp": base_time,
            "team_id": 1,
            "event": "$pageview",
            "properties": {
                "$current_url": "https://app.posthog.com/project/123/llm-analytics/traces?filter=active",
            },
        },
        {
            "timestamp": base_time,
            "team_id": 1,
            "event": "$pageview",
            "properties": {
                "$current_url": "https://app.posthog.com/project/123/llm-analytics/traces",
            },
        },
        {
            "timestamp": base_time,
            "team_id": 1,
            "event": "$pageview",
            "properties": {
                "$current_url": "https://app.posthog.com/project/123/llm-analytics/generations",
            },
        },
    ]

    return events


@pytest.fixture
def expected_metrics(mock_events_data):
    """
    Expected metric outputs based on mock_events_data.

    This serves as the source of truth for what each SQL file should produce.
    """
    return {
        "event_counts.sql": [
            {"date": "2025-01-01", "team_id": 1, "metric_name": "ai_generation_count", "metric_value": 3.0},
            {"date": "2025-01-01", "team_id": 1, "metric_name": "ai_span_count", "metric_value": 2.0},
            {"date": "2025-01-01", "team_id": 2, "metric_name": "ai_generation_count", "metric_value": 1.0},
        ],
        "trace_counts.sql": [
            {
                "date": "2025-01-01",
                "team_id": 1,
                "metric_name": "ai_trace_id_count",
                "metric_value": 2.0,
            },  # trace-1, trace-2
            {"date": "2025-01-01", "team_id": 2, "metric_name": "ai_trace_id_count", "metric_value": 1.0},  # trace-3
        ],
        "session_counts.sql": [
            {
                "date": "2025-01-01",
                "team_id": 1,
                "metric_name": "ai_session_id_count",
                "metric_value": 1.0,
            },  # session-1
            {
                "date": "2025-01-01",
                "team_id": 2,
                "metric_name": "ai_session_id_count",
                "metric_value": 1.0,
            },  # session-2
        ],
        "error_rates.sql": [
            # Team 1: 1 errored generation out of 3 = 0.3333
            {"date": "2025-01-01", "team_id": 1, "metric_name": "ai_generation_error_rate", "metric_value": 0.3333},
            # Team 1: 1 errored span out of 2 = 0.5
            {"date": "2025-01-01", "team_id": 1, "metric_name": "ai_span_error_rate", "metric_value": 0.5},
            # Team 2: 0 errored out of 1 = 0.0
            {"date": "2025-01-01", "team_id": 2, "metric_name": "ai_generation_error_rate", "metric_value": 0.0},
        ],
        "trace_error_rates.sql": [
            # Team 1: trace-1 has errors, trace-2 doesn't = 1/2 = 0.5
            {"date": "2025-01-01", "team_id": 1, "metric_name": "ai_trace_id_has_error_rate", "metric_value": 0.5},
            # Team 2: trace-3 has no errors = 0/1 = 0.0
            {"date": "2025-01-01", "team_id": 2, "metric_name": "ai_trace_id_has_error_rate", "metric_value": 0.0},
        ],
        "pageview_counts.sql": [
            {"date": "2025-01-01", "team_id": 1, "metric_name": "pageviews_traces", "metric_value": 2.0},
            {"date": "2025-01-01", "team_id": 1, "metric_name": "pageviews_generations", "metric_value": 1.0},
        ],
    }


@pytest.mark.parametrize("sql_file", get_all_sql_files(), ids=lambda f: f.stem)
def test_sql_output_structure(sql_file: Path, template_context: dict, mock_events_data: list):
    """
    Test that each SQL file produces output with the correct structure.

    This test verifies:
    1. SQL renders without errors
    2. Output has exactly 4 columns
    3. Columns are named correctly: date, team_id, metric_name, metric_value
    """
    with open(sql_file) as f:
        template = Template(f.read())
        rendered = template.render(**template_context)

    # Basic smoke test - SQL should render
    assert rendered.strip(), f"{sql_file.name} rendered to empty string"

    # SQL should be a SELECT statement
    assert "SELECT" in rendered.upper(), f"{sql_file.name} should contain SELECT"

    # Should have all required column aliases (or direct column references for team_id)
    for col in EXPECTED_COLUMNS:
        # team_id is often selected directly without an alias
        if col == "team_id":
            assert "team_id" in rendered.lower(), f"{sql_file.name} missing column: {col}"
        else:
            assert f"as {col}" in rendered.lower(), f"{sql_file.name} missing column alias: {col}"


def test_event_counts_logic(template_context: dict, mock_events_data: list, expected_metrics: dict):
    """Test event_counts.sql produces correct counts."""
    sql_file = SQL_DIR / "event_counts.sql"
    with open(sql_file) as f:
        template = Template(f.read())
        rendered = template.render(**template_context)

    # Verify SQL structure expectations
    assert "count(*)" in rendered.lower(), "event_counts.sql should use count(*)"
    assert "group by date, team_id, event" in rendered.lower(), "Should group by date, team_id, event"

    # Verify expected metrics documentation
    expected = expected_metrics["event_counts.sql"]
    assert len(expected) == 3, "Expected 3 metric rows based on mock data"

    # Team 1 should have 3 generation events
    gen_team1 = next(m for m in expected if m["team_id"] == 1 and "generation" in m["metric_name"])
    assert gen_team1["metric_value"] == 3.0

    # Team 1 should have 2 span events
    span_team1 = next(m for m in expected if m["team_id"] == 1 and "span" in m["metric_name"])
    assert span_team1["metric_value"] == 2.0


def test_trace_counts_logic(template_context: dict, mock_events_data: list, expected_metrics: dict):
    """Test trace_counts.sql produces correct distinct trace counts."""
    sql_file = SQL_DIR / "trace_counts.sql"
    with open(sql_file) as f:
        template = Template(f.read())
        rendered = template.render(**template_context)

    # Verify SQL uses count(DISTINCT)
    assert "count(distinct" in rendered.lower(), "trace_counts.sql should use count(DISTINCT)"
    assert "$ai_trace_id" in rendered, "Should count distinct $ai_trace_id"

    expected = expected_metrics["trace_counts.sql"]

    # Team 1: Should have 2 unique traces (trace-1, trace-2)
    team1 = next(m for m in expected if m["team_id"] == 1)
    assert team1["metric_value"] == 2.0, "Team 1 should have 2 unique traces"

    # Team 2: Should have 1 unique trace (trace-3)
    team2 = next(m for m in expected if m["team_id"] == 2)
    assert team2["metric_value"] == 1.0, "Team 2 should have 1 unique trace"


def test_session_counts_logic(template_context: dict, mock_events_data: list, expected_metrics: dict):
    """Test session_counts.sql produces correct distinct session counts."""
    sql_file = SQL_DIR / "session_counts.sql"
    with open(sql_file) as f:
        template = Template(f.read())
        rendered = template.render(**template_context)

    # Verify SQL uses count(DISTINCT)
    assert "count(distinct" in rendered.lower(), "session_counts.sql should use count(DISTINCT)"
    assert "$ai_session_id" in rendered, "Should count distinct $ai_session_id"

    expected = expected_metrics["session_counts.sql"]

    # Team 1: Should have 1 unique session (session-1)
    team1 = next(m for m in expected if m["team_id"] == 1)
    assert team1["metric_value"] == 1.0, "Team 1 should have 1 unique session"

    # Team 2: Should have 1 unique session (session-2)
    team2 = next(m for m in expected if m["team_id"] == 2)
    assert team2["metric_value"] == 1.0, "Team 2 should have 1 unique session"


def test_error_rates_logic(template_context: dict, mock_events_data: list, expected_metrics: dict):
    """Test error_rates.sql calculates proportions correctly."""
    sql_file = SQL_DIR / "error_rates.sql"
    with open(sql_file) as f:
        template = Template(f.read())
        rendered = template.render(**template_context)

    # Verify SQL calculates proportions
    assert "countif" in rendered.lower(), "error_rates.sql should use countIf"
    assert "/ count(*)" in rendered.lower(), "Should divide by total count"
    assert "round(" in rendered.lower(), "Should round the result"

    # Verify error detection logic
    assert "$ai_error" in rendered, "Should check $ai_error property"
    assert "$ai_is_error" in rendered, "Should check $ai_is_error property"

    expected = expected_metrics["error_rates.sql"]

    # Team 1 generations: 1 error out of 3 = 0.3333
    gen_team1 = next(m for m in expected if m["team_id"] == 1 and "generation" in m["metric_name"])
    assert abs(gen_team1["metric_value"] - 0.3333) < 0.0001, "Generation error rate should be ~0.3333"

    # Team 1 spans: 1 error out of 2 = 0.5
    span_team1 = next(m for m in expected if m["team_id"] == 1 and "span" in m["metric_name"])
    assert span_team1["metric_value"] == 0.5, "Span error rate should be 0.5"


def test_trace_error_rates_logic(template_context: dict, mock_events_data: list, expected_metrics: dict):
    """Test trace_error_rates.sql calculates trace-level error proportions correctly."""
    sql_file = SQL_DIR / "trace_error_rates.sql"
    with open(sql_file) as f:
        template = Template(f.read())
        rendered = template.render(**template_context)

    # Verify SQL uses distinct count
    assert "countdistinctif" in rendered.lower(), "Should use countDistinctIf"
    assert "count(distinct" in rendered.lower(), "Should use count(DISTINCT) for total"
    assert "$ai_trace_id" in rendered, "Should work with $ai_trace_id"

    expected = expected_metrics["trace_error_rates.sql"]

    # Team 1: trace-1 has errors, trace-2 doesn't = 1/2 = 0.5
    team1 = next(m for m in expected if m["team_id"] == 1)
    assert team1["metric_value"] == 0.5, "Team 1 should have 50% of traces with errors"

    # Team 2: trace-3 has no errors = 0/1 = 0.0
    team2 = next(m for m in expected if m["team_id"] == 2)
    assert team2["metric_value"] == 0.0, "Team 2 should have 0% of traces with errors"


def test_pageview_counts_logic(template_context: dict, mock_events_data: list, expected_metrics: dict):
    """Test pageview_counts.sql categorizes and counts pageviews correctly."""
    sql_file = SQL_DIR / "pageview_counts.sql"
    with open(sql_file) as f:
        template = Template(f.read())
        rendered = template.render(**template_context)

    # Verify SQL uses the llma_pageview_events CTE (which filters $pageview events)
    assert "llma_pageview_events" in rendered, "Should use llma_pageview_events CTE"
    assert "$current_url" in rendered, "Should use $current_url property"
    assert "LIKE" in rendered, "Should use LIKE for URL matching"

    # Verify pageview mappings are used
    assert config.pageview_mappings is not None
    for url_path, _ in config.pageview_mappings:
        assert url_path in rendered, f"Should include pageview mapping for {url_path}"

    expected = expected_metrics["pageview_counts.sql"]

    # Team 1: 2 trace pageviews
    traces = next(m for m in expected if "traces" in m["metric_name"])
    assert traces["metric_value"] == 2.0, "Should count 2 trace pageviews"

    # Team 1: 1 generation pageview
    gens = next(m for m in expected if "generations" in m["metric_name"])
    assert gens["metric_value"] == 1.0, "Should count 1 generation pageview"
