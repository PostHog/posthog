#!/usr/bin/env python
"""
Quick test script for LLMA daily metrics aggregation.

Run this after ./bin/migrate to test the pipeline locally.
"""
# ruff: noqa: T201

from datetime import datetime, timedelta

from posthog.clickhouse.client import sync_execute

from dags.llma.metrics_daily import get_delete_query, get_insert_query


def test_llma_metrics():
    """Test LLMA metrics aggregation for yesterday."""
    print("=" * 60)
    print("LLMA Metrics Daily Aggregation Test")
    print("=" * 60)

    # Check table exists
    print("\n1. Checking table exists...")
    result = sync_execute("SHOW TABLES LIKE 'llma_metrics_daily'")
    if not result:
        print("   ❌ Table llma_metrics_daily does not exist!")
        print("   Run: ./bin/migrate")
        return
    print("   ✓ Table llma_metrics_daily exists")

    # Get yesterday's date
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

    print(f"\n2. Aggregating metrics for {yesterday}...")

    # Delete existing data
    delete_sql = get_delete_query(yesterday, today)
    sync_execute(delete_sql)
    print("   ✓ Deleted existing data")

    # Insert aggregated metrics
    insert_sql = get_insert_query(yesterday, today)
    try:
        sync_execute(insert_sql)
        print("   ✓ Inserted aggregated metrics")
    except Exception as e:
        print(f"   ❌ Failed to insert: {e}")
        return

    # Query results
    print(f"\n3. Results for {yesterday}:")
    result = sync_execute(
        """
        SELECT
            date,
            metric_name,
            count(*) as teams,
            sum(metric_value) as total
        FROM llma_metrics_daily
        WHERE date = %(date)s
        GROUP BY date, metric_name
        ORDER BY metric_name
    """,
        {"date": yesterday},
    )

    if not result:
        print("   No AI events found for yesterday")
        print("   (This is normal if you don't have AI events in your local instance)")
    else:
        print(f"\n   Date: {yesterday}")
        for row in result:
            metric_name = row[1]
            teams = row[2]
            total = row[3]
            if "_error_rate" in metric_name:
                print(f"   {metric_name:25s}: {total:6.2f}% error rate across {teams} team(s)")
            else:
                print(f"   {metric_name:25s}: {total:6.0f} events across {teams} team(s)")

    # Show sample data
    print("\n4. Sample rows:")
    sample = sync_execute(
        """
        SELECT date, team_id, metric_name, metric_value
        FROM llma_metrics_daily
        ORDER BY date DESC, team_id, metric_name
        LIMIT 10
    """
    )

    if not sample:
        print("   No data in table")
    else:
        for row in sample:
            metric_name = row[2]
            metric_value = row[3]
            if "_error_rate" in metric_name:
                print(f"   {row[0]} | Team {row[1]:3.0f} | {metric_name:25s} | {metric_value:6.2f}%")
            else:
                print(f"   {row[0]} | Team {row[1]:3.0f} | {metric_name:25s} | {metric_value:6.0f}")

    print("\n" + "=" * 60)
    print("✓ Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    test_llma_metrics()
