from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.growth.backend.sdk_health import (
    MINOR_AGE_THRESHOLD_DAYS,
    MINOR_VERSIONS_BEHIND_THRESHOLD,
    SINGLE_VERSION_GRACE_PERIOD_DAYS,
    OutdatedTrafficAlert,
    UsageEntry,
    _build_activity_page_url,
    _build_banner,
    _build_sql_query,
    _build_status_reason,
    assess_release,
    assess_sdk,
    compute_sdk_health,
    diff_versions,
    parse_version,
)

NOW = datetime(2026, 4, 21, tzinfo=UTC)


def _days_ago(days: int) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def _entry(version: str, count: int, days_ago: int | None = None, is_latest: bool = False) -> UsageEntry:
    return UsageEntry(
        lib_version=version,
        count=count,
        max_timestamp=NOW.isoformat(),
        release_date=_days_ago(days_ago) if days_ago is not None else None,
        is_latest=is_latest,
    )


class TestParseVersion(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain", "1.2.3", 1, 2, 3, None),
            ("leading_v", "v1.2.3", 1, 2, 3, None),
            ("major_only", "2", 2, None, None, None),
            ("major_minor", "3.4", 3, 4, None, None),
            ("with_extra", "1.2.3-beta", 1, 2, 3, "beta"),
            # Match TS `split('-', 2)` which discards everything after the 2nd segment:
            # "1.2.3-beta-2" → extra="beta", not "beta-2".
            ("with_extra_multi_dash", "1.2.3-beta-2", 1, 2, 3, "beta"),
            ("with_extra_rc_build", "1.2.3-rc.1-build.5", 1, 2, 3, "rc.1"),
        ]
    )
    def test_parses(self, _name, raw, major, minor, patch, extra):
        v = parse_version(raw)
        assert v.major == major
        assert v.minor == minor
        assert v.patch == patch
        assert v.extra == extra

    @parameterized.expand([("empty", ""), ("not_numeric", "abc"), ("too_many_parts", "1.2.3.4")])
    def test_invalid_raises(self, _name, raw):
        with self.assertRaises(ValueError):
            parse_version(raw)


class TestDiffVersions(SimpleTestCase):
    def test_equal(self):
        assert diff_versions(parse_version("1.2.3"), parse_version("1.2.3")) is None

    def test_major_diff(self):
        d = diff_versions(parse_version("2.0.0"), parse_version("1.0.0"))
        assert d is not None
        assert d.kind == "major"
        assert d.diff == 1

    def test_minor_diff(self):
        d = diff_versions(parse_version("1.5.0"), parse_version("1.2.0"))
        assert d is not None
        assert d.kind == "minor"
        assert d.diff == 3

    def test_patch_diff(self):
        d = diff_versions(parse_version("1.2.7"), parse_version("1.2.3"))
        assert d is not None
        assert d.kind == "patch"
        assert d.diff == 4

    def test_older_is_negative(self):
        d = diff_versions(parse_version("1.0.0"), parse_version("2.0.0"))
        assert d is not None
        assert d.kind == "major"
        assert d.diff == -1


class TestAssessReleaseGracePeriod(SimpleTestCase):
    def test_fresh_web_release_not_outdated_even_if_behind(self):
        # Within 14-day web grace period — should NOT be flagged
        entry = _entry("1.0.0", 100, days_ago=5)
        result = assess_release(
            "web",
            entry,
            latest=parse_version("5.0.0"),
            is_single_version=False,
            now=NOW,
        )
        assert result.is_outdated is False
        assert result.is_old is False

    def test_fresh_node_release_not_outdated(self):
        # Within 7-day non-web grace period
        entry = _entry("1.0.0", 100, days_ago=3)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("5.0.0"),
            is_single_version=False,
            now=NOW,
        )
        assert result.is_outdated is False

    def test_web_outside_grace_period_major_behind(self):
        # 20 days old, major behind — flagged
        entry = _entry("1.0.0", 100, days_ago=20)
        result = assess_release(
            "web",
            entry,
            latest=parse_version("2.0.0"),
            is_single_version=False,
            now=NOW,
        )
        assert result.is_outdated is True


