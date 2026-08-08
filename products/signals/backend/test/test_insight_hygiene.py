"""Test suite for the insight-hygiene scout. Three layers:

1. **Scenario corpus**. Named (name, description, query) cases with an expected verdict and
   action. The corpus runs through the mechanical rule engine in
   `products/signals/backend/scout_harness/insight_hygiene.py`. The scout's
   `references/queries.md` states the same rules. This is the behavioral contract: every
   confusing shape the scout must catch, and every clean shape it must leave alone.
2. **Scope wiring**. The `update_insights` allowed-tool opt-in is the only way a scout token
   gains `insight:write`. Covers the skill-loader mapping, its scope validation, and the
   runner's sandbox posture end to end.
3. **Static skill tests**. The SKILL.md must parse. It must carry the opt-in and the required
   anatomy sections. Its bundled `references/queries.md` must exist. The body must still state
   the mechanical rules the corpus asserts. This keeps the prompt and the tested rules from
   drifting apart silently.
"""

from __future__ import annotations

import re
import random
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.apps import apps
from django.test import SimpleTestCase

import pytest_asyncio
from asgiref.sync import sync_to_async
from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async
from posthog.temporal.oauth import MCP_WRITE_SCOPES

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
from products.signals.backend.scout_harness.runner import arun_signals_scout
from products.signals.backend.scout_harness.skill_loader import (
    OPT_IN_USER_WRITE_TOOLS,
    skill_opted_in_user_write_scopes,
)
from products.skills.backend.models.skills import LLMSkill

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
        Action.RENAME,
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
        Action.RENAME,
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
        Action.RENAME,
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
        Action.RENAME,
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
        if expected_action == Action.RENAME:
            assert assessment.suggested_name is not None, f"{case_name}: a rename verdict must carry a suggestion"
        if expected_suggested is not None:
            assert assessment.suggested_name == expected_suggested, f"{case_name}: {assessment.suggested_name!r}"

    def test_corpus_has_no_duplicate_case_names(self) -> None:
        names = [s[0] for s in SCENARIOS]
        assert len(names) == len(set(names))

    def test_renames_change_only_the_day_count(self) -> None:
        """Every suggested rename must differ from the original title by the digit run only.
        A rename that restructures the title is taste, not mechanics."""
        for _, name, _desc, query, legacy, known, _conf, action, suggested in SCENARIOS:
            if action != Action.RENAME or suggested is None:
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
# 2. Scope wiring
# ---------------------------------------------------------------------------


class TestUpdateInsightsOptIn(SimpleTestCase):
    def test_report_tools_without_update_insights_get_no_scope(self) -> None:
        assert skill_opted_in_user_write_scopes(["emit_report", "edit_report"]) == []

    def test_update_insights_maps_to_insight_write(self) -> None:
        assert skill_opted_in_user_write_scopes(["emit_report", "edit_report", "update_insights"]) == ["insight:write"]

    def test_unknown_allowed_tools_are_ignored(self) -> None:
        assert skill_opted_in_user_write_scopes(["delete_everything"]) == []

    def test_opt_in_map_targets_only_advertised_scopes(self) -> None:
        for tool, scope in OPT_IN_USER_WRITE_TOOLS.items():
            assert scope in MCP_WRITE_SCOPES, f"{tool} → {scope} is not an advertised MCP write scope"

    def test_bad_map_entry_fails_loud_at_resolution_time(self) -> None:
        # The map is repo-controlled, but if a future edit points it at a scope the MCP server
        # doesn't advertise, resolution must raise one hop from the runner rather than minting a
        # token carrying a scope nothing understands.
        with patch.dict(OPT_IN_USER_WRITE_TOOLS, {"bad_tool": "planet:destroy"}):
            with pytest.raises(ValueError, match="not an advertised MCP write scope"):
                skill_opted_in_user_write_scopes(["bad_tool"])


# `resolve_scopes`' preset-plus-extras resolution, validation, and `has_write_scopes` posture
# are covered in `posthog/temporal/tests/test_oauth.py` (the canonical scope-test home).

