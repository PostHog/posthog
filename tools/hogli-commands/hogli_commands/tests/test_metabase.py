from __future__ import annotations

import os
import plistlib
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

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
    candidates = list(metabase._iter_cookie_candidates("metabase.prod-us.posthog.dev", "chrome"))
    assert candidates == [
        {
            "metabase.SESSION": "s",
            "metabase.DEVICE": "d",
            "ph_int_auth-0": "a0",
            "ph_int_auth-1": "a1",
        }
    ]


def test_load_cookies_dia_uses_chromium_based_with_dia_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_kwargs: dict = {}
    complete_jar = [
        _FakeCookie("metabase.SESSION", "s"),
        _FakeCookie("metabase.DEVICE", "d"),
        _FakeCookie("ph_int_auth-0", "a0"),
        _FakeCookie("ph_int_auth-1", "a1"),
    ]

    class FakeChromiumBased:
        def __init__(self, **kwargs: object) -> None:
            seen_kwargs.update(kwargs)

        def load(self) -> list[_FakeCookie]:
            return complete_jar

    class FakeBC3:
        ChromiumBased = FakeChromiumBased

    import sys

    monkeypatch.setitem(sys.modules, "browser_cookie3", FakeBC3)
    monkeypatch.setattr(
        metabase,
        "_enumerate_cookie_files",
        lambda browser: [("dia", Path("/fake/dia/Default/Cookies"))],
    )
    candidates = list(metabase._iter_cookie_candidates("metabase.prod-us.posthog.dev", "dia"))
    assert candidates == [
        {"metabase.SESSION": "s", "metabase.DEVICE": "d", "ph_int_auth-0": "a0", "ph_int_auth-1": "a1"}
    ]
    assert seen_kwargs["osx_key_service"] == "Dia Safe Storage"
    assert seen_kwargs["cookie_file"] == "/fake/dia/Default/Cookies"


def test_iter_cookie_candidates_never_merges_partial_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    # Profiles A and B are each partial but jointly cover REQUIRED_COOKIES; profile C
    # is complete on its own. Only C's set may appear — A and B are not candidates,
    # merged or otherwise, since their cookies belong to two different logins.
    jars_by_file = {
        "/a/Cookies": [_FakeCookie("metabase.SESSION", "s-a"), _FakeCookie("metabase.DEVICE", "d-a")],
        "/b/Cookies": [_FakeCookie("ph_int_auth-0", "a0-b"), _FakeCookie("ph_int_auth-1", "a1-b")],
        "/c/Cookies": [
            _FakeCookie("metabase.SESSION", "s-c"),
            _FakeCookie("metabase.DEVICE", "d-c"),
            _FakeCookie("ph_int_auth-0", "a0-c"),
            _FakeCookie("ph_int_auth-1", "a1-c"),
        ],
    }

    class FakeBC3:
        @staticmethod
        def chrome(domain_name: str, cookie_file: str | None = None) -> list[_FakeCookie]:
            return jars_by_file[cookie_file]

    import sys

    monkeypatch.setitem(sys.modules, "browser_cookie3", FakeBC3)
    monkeypatch.setattr(
        metabase,
        "_enumerate_cookie_files",
        lambda browser: [
            ("chrome", Path("/a/Cookies")),
            ("chrome", Path("/b/Cookies")),
            ("chrome", Path("/c/Cookies")),
        ],
    )

    candidates = list(metabase._iter_cookie_candidates("metabase.prod-us.posthog.dev", "chrome"))
    assert candidates == [
        {
            "metabase.SESSION": "s-c",
            "metabase.DEVICE": "d-c",
            "ph_int_auth-0": "a0-c",
            "ph_int_auth-1": "a1-c",
        }
    ]


def test_find_valid_candidate_ignores_partial_profiles_and_never_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jars_by_file = {
        "/a/Cookies": [_FakeCookie("metabase.SESSION", "s-a"), _FakeCookie("metabase.DEVICE", "d-a")],
        "/b/Cookies": [_FakeCookie("ph_int_auth-0", "a0-b"), _FakeCookie("ph_int_auth-1", "a1-b")],
    }

    class FakeBC3:
        @staticmethod
        def chrome(domain_name: str, cookie_file: str | None = None) -> list[_FakeCookie]:
            return jars_by_file[cookie_file]

    import sys

    monkeypatch.setitem(sys.modules, "browser_cookie3", FakeBC3)
    monkeypatch.setattr(
        metabase,
        "_enumerate_cookie_files",
        lambda browser: [("chrome", Path("/a/Cookies")), ("chrome", Path("/b/Cookies"))],
    )
    probe_calls: list[str] = []
    monkeypatch.setattr(metabase, "_probe_cookie", lambda domain, header: probe_calls.append(header) or True)

    header, any_candidate = metabase._find_valid_candidate("metabase.prod-us.posthog.dev", "chrome")
    assert header is None
    assert any_candidate is False
    assert probe_calls == []