class TestAssessReleaseSingleVersion(SimpleTestCase):
    def test_single_version_young_not_outdated(self):
        entry = _entry("1.230.1", 500, days_ago=5)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("1.234.0"),
            is_single_version=True,
            now=NOW,
        )
        assert result.is_outdated is False

    def test_single_version_old_is_outdated(self):
        entry = _entry("1.230.1", 500, days_ago=SINGLE_VERSION_GRACE_PERIOD_DAYS + 10)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("1.234.0"),
            is_single_version=True,
            now=NOW,
        )
        assert result.is_outdated is True

    def test_single_version_no_release_date_falls_through_to_count_check(self):
        # Regression: single-version with undefined daysSinceRelease previously bypassed count check
        entry = _entry("1.234.1", 500, days_ago=None)  # No release_date
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("1.364.1"),  # 130 minors ahead
            is_single_version=True,
            now=NOW,
        )
        # Falls through to multi-version-style count check: 130 minors behind >= 3, so outdated
        assert result.is_outdated is True


class TestAssessReleaseMinorRules(SimpleTestCase):
    def test_one_minor_behind_recent_not_outdated(self):
        entry = _entry("1.4.0", 100, days_ago=30)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("1.5.0"),
            is_single_version=False,
            now=NOW,
        )
        assert result.is_outdated is False

    def test_threshold_minors_behind_is_outdated(self):
        entry = _entry("1.2.0", 100, days_ago=30)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version(f"1.{2 + MINOR_VERSIONS_BEHIND_THRESHOLD}.0"),
            is_single_version=False,
            now=NOW,
        )
        assert result.is_outdated is True

    def test_minor_behind_but_old_is_outdated(self):
        entry = _entry("1.4.0", 100, days_ago=MINOR_AGE_THRESHOLD_DAYS + 10)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("1.5.0"),
            is_single_version=False,
            now=NOW,
        )
        assert result.is_outdated is True


class TestAssessReleasePatchRules(SimpleTestCase):
    def test_patch_behind_is_never_outdated(self):
        entry = _entry("1.2.0", 100, days_ago=400)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("1.2.20"),
            is_single_version=False,
            now=NOW,
        )
        assert result.is_outdated is False


class TestAssessReleaseMajorRules(SimpleTestCase):
    def test_major_behind_is_outdated(self):
        entry = _entry("1.0.0", 100, days_ago=30)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("2.0.0"),
            is_single_version=False,
            now=NOW,
        )
        assert result.is_outdated is True


class TestAssessReleaseCurrentOrNewer(SimpleTestCase):
    def test_current_version_not_outdated(self):
        entry = _entry("1.5.0", 100, is_latest=True)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("1.5.0"),
            is_single_version=True,
            now=NOW,
        )
        assert result.is_outdated is False
        assert result.is_current_or_newer is True

    def test_ahead_of_cached_latest_not_outdated(self):
        entry = _entry("1.6.0", 100)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("1.5.0"),
            is_single_version=True,
            now=NOW,
        )
        assert result.is_outdated is False
        assert result.is_current_or_newer is True


class TestAssessReleaseIsOld(SimpleTestCase):
    def test_desktop_old_flagged(self):
        # 17 weeks > 16-week desktop threshold, with 1 minor behind
        entry = _entry("1.2.0", 100, days_ago=17 * 7 + 1)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("1.3.0"),
            is_single_version=False,
            now=NOW,
        )
        assert result.is_old is True
        assert result.needs_updating is True

    def test_mobile_old_threshold_higher(self):
        # 20 weeks — above desktop threshold (16), below mobile threshold (24)
        entry = _entry("1.2.0", 100, days_ago=20 * 7)
        result = assess_release(
            "posthog-ios",
            entry,
            latest=parse_version("1.3.0"),
            is_single_version=False,
            now=NOW,
        )
        assert result.is_old is False

    def test_current_version_never_old(self):
        # Even an ancient current version shouldn't be flagged as "old"
        entry = _entry("1.5.0", 100, days_ago=1000, is_latest=True)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("1.5.0"),
            is_single_version=True,
            now=NOW,
        )
        assert result.is_old is False


class TestAssessSdkTrafficAlerts(SimpleTestCase):
    def test_web_outdated_with_significant_traffic_triggers_alert(self):
        entries = [
            _entry("2.0.0", 30, days_ago=5, is_latest=True),
            _entry("1.0.0", 70, days_ago=200),  # 70% traffic, major behind, old
        ]
        result = assess_sdk("web", "2.0.0", entries, now=NOW)
        assert result is not None
        assert len(result.outdated_traffic_alerts) == 1
        assert result.outdated_traffic_alerts[0].version == "1.0.0"
        assert result.is_outdated is True

    def test_web_low_traffic_outdated_version_below_threshold(self):
        # Old version with only 15% traffic — below 20% web threshold
        entries = [
            _entry("2.0.0", 85, days_ago=5, is_latest=True),
            _entry("1.0.0", 15, days_ago=200),
        ]
        result = assess_sdk("web", "2.0.0", entries, now=NOW)
        assert result is not None
        assert result.outdated_traffic_alerts == []
        # Primary (first) is fresh, so SDK not marked outdated
        assert result.is_outdated is False

    def test_mobile_never_gets_traffic_alerts(self):
        # Even at high traffic, mobile SDKs shouldn't trigger traffic alerts (users don't auto-update)
        entries = [
            _entry("2.0.0", 10, days_ago=5, is_latest=True),
            _entry("1.0.0", 90, days_ago=200),
        ]
        result = assess_sdk("posthog-ios", "2.0.0", entries, now=NOW)
        assert result is not None
        assert result.outdated_traffic_alerts == []


