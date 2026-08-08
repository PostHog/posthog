"""Test suite for the insight-hygiene scout. Two layers:

1. **Scenario corpus**. Named (name, description, query) cases with an expected verdict,
   confusion flag, and mechanical suggestion. The corpus runs through the rule engine in
   `products/signals/backend/scout_harness/insight_hygiene.py`. The scout's
   `references/queries.md` states the same rules. This is the behavioral contract: every
   confusing shape the scout must catch, and every clean shape it must leave alone.
2. **Static skill tests**. The SKILL.md must parse. It must stay report-only (no user-write
   opt-ins) and keep the required anatomy sections. Its bundled `references/queries.md` must
   exist. The body must still state the mechanical rules the corpus asserts. This keeps the
   prompt and the tested rules from drifting apart silently.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.scout_harness.insight_hygiene import (
    Action,
    DateRangeClaim,
    InsightAssessment,
    SeriesInfo,
    Verdict,
    assess_insight,
    check_date_range,
    check_series_count,
    check_series_event,
    event_display_forms,
    extract_date_claim,
    extract_date_from,
    extract_series,
    suggest_renamed_name,
)
from products.signals.backend.scout_harness.lazy_seed import discover_canonical_skills

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
SKILL_DIR = SKILLS_DIR / "signals-scout-insight-hygiene"


def trends_query(events: list[str], date_from: str | None = "-7d") -> dict:
    return {
        "kind": "TrendsQuery",
        "series": [{"kind": "EventsNode", "event": e} for e in events],
        "dateRange": {} if date_from is None else {"date_from": date_from},
    }


def legacy_filters(events: list[str], date_from: str) -> dict:
    return {"events": [{"id": e, "name": e} for e in events], "date_from": date_from}


def wrapped_trends_query(events: list[str], date_from: str | None = "-7d") -> dict:
    # How the API persists every ordinary saved trend-family insight since the auto-wrap:
    # InsightSerializer.validate_query wraps the bare source in an InsightVizNode so the UI
    # renders it. The checks must read through `source`.
    return {"kind": "InsightVizNode", "source": trends_query(events, date_from)}


# ---------------------------------------------------------------------------
# 1. Scenario corpus
# ---------------------------------------------------------------------------

# (case name, insight name, description, query_json, legacy_filters, known_events,
#  expected confusing, expected action, expected suggested name)
SCENARIOS = [
    # --- the headline case: window edited, name left behind → mechanical rename
    (
        "window_edit_rename",
        "Pageviews (last 14 days)",
        None,
        trends_query(["$pageview"], "-30d"),
        None,
        None,
        True,
        Action.REPORT,
        "Pageviews (last 30 days)",
    ),
    (
        "window_edit_rename_90d",
        "Signups (last 7 days)",
        None,
        trends_query(["signed_up"], "-90d"),
        None,
        None,
        True,
        Action.REPORT,
        "Signups (last 90 days)",
    ),
    (
        "window_edit_shorthand",
        "All pageviews, last 7d",
        None,
        trends_query(["$pageview"], "-14d"),
        None,
        None,
        True,
        Action.REPORT,
        "All pageviews, last 14d",
    ),
    # --- window claim matching the query → clean
    (
        "window_match",
        "Pageviews (last 30 days)",
        None,
        trends_query(["$pageview"], "-30d"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    (
        "window_match_shorthand",
        "All pageviews, last 7d",
        None,
        trends_query(["$pageview"], "-7d"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    (
        "this_month_match",
        "Signups this month",
        None,
        trends_query(["signed_up"], "-0mStart"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    (
        "today_match",
        "Pageviews today",
        None,
        trends_query(["$pageview"], "-0dStart"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    (
        "equivalent_window_units",
        "Pageviews (last 14 days)",
        None,
        trends_query(["$pageview"], "-2w"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    # --- window claims contradicting the query with no mechanical substitution → report
    (
        "this_month_now_weekly",
        "Signups this month",
        None,
        trends_query(["signed_up"], "-7d"),
        None,
        None,
        True,
        Action.REPORT,
        None,
    ),
    (
        "today_now_90d",
        "Pageviews today",
        None,
        trends_query(["$pageview"], "-90d"),
        None,
        None,
        True,
        Action.REPORT,
        None,
    ),
    (
        "past_week_now_two",
        "Clicks past week",
        None,
        trends_query(["$autocapture"], "-2w"),
        None,
        None,
        True,
        Action.REPORT,
        None,
    ),
    (
        "claim_on_all_time",
        "Pageviews (last 7 days)",
        None,
        trends_query(["$pageview"], "all"),
        None,
        None,
        True,
        Action.REPORT,
        None,
    ),
    # --- cadence names: satisfied by any window at least as long, confusing only when shorter
    (
        "wau_over_90d",
        "Weekly active users",
        None,
        trends_query(["$pageview"], "-90d"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    (
        "wau_over_7d",
        "Weekly active users",
        None,
        trends_query(["$pageview"], "-7d"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    (
        "wau_over_1d",
        "Weekly active users",
        None,
        trends_query(["$pageview"], "-1d"),
        None,
        None,
        True,
        Action.REPORT,
        None,
    ),
    (
        "dau_over_month",
        "Daily active users",
        None,
        trends_query(["$pageview"], "-30d"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    # --- no claim → never a finding
    ("no_claim", "Key metrics", None, trends_query(["$pageview"], "-30d"), None, None, False, Action.NONE, None),
    ("bare_name", "Pageviews", None, trends_query(["$pageview"], "-14d"), None, None, False, Action.NONE, None),
    (
        "identifier_year",
        "Feature adoption 2024 stats",
        None,
        trends_query(["feature_x"], "-30d"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    (
        "identifier_error_code",
        "404 errors by page",
        None,
        trends_query(["$exception"], "-14d"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    # --- stale event (only with positive evidence the dropped event was tracked)
    (
        "event_swap_stale",
        "Pageviews over time",
        None,
        trends_query(["$autocapture"], "-14d"),
        None,
        {"$pageview"},
        True,
        Action.REPORT,
        None,
    ),
    (
        "event_swap_no_evidence",
        "Pageviews over time",
        None,
        trends_query(["$autocapture"], "-14d"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    (
        "event_alias_phrase",
        "Page views trend",
        None,
        trends_query(["$screen"], "-14d"),
        None,
        {"$pageview"},
        True,
        Action.REPORT,
        None,
    ),
    (
        "event_still_tracked",
        "Pageviews over time",
        None,
        trends_query(["$pageview"], "-14d"),
        None,
        {"$pageview"},
        False,
        Action.NONE,
        None,
    ),
    (
        "custom_event_humanized",
        "Signed up users",
        None,
        trends_query(["signed_up"], "-30d"),
        None,
        {"signed_up"},
        False,
        Action.NONE,
        None,
    ),
    # --- broken comparison
    (
        "vs_one_series",
        "Signups vs logins",
        None,
        trends_query(["signed_up"], "-30d"),
        None,
        None,
        True,
        Action.REPORT,
        None,
    ),
    (
        "vs_two_series",
        "Signups vs logins",
        None,
        trends_query(["signed_up", "logged_in"], "-30d"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    # --- legacy filters format
    (
        "legacy_window_stale",
        "Pageviews (last 14 days)",
        None,
        None,
        legacy_filters(["$pageview"], "-30d"),
        None,
        True,
        Action.REPORT,
        "Pageviews (last 30 days)",
    ),
    (
        "legacy_window_match",
        "Pageviews (last 14 days)",
        None,
        None,
        legacy_filters(["$pageview"], "-14d"),
        None,
        False,
        Action.NONE,
        None,
    ),
    # --- description carrying the only claim → report-only (descriptions are prose, never edited)
    (
        "stale_description_only",
        "Pageviews",
        "Signups over the last 14 days",
        trends_query(["$pageview"], "-30d"),
        None,
        None,
        True,
        Action.REPORT,
        None,
    ),
    # --- InsightVizNode wrapper: how the API persists every ordinary saved trend-family
    # insight. The checks must read through `source`, or wrapped insights look windowless and
    # seriesless (stale windows missed, valid A-vs-B insights falsely reported as zero-series).
    (
        "wrapped_window_edit_rename",
        "Pageviews (last 14 days)",
        None,
        wrapped_trends_query(["$pageview"], "-30d"),
        None,
        None,
        True,
        Action.REPORT,
        "Pageviews (last 30 days)",
    ),
    (
        "wrapped_window_match",
        "Pageviews (last 30 days)",
        None,
        wrapped_trends_query(["$pageview"], "-30d"),
        None,
        None,
        False,
        Action.NONE,
        None,
    ),
    (
        "wrapped_vs_two_series",
        "Signups vs logins",
        None,
        wrapped_trends_query(["signed_up", "logged_in"], "-30d"),
        None,
        {"signed_up", "logged_in"},
        False,
        Action.NONE,
        None,
    ),
    (
        "wrapped_vs_one_series",
        "Signups vs logins",
        None,
        wrapped_trends_query(["signed_up"], "-30d"),
        None,
        {"signed_up"},
        True,
        Action.REPORT,
        None,
    ),
]


class TestScenarioCorpus(SimpleTestCase):
    @parameterized.expand([(s[0],) for s in SCENARIOS])
    def test_scenario(self, case_name: str) -> None:
        row = next(s for s in SCENARIOS if s[0] == case_name)
        (
            _,
            name,
            description,
            query_json,
            legacy,
            known_events,
            expected_confusing,
            expected_action,
            expected_suggested,
        ) = row
        assessment = assess_insight(
            name=name,
            description=description,
            query_json=query_json,
            legacy_filters=legacy,
            known_events=known_events,
        )
        assert isinstance(assessment, InsightAssessment)
        assert assessment.confusing == expected_confusing, (
            f"{case_name}: verdicts={assessment.verdicts} reason={assessment.reason!r}"
        )
        assert assessment.action == expected_action, (
            f"{case_name}: action={assessment.action} reason={assessment.reason!r}"
        )
        if expected_suggested is not None:
            assert assessment.suggested_name is not None, f"{case_name}: expected a mechanical suggestion"
        if expected_suggested is not None:
            assert assessment.suggested_name == expected_suggested, f"{case_name}: {assessment.suggested_name!r}"

    def test_corpus_has_no_duplicate_case_names(self) -> None:
        names = [s[0] for s in SCENARIOS]
        assert len(names) == len(set(names))

    def test_suggested_titles_change_only_the_day_count(self) -> None:
        """Every suggested replacement title must differ from the original title by the digit
        run only. A suggestion that restructures the title is taste, not mechanics."""
        for _, name, _desc, query, legacy, known, _conf, _action, suggested in SCENARIOS:
            if suggested is None:
                continue
            a = assess_insight(name=name, description=None, query_json=query, legacy_filters=legacy, known_events=known)
            assert a.suggested_name == suggested
            assert suggested != name
            assert re.sub(r"\d+", "N", suggested) == re.sub(r"\d+", "N", name), (
                f"rename for {name!r} changed more than the day count: {suggested!r}"
            )


class TestRuleEngineUnits(SimpleTestCase):
    """Focused unit tests for the individual rules the corpus exercises end-to-end."""

    @parameterized.expand(
        [
            ("Signups (last 14 days)", "-14d", 14, "window"),
            ("Signups (past 7 days)", "-7d", 7, "window"),
            ("Signups (last fourteen days)", "-14d", 14, "window"),
            ("Signups, 30d", "-30d", 30, "window"),
            ("Signups, 14 d", "-14d", 14, "window"),
            ("Signups last week", "-1w", None, "window"),
            ("Signups past fortnight", "-2w", None, "window"),
            ("Signups this month", "-0mStart", None, "window"),
            ("Signups today", "-0dStart", None, "window"),
            ("Weekly active users", "-7d", 7, "cadence"),
        ]
    )
    def test_date_claim_extraction(
        self, text: str, expected_canonical: str, expected_days: int | None, kind: str
    ) -> None:
        claim = extract_date_claim(text)
        assert claim is not None, f"no claim found in {text!r}"
        assert claim.canonical() == expected_canonical
        assert claim.days == expected_days
        assert claim.kind == kind

    @parameterized.expand(["2024", "404", "725", "90210"])
    def test_identifiers_never_claim_a_window(self, token: str) -> None:
        assert extract_date_claim(f"Adoption {token} stats") is None

    def test_stale_date_range_on_description(self) -> None:
        assert check_date_range("Pageviews", "Signups over the last 14 days", "-30d") == Verdict.STALE_DATE_RANGE
        assert check_date_range("Pageviews", "Signups over the last 30 days", "-30d") is None

    def test_equivalent_windows_are_not_stale(self) -> None:
        # "-2w" and "last 14 days" are the same window phrased differently
        assert check_date_range("Pageviews (last 14 days)", None, "-2w") is None
        assert check_date_range("Pageviews (last week)", None, "-7d") is None
        assert check_date_range("Pageviews (last week)", None, "-14d") == Verdict.STALE_DATE_RANGE
        # Deliberate approximation: "-1m" reads as 30 days symbolically, not calendar-aware.
        # A calendar-aware comparison would flip verdicts month to month (see parse_relative_days).
        assert check_date_range("Pageviews (last month)", None, "-30d") is None

    def test_event_display_forms_cover_common_events(self) -> None:
        assert "pageviews" in event_display_forms("$pageview")
        assert "errors" in event_display_forms("$exception")
        assert "signed up" in event_display_forms("signed_up")

    def test_stale_event_requires_positive_evidence(self) -> None:
        series = [SeriesInfo(kind="events", name="$autocapture")]
        assert (
            check_series_event("Pageviews over time", None, series, known_events={"$pageview"}) == Verdict.STALE_EVENT
        )
        assert check_series_event("Pageviews over time", None, series, known_events=None) is None
        assert (
            check_series_event(
                "Pageviews over time", None, [SeriesInfo(kind="events", name="$pageview")], known_events={"$pageview"}
            )
            is None
        )

    def test_vs_implies_two_series(self) -> None:
        assert check_series_count("A vs B", [SeriesInfo(kind="events", name="a")]) == Verdict.SERIES_COUNT_MISMATCH
        assert (
            check_series_count("A vs B", [SeriesInfo(kind="events", name="a"), SeriesInfo(kind="events", name="b")])
            is None
        )
        assert check_series_count("A", [SeriesInfo(kind="events", name="a")]) is None

    def test_extract_series_and_date_from_new_and_legacy(self) -> None:
        q = trends_query(["$pageview"], "-14d")
        assert extract_date_from(q, None) == "-14d"
        assert [s.name for s in extract_series(q, None)] == ["$pageview"]
        legacy = {"events": [{"name": "$pageview"}], "actions": [{"id": 3, "name": "Clicked CTA"}], "date_from": "-7d"}
        assert extract_date_from(None, legacy) == "-7d"
        assert [(s.kind, s.name) for s in extract_series(None, legacy)] == [
            ("events", "$pageview"),
            ("actions", "Clicked CTA"),
        ]

    def test_suggestion_only_for_exact_day_window_claims(self) -> None:
        assert (
            suggest_renamed_name(
                "Pageviews (last 14 days)",
                Verdict.STALE_DATE_RANGE,
                claim=DateRangeClaim("last 14 days", days=14),
                date_from="-30d",
            )
            == "Pageviews (last 30 days)"
        )
        # shorthand claims keep the shorthand style
        assert (
            suggest_renamed_name(
                "All pageviews, last 7d", Verdict.STALE_DATE_RANGE, claim=DateRangeClaim("7d", days=7), date_from="-14d"
            )
            == "All pageviews, last 14d"
        )
        # start-anchored / all-time windows have no substitution
        assert (
            suggest_renamed_name(
                "Pageviews (last 14 days)",
                Verdict.STALE_DATE_RANGE,
                claim=DateRangeClaim("last 14 days", days=14),
                date_from="-0mStart",
            )
            is None
        )
        # cadence claims are never mechanically renamable
        assert (
            suggest_renamed_name(
                "Weekly active users",
                Verdict.STALE_DATE_RANGE,
                claim=DateRangeClaim("Weekly active users", days=7, kind="cadence"),
                date_from="-1d",
            )
            is None
        )


# ---------------------------------------------------------------------------
# 3. Static skill tests
# ---------------------------------------------------------------------------


class TestInsightHygieneSkillDefinition(SimpleTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.references = (SKILL_DIR / "references" / "queries.md").read_text(encoding="utf-8")
        (cls.canonical,) = [
            s for s in discover_canonical_skills(SKILLS_DIR) if s.name == "signals-scout-insight-hygiene"
        ]

    def test_skill_directory_shape(self) -> None:
        assert (SKILL_DIR / "SKILL.md").is_file()
        assert (SKILL_DIR / "references" / "queries.md").is_file()

    def test_frontmatter_opts_into_the_report_channel_only(self) -> None:
        # Report-only by design: the scout suggests fixes; humans apply them. No user-write
        # tools may appear in the frontmatter.
        assert sorted(self.canonical.allowed_tools) == ["edit_report", "emit_report"]

    def test_frontmatter_description_stands_alone(self) -> None:
        assert self.canonical.description
        assert len(self.canonical.description) <= 400
        assert "insight" in self.canonical.description.lower()

    def test_body_keeps_the_required_anatomy(self) -> None:
        for heading in (
            "## Quick close-out",
            "### Get oriented",
            "### Close out",
            "## Disqualifiers",
            "## MCP tools",
            "## When to stop",
        ):
            assert heading in self.skill_md, f"missing section: {heading}"

    def test_body_references_the_bundled_file(self) -> None:
        assert "references/queries.md" in self.skill_md
        assert (SKILL_DIR / "references" / "queries.md").is_file()

    def test_body_encodes_the_mechanical_rules_the_corpus_asserts(self) -> None:
        """Drift tripwire: the prompt's rules and the tested rule engine must keep agreeing.
        Change a rule in one place only, and this test rings the bell."""
        for check in ("Stale window", "Stale event", "Broken comparison"):
            assert check in self.skill_md
            assert check in self.references
        # rename eligibility: exact-day substitution only, descriptions never rewritten
        assert "rename-eligible" in self.references.lower()
        assert "exact-day" in self.references
        assert "report-only" in self.skill_md
        # the headline worked example matches the corpus exactly
        assert "Pageviews (last 14 days)" in self.skill_md
        assert "Pageviews (last 30 days)" in self.references
        headline = next(s for s in SCENARIOS if s[0] == "window_edit_rename")
        assert headline[1] == "Pageviews (last 14 days)" and headline[8] == "Pageviews (last 30 days)"
        # write discipline: title-only edits, never the query itself
        assert "`query`" in self.skill_md
        # the reference-implementation pointer keeps the two surfaces linked
        assert "insight_hygiene.py" in self.skill_md
        assert "test_insight_hygiene.py" in self.skill_md

    def test_body_reuses_fleet_scratchpad_prefixes_only(self) -> None:
        """Fleet rule: a new scout introduces its own domain label but reuses the canonical key
        prefixes (dedupe-and-memory.md). No invented ones."""
        canonical_prefixes = {
            "pattern",
            "noise",
            "addressed",
            "dedupe",
            "allowlist",
            "not-in-use",
            "mcp-gap",
            "improve",
            "reported",
            "report",
            "reviewer",
        }
        body_prefixes = set(re.findall(r"`([a-z\-]+):" + r"insight_hygiene", self.skill_md))
        assert body_prefixes, "no scoped scratchpad keys found in the body"
        assert body_prefixes <= canonical_prefixes, (
            f"invented scratchpad prefixes: {sorted(body_prefixes - canonical_prefixes)}. "
            "Use the fleet vocabulary (see authoring-scouts/references/dedupe-and-memory.md)."
        )

    def test_body_carries_sibling_courtesy(self) -> None:
        """The adjacent insight-reading scouts must be named so runs don't re-own their surfaces:
        dead-event insights are observability-gaps' insight-drift family."""
        assert "observability-gaps" in self.skill_md
        assert "Sibling courtesy" in self.skill_md
        # and the digest convention: one bundled report per run, NO_REPO sentinel
        assert "ONE bundled report" in self.skill_md
        assert "NO_REPO" in self.skill_md

    def test_references_document_every_mechanical_rule(self) -> None:
        for token in (
            "-0mStart",
            "-0dStart",
            "-Nd",
            "cadence",
            "TrendsQuery",
            "StickinessQuery",
            "LifecycleQuery",
            "filters",
            "ActionsNode",
            "at least as long",
        ):
            assert token in self.references, f"references/queries.md is missing rule token {token!r}"

    def test_worked_examples_agree_with_the_corpus(self) -> None:
        """Every worked-example row in references/queries.md whose name also appears in the
        corpus must carry the same verdict. The table is what the scout imitates. The corpus is
        tested."""
        for case_name, name, _desc, _q, _l, _k, expected_confusing, _action, _s in SCENARIOS:
            expected_words = ("stale", "broken", "confusing") if expected_confusing else ("clean",)
            matching_rows = [line for line in self.references.splitlines() if line.startswith(f"| {name}")]
            if not matching_rows:
                continue
            assert any(any(word in line.lower() for word in expected_words) for line in matching_rows), (
                f"worked example for {name!r} ({case_name}) disagrees with the corpus: {matching_rows}"
            )

    def test_sweep_sql_parses_as_hogql(self) -> None:
        """Every fenced SQL block in the references must be syntactically valid HogQL. A broken
        query here means every run of this scout crashes at step one."""
        from posthog.hogql.parser import parse_select

        blocks = re.findall(r"```sql\n(.*?)```", self.references, re.S)
        assert len(blocks) >= 4, f"expected schema-confirm, count, sweep, and vocabulary queries, found {len(blocks)}"
        for sql in blocks:
            parse_select(sql.strip())

    def test_sweep_read_uses_the_system_schema(self) -> None:
        """Fleet convention (anomaly-detection, observability-gaps, revenue-analytics scouts): the
        dashboard-item table is `system.insights`. A bare `insights` doesn't resolve in HogQL, and
        the execute-sql contract requires confirming columns against information_schema first."""
        sweep = next(
            b for b in re.findall(r"```sql\n(.*?)```", self.references, re.S) if "ORDER BY last_modified_at DESC" in b
        )
        assert "FROM system.insights" in sweep, f"sweep must read system.insights, got: {sweep}"
        for column in ("short_id", "name", "description", "query", "filters", "last_modified_at"):
            assert column in sweep
        assert "system.information_schema.columns" in self.references
        # no query reads the bare table name (word-boundary check, `system.insights` must not match)
        assert not re.search(r"FROM\s+insights\b", self.references), (
            "found a bare `FROM insights`. Use `system.insights`."
        )


class TestFleetShape(SimpleTestCase):
    def test_new_scout_is_registered_in_skills_agents_md(self) -> None:
        agents_md = (SKILLS_DIR / "AGENTS.md").read_text(encoding="utf-8")
        assert "signals-scout-insight-hygiene" in agents_md