def test_find_valid_candidate_stops_after_first_valid_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    complete = [
        _FakeCookie("metabase.SESSION", "s"),
        _FakeCookie("metabase.DEVICE", "d"),
        _FakeCookie("ph_int_auth-0", "a0"),
        _FakeCookie("ph_int_auth-1", "a1"),
    ]
    calls: list[str] = []

    class FakeBC3:
        @staticmethod
        def chrome(domain_name: str, cookie_file: str | None = None) -> list[_FakeCookie]:
            calls.append(cookie_file or "default")
            if cookie_file == "/first/Cookies":
                return complete
            raise AssertionError("must not read a later profile once one validates")

    import sys

    monkeypatch.setitem(sys.modules, "browser_cookie3", FakeBC3)
    monkeypatch.setattr(
        metabase,
        "_enumerate_cookie_files",
        lambda browser: [("chrome", Path("/first/Cookies")), ("chrome", Path("/second/Cookies"))],
    )
    monkeypatch.setattr(metabase, "_probe_cookie", lambda domain, header: True)

    header, any_candidate = metabase._find_valid_candidate("metabase.prod-us.posthog.dev", "chrome")
    expected = metabase._format_cookie_header(
        {"metabase.SESSION": "s", "metabase.DEVICE": "d", "ph_int_auth-0": "a0", "ph_int_auth-1": "a1"}
    )
    assert header == expected
    assert any_candidate is True
    assert calls == ["/first/Cookies"]


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        pytest.param(200, True, id="200-accepted"),
        pytest.param(302, False, id="302-sso-redirect"),
        pytest.param(303, False, id="303-sso-redirect"),
        pytest.param(401, False, id="401-unauthorized"),
        pytest.param(403, False, id="403-forbidden"),
        pytest.param(429, None, id="429-rate-limited"),
        pytest.param(502, None, id="502-bad-gateway"),
        pytest.param(503, None, id="503-unavailable"),
    ],
)
def test_probe_cookie_classifies_the_response(
    monkeypatch: pytest.MonkeyPatch, status_code: int, expected: bool | None
) -> None:
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: SimpleNamespace(status_code=status_code))
    assert metabase._probe_cookie("metabase.example", "cookie=1") is expected


def test_probe_cookie_returns_none_on_request_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    def raise_request_exception(*args: object, **kwargs: object) -> None:
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "get", raise_request_exception)
    assert metabase._probe_cookie("metabase.example", "cookie=1") is None


def test_check_cookie_treats_inconclusive_the_same_as_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # _check_cookie keeps its boolean contract for metabase:cookie --check,
    # which has no retry loop to give a transient failure a second chance.
    monkeypatch.setattr(metabase, "_probe_cookie", lambda domain, header, timeout=5.0: None)
    assert metabase._check_cookie("metabase.example", "cookie=1") is False


@pytest.mark.parametrize(
    ("probe_result", "remembered"),
    [
        pytest.param(False, True, id="rejected-is-remembered"),
        pytest.param(None, False, id="inconclusive-is-not-remembered"),
    ],
)
def test_find_valid_candidate_only_remembers_an_outright_rejection(
    monkeypatch: pytest.MonkeyPatch, probe_result: bool | None, remembered: bool
) -> None:
    candidate = {"metabase.SESSION": "s", "metabase.DEVICE": "d", "ph_int_auth-0": "a0", "ph_int_auth-1": "a1"}
    header = metabase._format_cookie_header(candidate)
    monkeypatch.setattr(
        metabase, "_iter_cookie_candidates", lambda domain, browser, seen_warnings=None: iter([candidate])
    )
    monkeypatch.setattr(metabase, "_probe_cookie", lambda domain, h: probe_result)

    rejected_headers: set[str] = set()
    result_header, _ = metabase._find_valid_candidate("metabase.example", None, rejected_headers=rejected_headers)
    assert result_header is None
    assert (header in rejected_headers) is remembered


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


