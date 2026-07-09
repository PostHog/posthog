from __future__ import annotations

import pytest
from unittest.mock import patch

from click.testing import CliRunner
from hogli.cli import cli
from hogli_commands import flags

from products.feature_flags.scripts.region_report import FlagSummary


def _summary(key: str, active: bool = True, rollout: int | None = 100) -> FlagSummary:
    return FlagSummary(
        key=key, name=key, active=active, archived=False, max_rollout_percentage=rollout, is_multivariate=False
    )


def test_fetch_flags_parses_cols_and_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    cols = ["key", "name", "active", "archived", "filters"]
    rows = [["my-flag", "My flag", True, False, '{"groups": [{"rollout_percentage": 25}]}']]
    monkeypatch.setattr(flags, "get_dataset_rows", lambda region, db, sql: (cols, rows))

    result = flags._fetch_flags("us", team_id=2, database_id=34)

    assert set(result) == {"my-flag"}
    assert result["my-flag"].max_rollout_percentage == 25


def test_fetch_region_skips_resolution_when_database_id_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flags, "_fetch_flags", lambda region, team_id, database_id: {"x": database_id})
    with patch.object(flags, "resolve_database_id") as resolve:
        result = flags._fetch_region("us", team_id=2, database_id=34)
    assert result == {"x": 34}
    resolve.assert_not_called()


def test_fetch_region_resolves_when_database_id_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flags, "resolve_database_id", lambda region, *, name_contains, engine: 99)
    monkeypatch.setattr(flags, "_fetch_flags", lambda region, team_id, database_id: {"x": database_id})
    result = flags._fetch_region("us", team_id=2, database_id=None)
    assert result == {"x": 99}


def test_compare_regions_prints_diff_and_skips_resolution_with_explicit_db_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    us_flags = {"us-only": _summary("us-only")}
    eu_flags = {"us-only": _summary("us-only", active=False)}
    monkeypatch.setattr(
        flags, "_fetch_flags", lambda region, team_id, database_id: us_flags if region == "us" else eu_flags
    )

    with patch.object(flags, "resolve_database_id") as resolve:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["flags:compare-regions", "--us-database-id", "34", "--eu-database-id", "34"],
        )

    assert result.exit_code == 0, result.output
    assert "US flags: 1  EU flags: 1  Common: 1" in result.output
    assert "us-only" in result.output
    resolve.assert_not_called()


def test_compare_regions_reports_each_section(monkeypatch: pytest.MonkeyPatch) -> None:
    us_flags = {"us-only": _summary("us-only"), "shared": _summary("shared", active=True)}
    eu_flags = {"eu-only": _summary("eu-only"), "shared": _summary("shared", active=False)}
    monkeypatch.setattr(
        flags, "_fetch_flags", lambda region, team_id, database_id: us_flags if region == "us" else eu_flags
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["flags:compare-regions", "--us-database-id", "34", "--eu-database-id", "34"],
    )

    assert result.exit_code == 0, result.output
    eu_idx = result.output.index("Flags only in EU")
    assert result.output.index("us-only") < eu_idx
    assert eu_idx < result.output.index("eu-only")