class TestComputeSdkHealth(SimpleTestCase):
    def test_healthy_when_all_current(self):
        data = {
            "web": {
                "latest_version": "1.5.0",
                "usage": [{"lib_version": "1.5.0", "count": 100, "max_timestamp": NOW.isoformat(), "is_latest": True}],
            }
        }
        report = compute_sdk_health(data, now=NOW)
        assert report.overall_health == "healthy"
        assert report.health == "success"
        assert report.needs_updating_count == 0
        assert report.team_sdk_count == 1

    def test_warning_when_one_of_many_outdated(self):
        # 1 of 3 outdated — below half, so warning not danger
        data = {
            "web": {
                "latest_version": "2.0.0",
                "usage": [
                    {
                        "lib_version": "2.0.0",
                        "count": 100,
                        "max_timestamp": NOW.isoformat(),
                        "is_latest": True,
                    }
                ],
            },
            "posthog-node": {
                "latest_version": "1.5.0",
                "usage": [
                    {
                        "lib_version": "1.5.0",
                        "count": 100,
                        "max_timestamp": NOW.isoformat(),
                        "is_latest": True,
                    }
                ],
            },
            "posthog-python": {
                "latest_version": "5.0.0",
                "usage": [
                    {
                        "lib_version": "1.0.0",
                        "count": 100,
                        "max_timestamp": NOW.isoformat(),
                        "is_latest": False,
                        "release_date": _days_ago(200),
                    }
                ],
            },
        }
        report = compute_sdk_health(data, now=NOW)
        assert report.needs_updating_count == 1
        assert report.team_sdk_count == 3
        assert report.health == "warning"
        assert report.overall_health == "needs_attention"

    def test_danger_when_half_or_more_outdated(self):
        # 2 of 3 outdated — triggers danger
        data = {
            "web": {
                "latest_version": "2.0.0",
                "usage": [
                    {
                        "lib_version": "1.0.0",
                        "count": 100,
                        "max_timestamp": NOW.isoformat(),
                        "is_latest": False,
                        "release_date": _days_ago(200),
                    }
                ],
            },
            "posthog-node": {
                "latest_version": "1.5.0",
                "usage": [
                    {
                        "lib_version": "1.5.0",
                        "count": 100,
                        "max_timestamp": NOW.isoformat(),
                        "is_latest": True,
                    }
                ],
            },
            "posthog-python": {
                "latest_version": "5.0.0",
                "usage": [
                    {
                        "lib_version": "1.0.0",
                        "count": 100,
                        "max_timestamp": NOW.isoformat(),
                        "is_latest": False,
                        "release_date": _days_ago(200),
                    }
                ],
            },
        }
        report = compute_sdk_health(data, now=NOW)
        assert report.needs_updating_count == 2
        assert report.team_sdk_count == 3
        assert report.health == "danger"
        assert report.overall_health == "needs_attention"
        # When needs_attention fires, outdated SDK severity escalates to danger
        danger_count = sum(1 for s in report.sdks if s.severity == "danger")
        assert danger_count == 2

    def test_empty_data_is_healthy(self):
        report = compute_sdk_health({}, now=NOW)
        assert report.team_sdk_count == 0
        assert report.needs_updating_count == 0
        assert report.overall_health == "healthy"
        assert report.health == "success"

    def test_skips_entries_with_no_usage(self):
        data = {
            "web": {"latest_version": "1.0.0", "usage": []},
        }
        report = compute_sdk_health(data, now=NOW)
        assert report.team_sdk_count == 0