def test_ordered_browsers_puts_default_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metabase, "_default_https_browser", lambda: "firefox")
    order = metabase._ordered_browsers(None)
    assert order[0] == "firefox"
    assert set(order) == set(metabase.SUPPORTED_BROWSERS), "reordering must never drop a browser"


def test_ordered_browsers_falls_back_when_default_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metabase, "_default_https_browser", lambda: None)
    assert metabase._ordered_browsers(None) == metabase.SUPPORTED_BROWSERS


def test_ordered_browsers_ignores_default_when_explicit_browser_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metabase, "_default_https_browser", lambda: "firefox")
    assert metabase._ordered_browsers("chrome") == ("chrome",)


def _plist_stub(bundle_id: str) -> Callable[..., SimpleNamespace]:
    plist = plistlib.dumps({"LSHandlers": [{"LSHandlerURLScheme": "https", "LSHandlerRoleAll": bundle_id}]})
    return lambda *args, **kwargs: SimpleNamespace(stdout=plist)


def _failing_subprocess_run(*args: object, **kwargs: object) -> SimpleNamespace:
    raise OSError("no defaults binary")


@pytest.mark.parametrize(
    ("platform", "run_stub", "expected"),
    [
        pytest.param("darwin", _plist_stub("org.mozilla.firefox"), "firefox", id="known-bundle-id"),
        pytest.param("darwin", _plist_stub("com.example.unknownbrowser"), None, id="unknown-bundle-id"),
        pytest.param("linux", _plist_stub("org.mozilla.firefox"), None, id="non-darwin"),
        pytest.param("darwin", _failing_subprocess_run, None, id="subprocess-failure"),
    ],
)
def test_default_https_browser(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    run_stub: Callable[..., SimpleNamespace],
    expected: str | None,
) -> None:
    metabase._default_https_browser.cache_clear()
    monkeypatch.setattr(metabase.sys, "platform", platform)
    monkeypatch.setattr(metabase.subprocess, "run", run_stub)
    try:
        assert metabase._default_https_browser() == expected
    finally:
        metabase._default_https_browser.cache_clear()


def test_load_cookies_unsupported_browser_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeBC3:
        pass

    import sys

    monkeypatch.setitem(sys.modules, "browser_cookie3", FakeBC3)
    with pytest.raises(click.ClickException, match="Unsupported browser"):
        # _iter_cookie_candidates is a generator, so the body (and its raise) only
        # runs once iterated.
        list(metabase._iter_cookie_candidates("metabase.prod-us.posthog.dev", "lynx"))


