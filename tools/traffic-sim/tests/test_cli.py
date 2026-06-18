"""Unit tests for traffic-sim cli helpers — no network, no Playwright."""

import json
from urllib.parse import parse_qs, urlparse

import pytest

import cli


class TestExtractPosthogEventsFromConsole:
    @pytest.mark.parametrize(
        "lines,expected",
        [
            ([], []),
            (
                [cli.ConsoleLine(timestamp="t", type="log", text='[PostHog.js] send "$pageview"', is_posthog=True)],
                ["$pageview"],
            ),
            (
                [
                    cli.ConsoleLine(timestamp="t", type="log", text='[PostHog.js] send "$pageview"', is_posthog=True),
                    cli.ConsoleLine(
                        timestamp="t", type="log", text='[PostHog.js] send "$autocapture"', is_posthog=True
                    ),
                ],
                ["$pageview", "$autocapture"],
            ),
            (
                # Custom event names without $ prefix.
                [
                    cli.ConsoleLine(
                        timestamp="t", type="log", text='[PostHog.js] send "signup_completed"', is_posthog=True
                    )
                ],
                ["signup_completed"],
            ),
            (
                # Non-posthog console lines are ignored even if they look similar.
                [cli.ConsoleLine(timestamp="t", type="log", text='[PostHog.js] send "$pageview"', is_posthog=False)],
                [],
            ),
        ],
    )
    def test_extracts_event_names(self, lines, expected):
        assert cli.extract_posthog_events_from_console(lines) == expected


class TestAddTrackingParams:
    def test_adds_required_params(self):
        url = cli.add_tracking_params("https://example.com/foo", "abc123", "new-user")
        params = parse_qs(urlparse(url).query)
        assert params["__posthog_debug"] == ["true"]
        assert params["run_id"] == ["abc123"]
        assert params["scenario"] == ["new-user"]

    def test_preserves_existing_query_params(self):
        url = cli.add_tracking_params("https://example.com/foo?utm_source=x", "id", "scen")
        params = parse_qs(urlparse(url).query)
        assert params["utm_source"] == ["x"]
        assert params["__posthog_debug"] == ["true"]


class TestResolvePosthogDomains:
    def test_empty_host_returns_defaults(self):
        assert cli.resolve_posthog_domains("") == cli.DEFAULT_POSTHOG_DOMAINS

    def test_default_host_does_not_add_extras(self):
        # us.i.posthog.com is a subdomain of i.posthog.com, so no extra needed.
        domains = cli.resolve_posthog_domains("https://us.i.posthog.com")
        assert domains == cli.DEFAULT_POSTHOG_DOMAINS

    def test_custom_host_adds_netloc(self):
        domains = cli.resolve_posthog_domains("https://ph.example.com")
        assert domains == (*cli.DEFAULT_POSTHOG_DOMAINS, "ph.example.com")

    def test_eu_cloud_does_not_add_extras(self):
        domains = cli.resolve_posthog_domains("https://eu.i.posthog.com")
        assert domains == cli.DEFAULT_POSTHOG_DOMAINS


class TestLoadUrlsFile:
    def test_flat_list(self, tmp_path):
        path = tmp_path / "urls.json"
        path.write_text(json.dumps(["https://example.com/", "https://example.com/about"]))
        assert cli._load_urls_file(str(path)) == ["https://example.com/", "https://example.com/about"]

    def test_grouped_form(self, tmp_path):
        path = tmp_path / "urls.json"
        path.write_text(
            json.dumps(
                {
                    "base_url": "https://example.com",
                    "categories": {"main": ["/", "/about"], "marketing": ["/pricing"]},
                    "extra_urls": ["https://example.com/blog/post-1"],
                }
            )
        )
        urls = cli._load_urls_file(str(path))
        assert sorted(urls) == sorted(
            [
                "https://example.com/",
                "https://example.com/about",
                "https://example.com/pricing",
                "https://example.com/blog/post-1",
            ]
        )

    def test_grouped_form_strips_trailing_slash_from_base(self, tmp_path):
        path = tmp_path / "urls.json"
        path.write_text(
            json.dumps(
                {
                    "base_url": "https://example.com/",
                    "categories": {"main": ["/about"]},
                }
            )
        )
        urls = cli._load_urls_file(str(path))
        assert urls == ["https://example.com/about"]

    @pytest.mark.parametrize(
        "payload",
        [
            [],
            {"base_url": "https://example.com"},
        ],
    )
    def test_empty_payload_raises(self, tmp_path, payload):
        path = tmp_path / "urls.json"
        path.write_text(json.dumps(payload))
        with pytest.raises(ValueError, match="No URLs found"):
            cli._load_urls_file(str(path))