class TestUiParityStrings(SimpleTestCase):
    @parameterized.expand(
        [
            ("outdated_with_age", True, False, "5 months ago", "Released 5 months ago. Upgrade recommended."),
            ("outdated_no_age", True, False, None, "Upgrade recommended"),
            (
                "current",
                False,
                True,
                "a day ago",
                "You have the latest available. Click 'Releases ↗' above to check for any since.",
            ),
            (
                "recent_with_age",
                False,
                False,
                "2 months ago",
                "Released 2 months ago. Upgrading is a good idea, but it's not urgent yet.",
            ),
            ("recent_no_age", False, False, None, "Upgrading is a good idea, but it's not urgent yet"),
        ]
    )
    def test_status_reason(self, _name, is_outdated, is_current_or_newer, released_ago, expected):
        assert _build_status_reason(is_outdated, is_current_or_newer, released_ago) == expected

    def test_sql_query_matches_ui_template(self):
        sql = _build_sql_query("posthog-node", "1.230.1")
        assert "SELECT * FROM events" in sql
        assert "INTERVAL 7 DAY" in sql
        assert "properties.$lib = 'posthog-node'" in sql
        assert "properties.$lib_version = '1.230.1'" in sql
        assert "LIMIT 50" in sql

    def test_activity_page_url_contains_project_prefix_and_version(self):
        url = _build_activity_page_url(2, "web", "1.298.0")
        # kea-router reads DataTableNode state from the hash, not the query string
        assert url.startswith("/project/2/activity/explore#q=")
        # URL-encoded JSON payload should contain our lib/version filters
        assert "%22web%22" in url  # "web" encoded
        assert "1.298.0" in url
        assert "DataTableNode" in url
        # Spaces must be %20, not '+': the hash parser does not treat '+' as space,
        # so "person_display_name -- Person" would otherwise be parsed as a literal
        # column name and silently dropped.
        assert "+" not in url.split("#", 1)[1]
        assert "person_display_name%20--%20Person" in url

    def test_activity_page_url_without_project(self):
        url = _build_activity_page_url(None, "web", "1.0.0")
        assert url.startswith("/activity/explore#q=")

    def test_banner_matches_ui_copy(self):
        banner = _build_banner("posthog-python", OutdatedTrafficAlert(version="7.0.0", threshold_percent=10.0))
        assert banner == "Version 7.0.0 of the Python SDK has captured more than 10% of events in the last 7 days."

    @parameterized.expand(
        [
            ("sql_quote_escape", "posthog-node", "1.0.0'; DROP TABLE events;--"),
            ("sql_union", "posthog-node", "1.0.0' UNION SELECT password FROM users--"),
            ("sql_line_break", "posthog-node", "1.0.0\n; DROP TABLE"),
            ("sql_trailing_space", "posthog-node", "1.0.0 OR 1=1"),
            ("sql_semicolon", "posthog-node", "1.0.0;SELECT"),
            ("lib_type_quote", "posthog-node'; --", "1.0.0"),
            ("lib_type_space", "posthog node", "1.0.0"),
            ("unicode_fullwidth", "posthog-node", "１.０.０"),
            ("empty_version", "posthog-node", ""),
            ("empty_sdk_type", "", "1.0.0"),
        ]
    )
    def test_sql_query_rejects_unsafe_values(self, _name, sdk_type, version):
        # Any character outside ^[A-Za-z0-9._+\-]+$ must produce an empty SQL, which the
        # skill tells agents to surface rather than retry or patch in their own values.
        assert _build_sql_query(sdk_type, version) == ""

    @parameterized.expand(
        [
            ("sql_quote_escape", "posthog-node", "1.0.0'; DROP TABLE events;--"),
            ("lib_type_quote", "posthog-node'; --", "1.0.0"),
            ("empty_version", "posthog-node", ""),
        ]
    )
    def test_activity_page_url_rejects_unsafe_values(self, _name, sdk_type, version):
        # Matches sql_query behavior so agents see a uniform "it's empty, surface it" signal.
        assert _build_activity_page_url(2, sdk_type, version) == ""

    def test_sql_query_accepts_prerelease_suffix(self):
        # Versions like "1.2.3-beta" are valid semver — must pass the allowlist.
        sql = _build_sql_query("posthog-node", "1.2.3-beta")
        assert "'1.2.3-beta'" in sql

    def test_sql_query_accepts_build_metadata(self):
        # "1.2.3+build.1" is valid semver with build metadata — allowlist includes '+'.
        sql = _build_sql_query("posthog-node", "1.2.3+build.1")
        assert "'1.2.3+build.1'" in sql