def test_load_cookies_warning_printed_once_across_repeated_calls(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeBC3:
        @staticmethod
        def firefox(domain_name: str, cookie_file: str | None = None) -> list[_FakeCookie]:
            raise RuntimeError("Failed to find Firefox cookie file")

    import sys

    monkeypatch.setitem(sys.modules, "browser_cookie3", FakeBC3)
    monkeypatch.setattr(metabase, "_enumerate_cookie_files", lambda browser: [("firefox", Path())])

    seen_warnings: set[str] = set()
    list(metabase._iter_cookie_candidates("metabase.prod-us.posthog.dev", "firefox", seen_warnings))
    list(metabase._iter_cookie_candidates("metabase.prod-us.posthog.dev", "firefox", seen_warnings))

    captured = capsys.readouterr()
    assert captured.err.count("Failed to find Firefox cookie file") == 1


def test_is_directory_blocked_false_for_missing_directory(tmp_path: Path) -> None:
    assert metabase._is_directory_blocked(tmp_path / "does-not-exist") is False


def test_is_directory_blocked_false_for_readable_directory(tmp_path: Path) -> None:
    root = tmp_path / "readable"
    root.mkdir()
    assert metabase._is_directory_blocked(root) is False


def test_is_directory_blocked_true_on_permission_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "blocked"
    root.mkdir()

    def raise_permission_error(path: object) -> None:
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(metabase.os, "scandir", raise_permission_error)
    assert metabase._is_directory_blocked(root) is True


def test_is_directory_blocked_true_for_chmod_000(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses unix permission bits")
    root = tmp_path / "locked"
    root.mkdir()
    root.chmod(0o000)
    try:
        assert metabase._is_directory_blocked(root) is True
    finally:
        root.chmod(0o700)


def test_detect_blocked_browsers_reports_chromium_and_firefox_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    chrome_root = Path("/fake/chrome")
    firefox_root = Path("/fake/firefox")
    monkeypatch.setattr(metabase, "_CHROMIUM_PROFILE_ROOTS", {"chrome": [chrome_root], "brave": [Path("/fake/brave")]})
    monkeypatch.setattr(metabase, "_FIREFOX_ROOT", firefox_root)
    monkeypatch.setattr(metabase, "_is_directory_blocked", lambda root: root in (chrome_root, firefox_root))

    assert metabase._detect_blocked_browsers(None) == ["chrome", "firefox"]


def test_detect_blocked_browsers_does_not_check_safari(monkeypatch: pytest.MonkeyPatch) -> None:
    # Safari's cookie store is a single binarycookies file, not a scanned directory,
    # so it never shows up as "blocked" here — browser_cookie3's own load error covers it.
    monkeypatch.setattr(metabase, "_is_directory_blocked", lambda root: True)
    assert metabase._detect_blocked_browsers("safari") == []


def test_detect_blocked_browsers_scoped_to_explicit_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metabase, "_is_directory_blocked", lambda root: True)
    assert metabase._detect_blocked_browsers("chrome") == ["chrome"]
    assert metabase._detect_blocked_browsers("firefox") == ["firefox"]


def test_all_readable_browsers_blocked_true_when_only_installed_candidates_are_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    chrome_root = tmp_path / "chrome"
    chrome_root.mkdir()
    firefox_root = tmp_path / "firefox"
    firefox_root.mkdir()
    monkeypatch.setattr(metabase, "_CHROMIUM_PROFILE_ROOTS", {"chrome": [chrome_root]})
    monkeypatch.setattr(metabase, "_FIREFOX_ROOT", firefox_root)
    monkeypatch.setattr(metabase, "_default_https_browser", lambda: None)

    assert metabase._all_readable_browsers_blocked(None, ["chrome", "firefox"]) is True


def test_all_readable_browsers_blocked_false_when_an_installed_candidate_is_unblocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arc is blocked, but Chrome is installed and readable, so SSO could still land there.
    chrome_root = tmp_path / "chrome"
    chrome_root.mkdir()
    arc_root = tmp_path / "arc"
    arc_root.mkdir()
    monkeypatch.setattr(metabase, "_CHROMIUM_PROFILE_ROOTS", {"chrome": [chrome_root], "arc": [arc_root]})
    monkeypatch.setattr(metabase, "_FIREFOX_ROOT", tmp_path / "does-not-exist")
    monkeypatch.setattr(metabase, "_default_https_browser", lambda: None)

    assert metabase._all_readable_browsers_blocked(None, ["arc"]) is False


def test_all_readable_browsers_blocked_true_when_no_candidate_is_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(metabase, "_CHROMIUM_PROFILE_ROOTS", {"chrome": [tmp_path / "does-not-exist"]})
    monkeypatch.setattr(metabase, "_FIREFOX_ROOT", tmp_path / "also-missing")
    monkeypatch.setattr(metabase, "_default_https_browser", lambda: None)

    assert metabase._all_readable_browsers_blocked(None, []) is True


@pytest.mark.parametrize(
    ("browser", "blocked"),
    [
        pytest.param(None, ["chrome", "firefox"], id="default-browser-is-safari"),
        pytest.param("safari", [], id="explicit-safari"),
    ],
)
def test_all_readable_browsers_blocked_false_for_safari(
    monkeypatch: pytest.MonkeyPatch, browser: str | None, blocked: list[str]
) -> None:
    # Safari isn't directory-checked, so a blocked Chrome/Firefox must not read as
    # "hopeless" when Safari is the browser actually in play.
    monkeypatch.setattr(metabase, "_default_https_browser", lambda: "safari")
    assert metabase._all_readable_browsers_blocked(browser, blocked) is False


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
    expected = metabase._format_cookie_header(
        {"metabase.SESSION": "s", "metabase.DEVICE": "d", "ph_int_auth-0": "a0", "ph_int_auth-1": "a1"}
    )
    monkeypatch.setattr(metabase, "_find_valid_candidate", lambda domain, browser: (expected, True))
    monkeypatch.setattr(metabase.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:login", "--region", "eu", "--no-open"])
    assert result.exit_code == 0, result.output

    saved = (cache_dir / "cookie-eu").read_text()
    assert saved == expected
    mode = os.stat(cache_dir / "cookie-eu").st_mode & 0o777
    assert mode == 0o600


def test_metabase_login_requires_region_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["metabase:login", "--no-open"])
    assert result.exit_code != 0
    assert "--region" in result.output


def test_metabase_login_fast_paths_already_valid_session(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = metabase._format_cookie_header({name: f"{name}-val" for name in metabase.REQUIRED_COOKIES})
    monkeypatch.setattr(metabase, "_find_valid_candidate", lambda domain, browser: (expected, True))
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
    expected = metabase._format_cookie_header({name: name + "-val" for name in metabase.REQUIRED_COOKIES})
    sequence = [
        (None, False),
        (None, True),
        (expected, True),
    ]
    calls = iter(sequence)
    monkeypatch.setattr(metabase, "_detect_blocked_browsers", lambda browser: [])
    monkeypatch.setattr(
        metabase,
        "_find_valid_candidate",
        lambda d, b, seen_warnings=None, rejected_headers=None: next(calls),
    )
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    header = metabase._wait_for_valid_cookie("metabase.example", None, timeout=10.0, interval=0.0)
    assert header == expected


def test_wait_for_valid_cookie_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metabase, "_detect_blocked_browsers", lambda browser: [])
    monkeypatch.setattr(
        metabase,
        "_find_valid_candidate",
        lambda d, b, seen_warnings=None, rejected_headers=None: (None, False),
    )
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


def test_wait_for_valid_cookie_raises_immediately_when_blocked_and_no_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metabase, "_detect_blocked_browsers", lambda browser: ["chrome"])
    monkeypatch.setattr(metabase, "_all_readable_browsers_blocked", lambda browser, blocked: True)
    monkeypatch.setattr(
        metabase,
        "_find_valid_candidate",
        lambda d, b, seen_warnings=None, rejected_headers=None: (None, False),
    )
    monkeypatch.setattr(metabase.sys, "platform", "darwin")
    sleep_calls: list[float] = []
    monkeypatch.setattr(metabase.time, "sleep", lambda s: sleep_calls.append(s))

    with pytest.raises(click.ClickException, match="chrome") as exc_info:
        metabase._wait_for_valid_cookie("metabase.example", None, timeout=180.0, interval=1.0)

    assert sleep_calls == [], "must stop before waiting out the poll interval, let alone the timeout"
    assert "Full Disk Access" in str(exc_info.value)


