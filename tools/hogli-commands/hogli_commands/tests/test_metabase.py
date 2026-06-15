from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from unittest.mock import patch

import click
from click.testing import CliRunner
from hogli.cli import cli
from hogli_commands import metabase


class _FakeCookie:
    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self.value = value


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(metabase, "CACHE_DIR", tmp_path)
    yield tmp_path


def test_format_cookie_header_joins_with_semicolons() -> None:
    header = metabase._format_cookie_header({"a": "1", "b": "2"})
    assert header == "a=1; b=2"


def test_cookie_path_per_region(cache_dir: Path) -> None:
    assert metabase._cookie_path("us") == cache_dir / "cookie-us"
    assert metabase._cookie_path("eu") == cache_dir / "cookie-eu"


def test_write_cookie_file_is_owner_only(cache_dir: Path) -> None:
    path = metabase._write_cookie_file("us", "metabase.SESSION=abc")
    assert path.read_text() == "metabase.SESSION=abc"
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_read_cookie_file_returns_none_when_missing(cache_dir: Path) -> None:
    assert metabase._read_cookie_file("us") is None


def test_read_cookie_file_strips_trailing_whitespace(cache_dir: Path) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc\n")
    assert metabase._read_cookie_file("us") == "metabase.SESSION=abc"


def test_load_cookies_filters_to_required_names(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_jar = [
        _FakeCookie("metabase.SESSION", "s"),
        _FakeCookie("metabase.DEVICE", "d"),
        _FakeCookie("ph_int_auth-0", "a0"),
        _FakeCookie("ph_int_auth-1", "a1"),
        _FakeCookie("unrelated", "x"),
    ]

    class FakeBC3:
        @staticmethod
        def chrome(domain_name: str, cookie_file: str | None = None) -> list[_FakeCookie]:
            assert domain_name == "metabase.prod-us.posthog.dev"
            assert cookie_file == "/fake/profile/Cookies"
            return fake_jar

    import sys

    monkeypatch.setitem(sys.modules, "browser_cookie3", FakeBC3)
    monkeypatch.setattr(
        metabase,
        "_enumerate_cookie_files",
        lambda browser: [("chrome", Path("/fake/profile/Cookies"))],
    )
    cookies = metabase._load_cookies_from_browser("metabase.prod-us.posthog.dev", "chrome")
    assert cookies == {
        "metabase.SESSION": "s",
        "metabase.DEVICE": "d",
        "ph_int_auth-0": "a0",
        "ph_int_auth-1": "a1",
    }


def test_enumerate_cookie_files_globs_chromium_profiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    chrome_root = tmp_path / "Chrome"
    (chrome_root / "Default").mkdir(parents=True)
    (chrome_root / "Default" / "Cookies").touch()
    (chrome_root / "Profile 1").mkdir()
    (chrome_root / "Profile 1" / "Cookies").touch()
    monkeypatch.setattr(metabase, "_CHROMIUM_PROFILE_ROOTS", {"chrome": [chrome_root]})

    targets = metabase._enumerate_cookie_files("chrome")
    cookie_files = [str(p) for _, p in targets]
    assert any("Default/Cookies" in p for p in cookie_files)
    assert any("Profile 1/Cookies" in p for p in cookie_files)


def test_load_cookies_unsupported_browser_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeBC3:
        pass

    import sys

    monkeypatch.setitem(sys.modules, "browser_cookie3", FakeBC3)
    with pytest.raises(click.ClickException, match="Unsupported browser"):
        metabase._load_cookies_from_browser("metabase.prod-us.posthog.dev", "lynx")


def test_metabase_cookie_command_errors_when_no_cache(cache_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:cookie", "--region", "us"])
    assert result.exit_code != 0
    assert "No cached cookie" in result.output


def test_metabase_cookie_command_prints_cached_value(cache_dir: Path) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc; metabase.DEVICE=def")
    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:cookie", "--region", "us"])
    assert result.exit_code == 0, result.output
    assert "metabase.SESSION=abc; metabase.DEVICE=def" in result.output


def test_metabase_cookie_check_validates_via_http(cache_dir: Path) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc; metabase.DEVICE=d; ph_int_auth-0=a; ph_int_auth-1=b")
    runner = CliRunner()
    with patch.object(metabase, "_check_cookie", return_value=False) as check:
        result = runner.invoke(cli, ["metabase:cookie", "--region", "us", "--check"])
    assert result.exit_code != 0
    assert "no longer valid" in result.output
    check.assert_called_once()


def test_metabase_cookie_requires_region_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:cookie"])
    assert result.exit_code != 0
    assert "--region" in result.output


def test_metabase_login_writes_cookie_after_validation(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {
        "metabase.SESSION": "s",
        "metabase.DEVICE": "d",
        "ph_int_auth-0": "a0",
        "ph_int_auth-1": "a1",
    }
    monkeypatch.setattr(metabase, "_load_cookies_from_browser", lambda domain, browser: captured)
    monkeypatch.setattr(metabase, "_check_cookie", lambda domain, header: True)
    monkeypatch.setattr(metabase.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:login", "--region", "eu", "--no-open"])
    assert result.exit_code == 0, result.output

    saved = (cache_dir / "cookie-eu").read_text()
    assert saved == "metabase.SESSION=s; metabase.DEVICE=d; ph_int_auth-0=a0; ph_int_auth-1=a1"
    mode = os.stat(cache_dir / "cookie-eu").st_mode & 0o777
    assert mode == 0o600


def test_metabase_login_requires_region_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:login", "--no-open"])
    assert result.exit_code != 0
    assert "--region" in result.output


def test_metabase_login_fast_paths_already_valid_session(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {name: f"{name}-val" for name in metabase.REQUIRED_COOKIES}
    monkeypatch.setattr(metabase, "_load_cookies_from_browser", lambda domain, browser: captured)
    monkeypatch.setattr(metabase, "_check_cookie", lambda domain, header: True)
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)
    opens: list[str] = []

    def record_open(url: str) -> bool:
        opens.append(url)
        return True

    monkeypatch.setattr(metabase.webbrowser, "open", record_open)

    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:login", "--region", "us"])
    assert result.exit_code == 0, result.output
    assert opens == [], "browser should not open when session is already valid"
    assert "already logged in" in result.output


def test_wait_for_valid_cookie_returns_when_session_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    sequence = [
        {},
        {"metabase.SESSION": "s"},
        {name: name + "-val" for name in metabase.REQUIRED_COOKIES},
    ]
    calls = iter(sequence)
    monkeypatch.setattr(metabase, "_load_cookies_from_browser", lambda d, b: next(calls))
    monkeypatch.setattr(metabase, "_check_cookie", lambda d, h: True)
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    header = metabase._wait_for_valid_cookie("metabase.example", None, timeout=10.0, interval=0.0)
    expected = metabase._format_cookie_header({name: name + "-val" for name in metabase.REQUIRED_COOKIES})
    assert header == expected


def test_wait_for_valid_cookie_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metabase, "_load_cookies_from_browser", lambda d, b: {})
    monkeypatch.setattr(metabase, "_check_cookie", lambda d, h: False)
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    # Return 0.0 twice (start + flush-hint check), then saturate past the deadline.
    # Saturating instead of exhausting the iterator keeps the test resilient if
    # someone adds another `time.monotonic()` call inside the loop later.
    call_count = {"n": 0}

    def fake_monotonic() -> float:
        call_count["n"] += 1
        return 0.0 if call_count["n"] <= 2 else 100.0

    monkeypatch.setattr(metabase.time, "monotonic", fake_monotonic)

    with pytest.raises(click.ClickException, match="Timed out"):
        metabase._wait_for_valid_cookie("metabase.example", None, timeout=10.0, interval=0.0)


def test_require_cookie_header_errors_when_missing(cache_dir: Path) -> None:
    with pytest.raises(click.ClickException, match="No cached cookie"):
        metabase._require_cookie_header("us")


def test_require_cookie_header_returns_cached(cache_dir: Path) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc")
    assert metabase._require_cookie_header("us") == "metabase.SESSION=abc"


def test_render_rows_tsv_formats_cols_and_rows() -> None:
    body = {
        "data": {
            "cols": [{"name": "team_id"}, {"name": "count"}, {"name": "label"}],
            "rows": [[1, 10, "a"], [2, None, "b"]],
        },
        "status": "completed",
    }
    out = metabase._render_rows_tsv(body)
    assert out == "team_id\tcount\tlabel\n1\t10\ta\n2\t\tb\n"


def test_metabase_databases_prints_table(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc")
    fake = {
        "data": [
            {"id": 42, "name": "ClickHouse", "engine": "clickhouse"},
            {"id": 38, "name": "Postgres", "engine": "postgres"},
        ]
    }
    monkeypatch.setattr(metabase, "_metabase_get", lambda region, path, timeout=30.0: fake)

    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:databases", "--region", "us"])
    assert result.exit_code == 0, result.output
    assert "42" in result.output and "ClickHouse" in result.output
    assert "38" in result.output and "Postgres" in result.output


def test_metabase_databases_json_format(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc")
    fake = [{"id": 42, "name": "ClickHouse", "engine": "clickhouse"}]  # bare-list form
    monkeypatch.setattr(metabase, "_metabase_get", lambda region, path, timeout=30.0: fake)

    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:databases", "--region", "us", "--format", "json"])
    assert result.exit_code == 0, result.output
    import json as _json

    parsed = _json.loads(result.output)
    assert parsed == [{"id": 42, "name": "ClickHouse", "engine": "clickhouse"}]


def test_metabase_query_requires_database_id() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:query", "--region", "us"], input="SELECT 1\n")
    assert result.exit_code != 0
    assert "--database-id" in result.output


def test_metabase_query_emits_tsv(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc")
    fake = {
        "status": "completed",
        "row_count": 2,
        "data": {"cols": [{"name": "x"}], "rows": [[1], [2]]},
    }
    monkeypatch.setattr(metabase, "_metabase_post_dataset", lambda region, db, sql, timeout=120.0: fake)

    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:query", "--region", "us", "--database-id", "42"], input="SELECT 1\n")
    assert result.exit_code == 0, result.output
    assert result.output == "x\n1\n2\n"


def test_metabase_query_surface_query_failure(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc")
    fake = {"status": "failed", "error": "syntax error near 'SELEKT'"}
    monkeypatch.setattr(metabase, "_metabase_post_dataset", lambda region, db, sql, timeout=120.0: fake)

    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:query", "--region", "us", "--database-id", "42"], input="SELEKT 1\n")
    assert result.exit_code != 0
    assert "syntax error" in result.output


def test_metabase_query_save_to_file(cache_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc")
    fake = {
        "status": "completed",
        "row_count": 1,
        "data": {"cols": [{"name": "x"}], "rows": [[42]]},
    }
    monkeypatch.setattr(metabase, "_metabase_post_dataset", lambda region, db, sql, timeout=120.0: fake)

    out_path = tmp_path / "out.tsv"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["metabase:query", "--region", "us", "--database-id", "42", "--save", str(out_path)],
        input="SELECT 42\n",
    )
    assert result.exit_code == 0, result.output
    assert out_path.read_text() == "x\n42\n"
    assert "42" not in result.output.replace("Wrote", "")  # value didn't leak to stdout
    mode = out_path.stat().st_mode & 0o777
    assert mode == 0o600, f"--save output must be owner-only, got {oct(mode)}"


def test_metabase_query_rejects_empty_sql(cache_dir: Path) -> None:
    metabase._write_cookie_file("us", "metabase.SESSION=abc")
    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:query", "--region", "us", "--database-id", "42"], input="")
    assert result.exit_code != 0
    assert "No SQL provided" in result.output
