#!/usr/bin/env python
"""
Test script to verify session-based filtering works correctly for web overview queries.
This script tests the new useSessionBasedFiltering modifier added for asset checks.
"""

from datetime import datetime, UTC
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.schema import WebOverviewQuery, DateRange, HogQLQueryModifiers
from posthog.models import Team

def test_session_based_filtering():
    """Test that session-based filtering produces different results than regular filtering"""
    
    # Use the same team and date range as the asset checks
    team_id = 2
    date_from = '2025-06-30'
    date_to = '2025-07-07'
    
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        print(f"Team {team_id} does not exist. Please adjust the team_id.")
        return
    
    # Create the query
    query = WebOverviewQuery(
        dateRange=DateRange(date_from=date_from, date_to=date_to),
        properties=[],
    )
    
    # Test 1: Regular filtering (current behavior)
    print("Testing regular filtering...")
    modifiers_regular = HogQLQueryModifiers(
        useWebAnalyticsPreAggregatedTables=False,
        convertToProjectTimezone=False,
        useSessionBasedFiltering=False
    )
    
    runner_regular = WebOverviewQueryRunner(query=query, team=team, modifiers=modifiers_regular)
    response_regular = runner_regular.calculate()
    
    # Test 2: Session-based filtering (new behavior)
    print("Testing session-based filtering...")
    modifiers_session = HogQLQueryModifiers(
        useWebAnalyticsPreAggregatedTables=False,
        convertToProjectTimezone=False,
        useSessionBasedFiltering=True
    )
    
    runner_session = WebOverviewQueryRunner(query=query, team=team, modifiers=modifiers_session)
    response_session = runner_session.calculate()
    
    # Test 3: Pre-aggregated tables (for comparison)
    print("Testing pre-aggregated tables...")
    modifiers_pre_agg = HogQLQueryModifiers(
        useWebAnalyticsPreAggregatedTables=True,
        convertToProjectTimezone=False,
    )
    
    runner_pre_agg = WebOverviewQueryRunner(query=query, team=team, modifiers=modifiers_pre_agg)
    response_pre_agg = runner_pre_agg.calculate()
    
    # Compare results
    print(f"\n=== Results Comparison ===")
    print(f"Date range: {date_from} to {date_to}")
    print(f"Team: {team_id}")
    
    def extract_metrics(response):
        return {item.key: item.value for item in response.results if item.value is not None}
    
    regular_metrics = extract_metrics(response_regular)
    session_metrics = extract_metrics(response_session)
    pre_agg_metrics = extract_metrics(response_pre_agg)
    
    print(f"\nRegular filtering:")
    for key, value in regular_metrics.items():
        print(f"  {key}: {value}")
    
    print(f"\nSession-based filtering:")
    for key, value in session_metrics.items():
        print(f"  {key}: {value}")
    
    print(f"\nPre-aggregated tables:")
    for key, value in pre_agg_metrics.items():
        print(f"  {key}: {value}")
    
    # Check if session-based filtering matches pre-aggregated more closely
    print(f"\n=== Comparison Analysis ===")
    
    for metric in set(regular_metrics.keys()) & set(session_metrics.keys()) & set(pre_agg_metrics.keys()):
        regular_val = regular_metrics[metric]
        session_val = session_metrics[metric]
        pre_agg_val = pre_agg_metrics[metric]
        
        if regular_val != 0:
            regular_diff = abs(regular_val - pre_agg_val) / regular_val * 100
        else:
            regular_diff = 0 if pre_agg_val == 0 else 100
            
        if session_val != 0:
            session_diff = abs(session_val - pre_agg_val) / session_val * 100
        else:
            session_diff = 0 if pre_agg_val == 0 else 100
        
        print(f"{metric}:")
        print(f"  Regular vs Pre-agg: {regular_diff:.2f}% difference")
        print(f"  Session vs Pre-agg: {session_diff:.2f}% difference")
        print(f"  Session-based filtering {'✓' if session_diff < regular_diff else '✗'} closer to pre-aggregated")
    
    # Test that used pre-aggregated tables flag is set correctly
    print(f"\n=== Pre-aggregated Usage ===")
    print(f"Regular query used pre-aggregated: {response_regular.usedPreAggregatedTables}")
    print(f"Session query used pre-aggregated: {response_session.usedPreAggregatedTables}")
    print(f"Pre-agg query used pre-aggregated: {response_pre_agg.usedPreAggregatedTables}")

if __name__ == "__main__":
    test_session_based_filtering()