# --- runner wiring: the opt-in must reach the sandbox context end-to-end ----------


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"InsightHygieneTestOrg-{random.randint(1, 99999)}",
        is_ai_data_processing_approved=True,
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"InsightHygieneTestTeam-{random.randint(1, 99999)}",
    )
    with team_scope(team.id, canonical=True):
        yield team
    await sync_to_async(team.delete)()


def _make_fake_session(team: Team) -> tuple[MagicMock, MagicMock]:
    """Build the (session, result) pair that `MultiTurnSession.start` returns. The session
    carries a saved task_run, so the bridge insert (an FK requirement) succeeds."""
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")
    task = Task.objects.create(
        team=team,
        title="scout run",
        description="scout run",
        origin_product=Task.OriginProduct.SIGNALS_SCOUT,
    )
    task_run = TaskRun.objects.create(task=task, team=team)
    session = MagicMock()
    session.task_run = task_run
    session.end = AsyncMock()
    result = MagicMock()
    result.summary = "quiet"
    return session, result


async def _capture_mcp_scopes(ateam: Team, *, allowed_tools: list[str]) -> object:
    """Run one scout with a fake session and capture the `posthog_mcp_scopes` the runner put in
    the sandbox context."""
    from products.signals.backend.scout_harness import runner as runner_mod

    skill = await sync_to_async(LLMSkill.objects.create)(
        team=ateam,
        name=f"signals-scout-hygiene-test-{random.randint(1, 99999)}",
        description="test scout",
        body="scout",
        allowed_tools=allowed_tools,
    )
    session, result = await database_sync_to_async(_make_fake_session, thread_sensitive=False)(ateam)
    captured: dict = {}
    original_context = runner_mod.CustomPromptSandboxContext

    def _capturing_context(**kwargs):
        captured.update(kwargs)
        return original_context(**kwargs)

    async def _fake_start(*args, on_task_run_created=None, **kwargs):
        if on_task_run_created is not None:
            await on_task_run_created(session.task_run)
        return session, result

    with (
        patch.object(runner_mod, "CustomPromptSandboxContext", side_effect=_capturing_context),
        patch("products.signals.backend.scout_harness.runner.MultiTurnSession.start", new=_fake_start),
        patch(
            "products.signals.backend.scout_harness.runner.get_or_create_signals_sandbox_env",
            return_value="env-id",
        ),
        patch(
            "products.signals.backend.scout_harness.runner.resolve_acting_user_id_for_team",
            return_value=42,
        ),
    ):
        await arun_signals_scout(team_id=ateam.id, skill_name=skill.name)
    return captured.get("posthog_mcp_scopes")


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_opted_in_scout_gets_insight_write_on_top_of_report_posture(ateam):
    # The runner resolves the scout preset through the public resolve_scopes API and appends
    # the opt-in scope. The shared OAuth token code only ever sees a plain list.
    from posthog.temporal.oauth import resolve_scopes

    scopes = await _capture_mcp_scopes(ateam, allowed_tools=["emit_report", "edit_report", "update_insights"])
    assert scopes == [*resolve_scopes("signals_scout_reports"), "insight:write"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_scout_without_opt_in_keeps_the_bare_preset(ateam):
    scopes = await _capture_mcp_scopes(ateam, allowed_tools=["emit_report", "edit_report"])
    assert scopes == "signals_scout_reports"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_opt_in_also_applies_to_non_report_scouts(ateam):
    from posthog.temporal.oauth import resolve_scopes

    scopes = await _capture_mcp_scopes(ateam, allowed_tools=["update_insights"])
    assert scopes == [*resolve_scopes("signals_scout"), "insight:write"]


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

    def test_frontmatter_opts_into_report_channel_and_insight_write(self) -> None:
        assert sorted(self.canonical.allowed_tools) == ["edit_report", "emit_report", "update_insights"]
        assert skill_opted_in_user_write_scopes(list(self.canonical.allowed_tools)) == ["insight:write"]

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