class TestLoadUrls:
    def test_args_take_precedence(self, tmp_path):
        path = tmp_path / "urls.json"
        path.write_text(json.dumps(["https://from-file.example.com/"]))
        result = cli.load_urls(["https://from-arg.example.com/"], str(path))
        assert result == ["https://from-arg.example.com/"]

    def test_falls_back_to_file(self, tmp_path):
        path = tmp_path / "urls.json"
        path.write_text(json.dumps(["https://from-file.example.com/"]))
        assert cli.load_urls(None, str(path)) == ["https://from-file.example.com/"]

    def test_neither_raises(self):
        with pytest.raises(ValueError, match="--url"):
            cli.load_urls(None, None)


class TestBuildParser:
    @pytest.mark.parametrize("scenario", ["new-user", "returning-user", "check-loading"])
    def test_parses_each_subcommand(self, scenario):
        args = cli.build_parser().parse_args([scenario, "--url", "https://example.com"])
        assert args.scenario == scenario
        assert args.urls == ["https://example.com"]

    def test_repeatable_url_flag(self):
        args = cli.build_parser().parse_args(
            [
                "new-user",
                "--url",
                "https://a.com",
                "--url",
                "https://b.com",
            ]
        )
        assert args.urls == ["https://a.com", "https://b.com"]

    def test_new_user_defaults(self):
        args = cli.build_parser().parse_args(["new-user", "--url", "https://example.com"])
        assert args.visits == 10
        assert args.interval == 60.0
        assert not args.cloud
        assert not args.headed
        assert args.timeout == 120

    def test_returning_user_defaults(self):
        args = cli.build_parser().parse_args(["returning-user", "--url", "https://example.com"])
        assert args.page_views == 5
        assert args.interval == 30.0

    def test_posthog_host_default(self):
        args = cli.build_parser().parse_args(["check-loading", "--url", "https://example.com"])
        assert args.posthog_host == cli.DEFAULT_POSTHOG_HOST

    def test_custom_posthog_host(self):
        args = cli.build_parser().parse_args(
            [
                "check-loading",
                "--url",
                "https://example.com",
                "--posthog-host",
                "https://eu.i.posthog.com",
            ]
        )
        assert args.posthog_host == "https://eu.i.posthog.com"


class TestAnalyticsCapture:
    def test_is_posthog_matches_default_domains(self):
        cap = cli.AnalyticsCapture(posthog_domains=cli.DEFAULT_POSTHOG_DOMAINS)
        assert cap._is_posthog("https://us.i.posthog.com/capture/")
        assert cap._is_posthog("https://app.posthog.com/decide/")
        assert not cap._is_posthog("https://google-analytics.com/collect")
        assert not cap._is_posthog("https://example.com/api")

    def test_is_posthog_matches_custom_domain(self):
        cap = cli.AnalyticsCapture(posthog_domains=("posthog.com", "ph.example.com"))
        assert cap._is_posthog("https://ph.example.com/i/v0/e/")
        assert cap._is_posthog("https://us.i.posthog.com/capture/")
        assert not cap._is_posthog("https://other.example.com/api")

    @pytest.mark.parametrize(
        "url",
        [
            # Hostname containing posthog.com as a path/query component is not a match.
            "https://evil.com/posthog.com/capture",
            "https://evil.com/?proxy=us.i.posthog.com",
            # Hostname that merely ends with posthog.com without a leading dot is not a match.
            "https://notposthog.com/capture",
            # Subdomain attack: posthog.com placed before the registered domain.
            "https://posthog.com.evil.com/capture",
        ],
    )
    def test_is_posthog_rejects_lookalike_urls(self, url):
        cap = cli.AnalyticsCapture(posthog_domains=cli.DEFAULT_POSTHOG_DOMAINS)
        assert not cap._is_posthog(url)


class TestLoadBrowserstackYaml:
    def test_returns_none_when_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cli, "__file__", str(tmp_path / "cli.py"))
        assert cli._load_browserstack_yaml() == (None, None)

    def test_parses_username_and_access_key(self, monkeypatch, tmp_path):
        (tmp_path / "browserstack.yml").write_text("# example header\nuserName: alice\naccessKey: 'secret-123'\n")
        monkeypatch.setattr(cli, "__file__", str(tmp_path / "cli.py"))
        assert cli._load_browserstack_yaml() == ("alice", "secret-123")

    def test_skips_placeholder_blanks(self, monkeypatch, tmp_path):
        (tmp_path / "browserstack.yml").write_text("userName:\naccessKey: \n")
        monkeypatch.setattr(cli, "__file__", str(tmp_path / "cli.py"))
        assert cli._load_browserstack_yaml() == (None, None)