def test_wait_for_valid_cookie_blocked_message_omits_macos_hint_off_darwin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metabase, "_detect_blocked_browsers", lambda browser: ["chrome"])
    monkeypatch.setattr(metabase, "_all_readable_browsers_blocked", lambda browser, blocked: True)
    monkeypatch.setattr(
        metabase,
        "_find_valid_candidate",
        lambda d, b, seen_warnings=None, rejected_headers=None: (None, False),
    )
    monkeypatch.setattr(metabase.sys, "platform", "linux")
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    with pytest.raises(click.ClickException) as exc_info:
        metabase._wait_for_valid_cookie("metabase.example", None, timeout=180.0, interval=1.0)

    assert "Full Disk Access" not in str(exc_info.value)


def test_wait_for_valid_cookie_does_not_fail_fast_when_another_browser_might_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unrelated, unused browser being blocked (e.g. Arc, installed but never opened)
    # must not cut off SSO in the browser the user is actually completing it in.
    monkeypatch.setattr(metabase, "_detect_blocked_browsers", lambda browser: ["arc"])
    monkeypatch.setattr(metabase, "_all_readable_browsers_blocked", lambda browser, blocked: False)
    monkeypatch.setattr(
        metabase,
        "_find_valid_candidate",
        lambda d, b, seen_warnings=None, rejected_headers=None: (None, False),
    )
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    call_count = {"n": 0}

    def fake_monotonic() -> float:
        call_count["n"] += 1
        return 0.0 if call_count["n"] <= 2 else 100.0

    monkeypatch.setattr(metabase.time, "monotonic", fake_monotonic)

    with pytest.raises(click.ClickException, match="Timed out"):
        metabase._wait_for_valid_cookie("metabase.example", None, timeout=10.0, interval=0.0)


