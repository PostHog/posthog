"""Tests for the signals-scout-insight-labels contradiction checker.

The detection logic of the `signals-scout-insight-labels` canonical scout lives
in a pure-stdlib bundled script (`scripts/check_insight_labels.py`) rather than
in the scout body, precisely so it can be pinned by plain unit tests in CI —
the scout body instructs the run to fetch and exec the script, and this suite
guarantees the script behaves the way the body promises.

Covers the shapes the scout's charter calls out — the "pageviews (last 14
days)" title whose date range was edited, an event the series no longer
tracks, a title that went single-vs-multi-series, a removed "by <x>"
breakdown — plus the equal-and-opposite controls that must NOT fire (matching
labels, interval words, HogQL-insight skips, ambiguous absolute dates).
"""

import json
import subprocess
import sys
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "skills" / "signals-scout-insight-labels" / "scripts" / "check_insight_labels.py"
)


def _load_module():
    assert _SCRIPT_PATH.exists(), f"checker script missing at {_SCRIPT_PATH}"
    spec = spec_from_file_location("check_insight_labels", _SCRIPT_PATH)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_module()


def _trends(date_from="-7d", series=("$pageview",), breakdown=None):
    source = {
        "kind": "TrendsQuery",
        "dateRange": {"date_from": date_from, "date_to": None},
        "series": [{"kind": "EventsNode", "event": ev} for ev in series],
    }
    if breakdown is not None:
        source["breakdownFilter"] = {"breakdown": breakdown}
    return {"kind": "InsightVizNode", "source": source}


def _insight(name, query=None, description="", short_id="abc123"):
    return {
        "short_id": short_id,
        "name": name,
        "description": description,
        "query": query if query is not None else _trends(),
    }


def _run(insights):
    return checker.check_insights(insights)


def _assert_single(insight, check, message_part):
    out = _run([insight])
    assert len(out["findings"]) == 1, out
    checks = out["findings"][0]["checks"]
    assert any(c["check"] == check and message_part in c["message"] for c in checks), checks
    return out["findings"][0]


# ---------------------------------------------------------------------------
# The charter's headline case: date range edited, title left behind
# ---------------------------------------------------------------------------


class TestDateRangeMismatch:
    def test_stale_14d_title_against_30d_query_is_flagged_with_swap(self):
        insight = _insight("pageviews (last 14 days)", _trends(date_from="-30d"))
        finding = _assert_single(insight, "date_range_mismatch", 'name says "last 14 days" but the query')
        assert finding["suggested_name"] == "pageviews (last 30 days)"
        assert finding["auto_fixable"] is True

    def test_matching_range_is_clean(self):
        assert _run([_insight("Signups (last 7 days)", _trends(date_from="-7d"))])["findings"] == []

    def test_weeks_and_days_are_equivalent(self):
        assert _run([_insight("Signups (last 2 weeks)", _trends(date_from="-14d"))])["findings"] == []

    def test_hours_match_one_day(self):
        assert _run([_insight("Watch this (last 24 hours)", _trends(date_from="-1d"))])["findings"] == []

    def test_weeks_title_against_days_query_suggests_in_query_units(self):
        finding = _assert_single(_insight("Actives (last 2 weeks)", _trends(date_from="-30d")), "date_range_mismatch", "")
        assert finding["suggested_name"] == "Actives (last 30 days)"

    def test_mismatched_week_unit_round_trips_to_weeks(self):
        finding = _assert_single(_insight("Actives (last week)", _trends(date_from="-2w")), "date_range_mismatch", "")
        assert finding["suggested_name"] == "Actives (last 2 weeks)"

    def test_range_in_description_is_flagged_but_not_auto_fixable(self):
        finding = _assert_single(
            _insight("Signups", _trends(date_from="-30d"), description="bounded to the last 7 days"),
            "date_range_mismatch",
            "description",
        )
        assert finding["suggested_name"] is None
        assert finding["auto_fixable"] is False

    def test_absolute_date_from_is_not_guessed(self):
        assert _run([_insight("pageviews (last 14 days)", _trends(date_from="2024-01-01"))])["findings"] == []

    def test_swap_preserves_surrounding_text(self):
        finding = _assert_single(
            _insight("Weekly review — signups (last 14 days) by country", _trends(date_from="-7d", breakdown="country")),
            "date_range_mismatch",
            "",
        )
        assert finding["suggested_name"] == "Weekly review — signups (last 7 days) by country"

    def test_compound_finding_is_not_auto_fixable(self):
        insight = _insight("pageviews (last 14 days) by region", _trends(date_from="-90d"))  # two stale claims
        out = _run([insight])["findings"][0]
        assert len(out["checks"]) == 2
        assert out["auto_fixable"] is False


# ---------------------------------------------------------------------------
# Event in the title no longer tracked by the series
# ---------------------------------------------------------------------------