class TestAssessReleaseParseFailureFallback(SimpleTestCase):
    """Parser failure and injection-safety are orthogonal concerns — document both paths."""

    def test_unparseable_safe_version_still_gets_sql_and_url(self):
        # "not-a-version" passes the safety allowlist but fails the semver parser.
        # The sanitizer is the security boundary — not the parser — so SQL is still built.
        # This is correct: an agent can still drill into events for an oddly-named version.
        entry = _entry("not-a-version", 100, days_ago=365)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("2.0.0"),
            is_single_version=False,
            now=NOW,
            project_id=7,
        )
        assert result.is_outdated is False
        assert result.is_old is False
        assert result.needs_updating is False
        assert "not-a-version" in result.sql_query
        assert "not-a-version" in result.activity_page_url
        assert "Unable to parse" in result.status_reason

    def test_unparseable_unsafe_version_emits_empty_sql_and_url(self):
        # The specific case the reviewer flagged: parse fails AND the string has injection chars.
        # Sanitizer must return empty strings so agents don't execute crafted SQL.
        entry = _entry("1.0.0'; DROP TABLE events;--", 100, days_ago=365)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("2.0.0"),
            is_single_version=False,
            now=NOW,
            project_id=7,
        )
        assert result.is_outdated is False
        assert result.sql_query == ""
        assert result.activity_page_url == ""

    def test_too_many_parts_triggers_parse_fallback(self):
        # "1.2.3.4" passes the allowlist but fails the semver regex — fallback kicks in.
        entry = _entry("1.2.3.4", 100, days_ago=10)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("2.0.0"),
            is_single_version=False,
            now=NOW,
            project_id=7,
        )
        assert result.is_outdated is False
        assert "1.2.3.4" in result.sql_query  # Safe to interpolate


class TestMobileGracePeriod(SimpleTestCase):
    """Grace period (7d non-web) must apply to mobile SDKs too."""

    @parameterized.expand(
        [
            ("ios", "posthog-ios"),
            ("android", "posthog-android"),
            ("flutter", "posthog-flutter"),
            ("react_native", "posthog-react-native"),
        ]
    )
    def test_fresh_mobile_release_not_outdated_even_if_major_behind(self, _name, sdk_type):
        entry = _entry("1.0.0", 100, days_ago=3)  # Within 7-day non-web grace period
        result = assess_release(
            sdk_type,
            entry,
            latest=parse_version("5.0.0"),  # Multiple majors ahead
            is_single_version=False,
            now=NOW,
        )
        assert result.is_outdated is False
        assert result.is_old is False

    def test_banner_uses_readable_name_for_web(self):
        banner = _build_banner("web", OutdatedTrafficAlert(version="1.298.0", threshold_percent=20.0))
        assert "Web SDK" in banner
        assert "20%" in banner


class TestAssessReleasePopulatesUiFields(SimpleTestCase):
    def test_outdated_release_has_tooltip_sql_and_url(self):
        entry = _entry("1.0.0", 100, days_ago=200)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("2.0.0"),
            is_single_version=False,
            now=NOW,
            project_id=7,
        )
        assert result.released_ago is not None
        assert "Upgrade recommended" in result.status_reason
        assert "posthog-node" in result.sql_query
        assert result.activity_page_url.startswith("/project/7/activity/explore#q=")

    def test_current_release_has_you_have_latest_tooltip(self):
        entry = _entry("1.5.0", 100, days_ago=5, is_latest=True)
        result = assess_release(
            "posthog-node",
            entry,
            latest=parse_version("1.5.0"),
            is_single_version=True,
            now=NOW,
            project_id=7,
        )
        assert "You have the latest available" in result.status_reason


class TestAssessSdkBanners(SimpleTestCase):
    def test_banners_one_per_traffic_alert(self):
        entries = [
            _entry("2.0.0", 30, days_ago=5, is_latest=True),
            _entry("1.0.0", 70, days_ago=200),
        ]
        result = assess_sdk("web", "2.0.0", entries, now=NOW, project_id=2)
        assert result is not None
        assert len(result.banners) == 1
        assert (
            result.banners[0] == "Version 1.0.0 of the Web SDK has captured more than 20% of events in the last 7 days."
        )

    def test_no_banners_when_no_traffic_alerts(self):
        entries = [_entry("1.5.0", 100, days_ago=5, is_latest=True)]
        result = assess_sdk("posthog-node", "1.5.0", entries, now=NOW)
        assert result is not None
        assert result.banners == []

    def test_readable_name_populated(self):
        entries = [_entry("1.5.0", 100, days_ago=5, is_latest=True)]
        result = assess_sdk("posthog-node", "1.5.0", entries, now=NOW)
        assert result is not None
        assert result.readable_name == "Node.js"