def test_wait_for_valid_cookie_keeps_polling_when_default_browser_is_safari(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Chrome is blocked, but Safari (the actual default) isn't directory-checked,
    # so this must not fail fast on the first empty poll.
    monkeypatch.setattr(metabase, "_detect_blocked_browsers", lambda browser: ["chrome"])
    monkeypatch.setattr(metabase, "_default_https_browser", lambda: "safari")
    monkeypatch.setattr(
        metabase,
        "_find_valid_candidate",
        lambda d, b, seen_warnings=None, rejected_headers=None: (None, False),
    )
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    call_count = {"n": 0}

    def fake_monotonic() -> float:
        call_count["n"] += 1
        return 0.0 if call_count["n"] <= 2 else 100.0

    monkeypatch.setattr(metabase.time, "monotonic", fake_monotonic)

    with pytest.raises(click.ClickException, match="Timed out"):
        metabase._wait_for_valid_cookie("metabase.example", None, timeout=10.0, interval=0.0)


def test_wait_for_valid_cookie_keeps_polling_and_notes_blocked_browser_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(metabase, "_detect_blocked_browsers", lambda browser: ["chrome"])
    monkeypatch.setattr(metabase, "_all_readable_browsers_blocked", lambda browser, blocked: False)
    monkeypatch.setattr(
        metabase,
        "_find_valid_candidate",
        lambda d, b, seen_warnings=None, rejected_headers=None: (None, True),
    )
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    call_count = {"n": 0}

    def fake_monotonic() -> float:
        call_count["n"] += 1
        return 0.0 if call_count["n"] <= 3 else 100.0

    monkeypatch.setattr(metabase.time, "monotonic", fake_monotonic)

    with pytest.raises(click.ClickException, match="Timed out"):
        metabase._wait_for_valid_cookie("metabase.example", None, timeout=10.0, interval=0.0)

    captured = capsys.readouterr()
    assert captured.out.count("chrome") == 1


def test_wait_for_valid_cookie_skips_expired_first_candidate_and_reaches_the_next_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired = {"metabase.SESSION": "old", "metabase.DEVICE": "old", "ph_int_auth-0": "old", "ph_int_auth-1": "old"}
    valid = {"metabase.SESSION": "new", "metabase.DEVICE": "new", "ph_int_auth-0": "new", "ph_int_auth-1": "new"}
    expired_header = metabase._format_cookie_header(expired)
    valid_header = metabase._format_cookie_header(valid)
    poll_count = {"n": 0}
    check_calls: dict[str, int] = {}

    def fake_iter_candidates(
        domain: str, browser: str | None, seen_warnings: set[str] | None = None
    ) -> Iterator[dict[str, str]]:
        # A second profile with the real, valid session only shows up from the
        # second poll onward (e.g. the user was still completing SSO there).
        poll_count["n"] += 1
        yield expired
        if poll_count["n"] >= 2:
            yield valid

    def fake_probe_cookie(domain: str, header: str) -> bool:
        # The expired header gets an outright rejection (a real backend would
        # answer 401/302 for it), not a transient failure.
        check_calls[header] = check_calls.get(header, 0) + 1
        return header == valid_header

    monkeypatch.setattr(metabase, "_detect_blocked_browsers", lambda browser: [])
    monkeypatch.setattr(metabase, "_iter_cookie_candidates", fake_iter_candidates)
    monkeypatch.setattr(metabase, "_probe_cookie", fake_probe_cookie)
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    header = metabase._wait_for_valid_cookie("metabase.example", None, timeout=10.0, interval=0.0)

    assert header == valid_header
    # The expired header is checked once (poll 1), never rechecked on poll 2 once rejected.
    assert check_calls[expired_header] == 1
    assert check_calls[valid_header] == 1


def test_wait_for_valid_cookie_retries_a_transient_probe_failure_and_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = {"metabase.SESSION": "s", "metabase.DEVICE": "d", "ph_int_auth-0": "a0", "ph_int_auth-1": "a1"}
    header = metabase._format_cookie_header(candidate)
    monkeypatch.setattr(metabase, "_detect_blocked_browsers", lambda browser: [])
    monkeypatch.setattr(
        metabase, "_iter_cookie_candidates", lambda domain, browser, seen_warnings=None: iter([candidate])
    )
    # Poll 1: a network blip or a 5xx from the load balancer (None, inconclusive).
    # Poll 2: the same header, now accepted.
    probe_results = iter([None, True])
    probe_calls: list[str] = []

    def fake_probe(domain: str, h: str, timeout: float = 5.0) -> bool | None:
        probe_calls.append(h)
        return next(probe_results)

    monkeypatch.setattr(metabase, "_probe_cookie", fake_probe)
    monkeypatch.setattr(metabase.time, "sleep", lambda _: None)

    result = metabase._wait_for_valid_cookie("metabase.example", None, timeout=10.0, interval=0.0)

    assert result == header
    assert probe_calls == [header, header]


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
