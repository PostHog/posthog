"""hogli wrapper for comparing US/EU feature flags, backed by Metabase instead of a personal API key.

Fetches `posthog_featureflag` rows from each region's app Postgres via Metabase (see
`hogli metabase:login`) and hands them to `products.feature_flags.scripts.region_report`
for the diffing/reporting logic - this module only owns the Metabase-specific transport.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import click

from products.feature_flags.scripts.region_report import (
    FlagSummary,
    diff_flags,
    print_differences_section,
    print_flag_only_section,
    summarize_flag,
    write_json_report,
)

from hogli_commands.metabase import get_dataset_rows, resolve_database_id

DEFAULT_US_TEAM_ID = 2
DEFAULT_EU_TEAM_ID = 1
_APP_DATABASE_ENGINE = "postgres"


def _fetch_flags(region: str, team_id: int, database_id: int) -> dict[str, FlagSummary]:
    """Fetch every non-deleted flag (active and archived) for a team, keyed by flag key."""
    sql = (
        "SELECT key, name, active, archived, filters::text AS filters "
        f"FROM posthog_featureflag WHERE team_id = {team_id} AND deleted = false"
    )
    cols, rows = get_dataset_rows(region, database_id, sql)

    flags: dict[str, FlagSummary] = {}
    for row in rows:
        record = dict(zip(cols, row))
        record["filters"] = json.loads(record["filters"]) if record.get("filters") else {}
        summary = summarize_flag(record)
        flags[summary.key] = summary
    return flags


def _fetch_region(region: str, team_id: int, database_id: int | None) -> dict[str, FlagSummary]:
    """Resolve the app database id if not given, then fetch that region's flags."""
    if database_id is None:
        database_id = resolve_database_id(
            region, name_contains=f"posthog postgres prod {region}", engine=_APP_DATABASE_ENGINE
        )
    return _fetch_flags(region, team_id, database_id)


@click.command(
    name="flags:compare-regions",
    help="Compare feature flag definitions between PostHog's US and EU dogfood projects",
)
@click.option("--us-team-id", type=int, default=DEFAULT_US_TEAM_ID, show_default=True, help="US team (project) ID")
@click.option("--eu-team-id", type=int, default=DEFAULT_EU_TEAM_ID, show_default=True, help="EU team (project) ID")
@click.option(
    "--us-database-id",
    type=int,
    default=None,
    help="Metabase database id for the US app Postgres (auto-resolved by name if omitted)",
)
@click.option(
    "--eu-database-id",
    type=int,
    default=None,
    help="Metabase database id for the EU app Postgres (auto-resolved by name if omitted)",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write the full comparison as JSON to this file",
)
def flags_compare_regions(
    us_team_id: int,
    eu_team_id: int,
    us_database_id: int | None,
    eu_database_id: int | None,
    output: str | None,
) -> None:
    """Requires `hogli metabase:login --region us` and `--region eu` first."""
    with ThreadPoolExecutor(max_workers=2) as executor:
        us_future = executor.submit(_fetch_region, "us", us_team_id, us_database_id)
        eu_future = executor.submit(_fetch_region, "eu", eu_team_id, eu_database_id)
        us_flags = us_future.result()
        eu_flags = eu_future.result()

    only_us, only_eu, differences = diff_flags(us_flags, eu_flags)
    common_count = len(us_flags) - len(only_us)

    click.echo("US vs EU feature flag comparison")
    click.echo(f"US flags: {len(us_flags)}  EU flags: {len(eu_flags)}  Common: {common_count}")
    print_flag_only_section("Flags only in US", only_us)
    print_flag_only_section("Flags only in EU", only_eu)
    print_differences_section(differences)

    if output:
        write_json_report(output, only_us, only_eu, differences)