class TestEventMismatch:
    def test_title_event_not_in_series(self):
        insight = _insight("Autocapture clicks (last 7 days)", _trends(series=("$pageview",)))
        _assert_single(insight, "event_mismatch", "autocapture")

    def test_series_edited_away_from_pageviews(self):
        insight = _insight("pageviews (last 7 days)", _trends(series=("$autocapture",)))
        _assert_single(insight, "event_mismatch", "pageview")

    def test_matching_event_vocab_is_clean(self):
        assert _run([_insight("Rage clicks today", _trends(series=("$rageclick",)))])["findings"] == []

    def test_any_series_quieting_the_mention(self):
        assert _run([_insight("pageviews and autocapture", _trends(series=("$pageview", "$autocapture")))])[
            "findings"
        ] == []

    def test_custom_events_do_not_resolve(self):
        # No alias-group knowledge on either side: stay silent.
        assert _run([_insight("Invoice created (last 7 days)", _trends(series=("company_created",)))] )[
            "findings"
        ] == []


# ---------------------------------------------------------------------------
# Series count vs the title's promise
# ---------------------------------------------------------------------------


class TestSeriesCountMismatch:
    def test_singular_title_over_two_series(self):
        insight = _insight("Active users (last 7 days)", _trends(series=("$pageview", "$autocapture")))
        _assert_single(insight, "series_count_mismatch", "2 series")

    def test_vs_title_quiets_the_singular_check(self):
        assert _run([_insight("Web vs mobile pageviews", _trends(series=("web", "mobile")))])["findings"] == []

    def test_vs_title_with_fewer_series_than_named(self):
        insight = _insight("Control vs test vs holdout", _trends(series=("control",)))
        _assert_single(insight, "series_count_mismatch", "names 3 things")


# ---------------------------------------------------------------------------
# "by <x>" titles vs the query's breakdown
# ---------------------------------------------------------------------------


class TestBreakdownMismatch:
    def test_by_claim_with_no_breakdown(self):
        insight = _insight("Signups by country", _trends())
        _assert_single(insight, "breakdown_mismatch", "no breakdown")

    def test_by_claim_against_different_breakdown(self):
        insight = _insight("Signups by country", _trends(breakdown="$browser"))
        _assert_single(insight, "breakdown_mismatch", "country")

    def test_matching_breakdown_is_clean(self):
        assert _run([_insight("Signups by country", _trends(breakdown="country"))])["findings"] == []

    def test_dollar_prefixed_property_matches(self):
        assert _run([_insight("Signups by browser", _trends(breakdown="$browser"))])["findings"] == []

    def test_multi_word_property_matches(self):
        assert _run([_insight("Signups by device type", _trends(breakdown="$device_type"))])["findings"] == []

    def test_interval_words_are_not_breakdown_claims(self):
        assert _run([_insight("Pageviews by day", _trends())])["findings"] == []


# ---------------------------------------------------------------------------
# Pipeline robustness: shapes the SQL sends at the script
# ---------------------------------------------------------------------------


class TestShapes:
    def test_query_as_json_string(self):
        insight = _insight("pageviews (last 14 days)")
        insight["query"] = json.dumps(insight["query"])
        out = _run([insight])
        assert out["checked"] == 1 and len(out["findings"]) == 1

    def test_legacy_filters_shape(self):
        insight = {
            "short_id": "leg1",
            "name": "pageviews (last 30 days)",
            "description": "",
            "query": None,
            "filters": {"insight": "TRENDS", "events": [{"id": "$pageview"}], "date_from": "-14d"},
        }
        _assert_single(insight, "date_range_mismatch", '"-14d"')

    def test_hogql_insights_are_skipped_not_fabricated(self):
        insight = {
            "short_id": "sql1",
            "name": "pageviews (last 14 days)",
            "description": "",
            "query": {
                "kind": "DataVisualizationNode",
                "source": {"kind": "HogQLQuery", "query": "select * from events where timestamp > now() - interval 30 day"},
            },
        }
        out = _run([insight])
        assert out["findings"] == []
        assert out["skipped"] == [{"short_id": "sql1", "reason": "hogql-skipped"}]

    def test_bare_list_input(self):
        assert _run([_insight("fine (last 7 days)")])["checked"] == 1

    def test_empty_name_still_checks_description(self):
        insight = _insight("", _trends(date_from="-30d"), description="last 7 days of signups")
        _assert_single(insight, "date_range_mismatch", "description")


# ---------------------------------------------------------------------------
# The CLI contract is what the scout actually shells out
# ---------------------------------------------------------------------------


class TestCli:
    @pytest.mark.parametrize(
        "payload",
        [
            {"insights": [_insight("pageviews (last 14 days)", _trends(date_from="-30d"))]},
            [_insight("fine (last 7 days)")],
        ],
    )
    def test_stdin_json_round_trip(self, payload):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert {"checked", "skipped", "findings"} <= set(out)
        expected = bool("last 14 days" in json.dumps(payload))
        assert len(out["findings"]) == (1 if expected else 0)

    def test_malformed_payload_exits_2(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH)],
            input='{"not_insights": true}',
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 2
        assert "error" in json.loads(proc.stdout)
