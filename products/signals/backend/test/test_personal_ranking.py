import json
import datetime
import dataclasses
from collections.abc import Callable
from io import StringIO
from types import SimpleNamespace
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.db.models import F
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import httpx
from openai import APITimeoutError, BadRequestError, omit
from parameterized import parameterized

from posthog.models import OrganizationMembership, Team, User
from posthog.redis import TEST_clear_clients
from posthog.token_bucket import TEST_reset_scripts

from products.signals.backend.activity_summary.read import (
    ActivitySummaryStatus,
    ActivitySummaryTheme,
    ActivitySummaryView,
)
from products.signals.backend.artefact_schemas import RankingModelResult, RankingScore
from products.signals.backend.models import (
    PersonalInboxRanking,
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
)
from products.signals.backend.personal_ranking import serve as personal_ranking_serve
from products.signals.backend.personal_ranking.candidates import Candidate
from products.signals.backend.personal_ranking.config import (
    CandidatePool,
    PersonalRankingConfig,
    PersonalRankingTickConfig,
    ReasonLimits,
    parse_config,
)
from products.signals.backend.personal_ranking.list_sort import personal_ranking_state
from products.signals.backend.personal_ranking.logic import (
    BUILT_EVENT,
    InputChanges,
    build_personal_ranking,
    compare_inputs,
    input_hash,
    input_parts,
)
from products.signals.backend.personal_ranking.prompt import render_person, system_prompt, user_message
from products.signals.backend.personal_ranking.validation import MalformedRankingError, validate_ranking
from products.signals.backend.personal_ranking_tasks import (
    build_lock_key,
    build_personal_inbox_ranking,
    start_first_summary_build,
)
from products.signals.backend.ranking.inbox_sort import PERSONAL_RECOMMENDED_FLAG, RECOMMENDED_INBOX_SORT_FLAG
from products.signals.backend.ranking.report_predictions import OutcomePrediction, ReportPredictions

REFS = ["c1", "c2", "c3", "c4"]
MODEL_REASONS = {ref: f"model {ref}" for ref in REFS}
LIMITS = ReasonLimits(top=40, worth_a_look=30, later=20)


def _entry(
    ref: str,
    rank: Any,
    tier: str = "worth_a_look",
    reason: str = "matches",
    next_step: str | None = None,
    matched: dict | None = None,
):
    return {"ref": ref, "rank": rank, "tier": tier, "reason": reason, "matched": matched, "next_step": next_step}


def _answer(ranked: list[dict], folded: list[dict] | None = None) -> str:
    return json.dumps({"ranked": ranked, "folded": folded or []})


def _validate(
    content: str | None,
    limit: int = 2,
    rank_top: int = 10,
    top_max: int = 5,
    worth_a_look_max: int = 10,
    needs_you: dict[str, tuple] | None = None,
):
    return validate_ranking(
        content,
        refs=REFS,
        model_reasons=MODEL_REASONS,
        needs_you=needs_you or {},
        limit=limit,
        rank_top=rank_top,
        top_max=top_max,
        worth_a_look_max=worth_a_look_max,
        reason_limits=LIMITS,
        next_step_max_chars=12,
    )


class TestValidateRanking(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "duplicate_ranks_keep_array_order",
                [_entry("c2", 1), _entry("c1", 1), _entry("c3", 2), _entry("c4", 3)],
                [],
                ["c2", "c1", "c3", "c4"],
                {"renumbered": 3},
            ),
            (
                "gaps_close",
                [_entry("c3", 4), _entry("c1", 9), _entry("c2", 2), _entry("c4", 20)],
                [],
                ["c2", "c3", "c1", "c4"],
                {"renumbered": 4},
            ),
            (
                "unknown_refs_drop",
                [_entry("c99", 1), _entry("c1", 2), _entry("c2", 3), _entry("c3", 4), _entry("c4", 5)],
                [],
                ["c1", "c2", "c3", "c4"],
                {"unknown_refs": 1, "renumbered": 4},
            ),
            (
                "missing_refs_follow_in_model_order",
                [_entry("c3", 1)],
                [],
                ["c3", "c1", "c2", "c4"],
                {"missing_refs": 3},
            ),
            (
                "repeat_ref_keeps_its_best_rank",
                [_entry("c2", 3), _entry("c2", 1), _entry("c1", 2), _entry("c3", 4), _entry("c4", 5)],
                [],
                ["c2", "c1", "c3", "c4"],
                {"duplicate_refs": 1, "renumbered": 2},
            ),
            (
                "folded_refs_get_no_rank",
                [_entry("c1", 1), _entry("c2", 2), _entry("c3", 3), _entry("c4", 4)],
                [
                    {"ref": "c2", "into": "c1", "reason": "same digest"},
                    {"ref": "c3", "into": "c2", "reason": "into a folded ref"},
                    {"ref": "c4", "into": "c4", "reason": "into itself"},
                    {"ref": "c9", "into": "c1", "reason": "unknown"},
                ],
                ["c1", "c3", "c4"],
                {"invalid_folds": 3, "renumbered": 2},
            ),
            (
                "entries_past_rank_top_follow_in_model_order",
                [_entry("c4", 1), _entry("c3", 2), _entry("c2", 3), _entry("c1", 4)],
                [],
                ["c4", "c3", "c1", "c2"],
                {"beyond_rank_top": 2},
                2,
            ),
            (
                "folds_apply_past_rank_top",
                [_entry("c4", 1), _entry("c3", 2)],
                [{"ref": "c1", "into": "c4", "reason": "same digest"}],
                ["c4", "c2", "c3"],
                {"beyond_rank_top": 1, "missing_refs": 1},
                1,
            ),
        ]
    )
    def test_order_covers_every_unfolded_candidate(
        self,
        _name: str,
        ranked: list[dict],
        folded: list[dict],
        expected_refs: list[str],
        expected_counts: dict,
        rank_top: int = 10,
    ) -> None:
        result = _validate(_answer(ranked, folded), rank_top=rank_top)

        assert [entry.ref for entry in result.entries] == expected_refs
        assert [entry.rank for entry in result.entries] == list(range(1, len(expected_refs) + 1))
        assert {key: value for key, value in dataclasses.asdict(result.counts).items() if value} == expected_counts
        assert all(entry.reason for entry in result.entries)

    def test_missing_refs_get_model_reasons_and_tiers_never_rise(self) -> None:
        result = _validate(
            _answer(
                [
                    _entry("c1", 1, tier="later", reason="r" * 50, next_step="open the PR now please"),
                    _entry("c2", 2, tier="top", next_step="look"),
                    _entry("c3", 3, tier="worth_a_look", next_step="beyond the limit"),
                ]
            )
        )

        assert [(entry.ref, entry.tier, entry.ranked_by) for entry in result.entries] == [
            ("c1", "later", "llm"),
            ("c2", "later", "llm"),
            ("c3", "later", "llm"),
            ("c4", "later", "model"),
        ]
        assert result.counts.tier_corrections == 2
        assert result.entries[0].reason == "r" * 19 + "…"
        assert [entry.next_step for entry in result.entries] == ["open the PR…", "look", None, None]
        assert result.entries[3].reason == "model c4"

    @parameterized.expand(
        [
            (
                "full_top_spills_into_worth_a_look",
                ["top"] * 4,
                1,
                2,
                ["top", "worth_a_look", "worth_a_look", "later"],
                3,
            ),
            (
                "full_worth_a_look_spills_into_later",
                ["top", "top", "top", "worth_a_look"],
                2,
                1,
                ["top", "top", "worth_a_look", "later"],
                2,
            ),
        ]
    )
    def test_entries_past_a_tier_cap_move_down_and_keep_their_rank(
        self,
        _name: str,
        tiers: list[str],
        top_max: int,
        worth_a_look_max: int,
        expected_tiers: list[str],
        expected_demotions: int,
    ) -> None:
        ranked = [_entry(ref, rank, tier=tier) for rank, (ref, tier) in enumerate(zip(REFS, tiers), start=1)]

        result = _validate(_answer(ranked), top_max=top_max, worth_a_look_max=worth_a_look_max)

        assert [(entry.ref, entry.rank, entry.tier) for entry in result.entries] == [
            (ref, rank, tier) for rank, (ref, tier) in enumerate(zip(REFS, expected_tiers), start=1)
        ]
        assert result.counts.tier_demotions == expected_demotions
        assert result.counts.tier_corrections == 0

    @parameterized.expand(
        [
            (
                "status_read_as_a_personal_claim_falls_back_to_the_theme",
                {"theme": "Checkout", "needs_you": ["waiting_on_input"]},
                (),
                {"theme": "Checkout", "needs_you": ()},
                "Matches your recent work: Checkout.",
                1,
            ),
            (
                "false_claim_with_no_theme_gets_the_model_reason",
                {"theme": None, "needs_you": ["suggested_reviewer"]},
                (),
                {"theme": None, "needs_you": ()},
                "model c1",
                1,
            ),
            (
                "only_the_false_kind_drops_and_the_real_fact_wins_over_the_theme",
                {"theme": "Checkout", "needs_you": ["waiting_on_input", "claimed"]},
                ("claimed",),
                {"theme": "Checkout", "needs_you": ("claimed",)},
                "model c1",
                1,
            ),
            (
                "true_claim_keeps_the_model_reason",
                {"theme": None, "needs_you": ["claimed"]},
                ("claimed",),
                {"theme": None, "needs_you": ("claimed",)},
                "Waiting on you",
                0,
            ),
        ]
    )
    def test_needs_you_claims_must_match_the_facts(
        self,
        _name: str,
        matched: dict,
        facts: tuple,
        expected_matched: dict,
        expected_reason: str,
        expected_false: int,
    ) -> None:
        result = _validate(
            _answer([_entry("c1", 1, tier="top", reason="Waiting on you", matched=matched)]),
            needs_you={"c1": facts},
        )

        entry = result.entries[0]
        assert (entry.rank, entry.tier) == (1, "top")
        assert dataclasses.asdict(entry.matched) == expected_matched
        assert entry.reason == expected_reason
        assert result.counts.false_needs_you == expected_false

    @parameterized.expand(
        [
            ("empty", None),
            ("not_json", "Here is your ranking: c1, c2"),
            ("no_ranked_list", json.dumps({"order": ["c1"]})),
            ("bad_tier", _answer([_entry("c1", 1, tier="urgent")])),
            ("boolean_rank", _answer([_entry("c1", True)])),
            ("only_unknown_refs", _answer([_entry("c7", 1)])),
        ]
    )
    def test_malformed_output_raises(self, _name: str, content: str | None) -> None:
        with self.assertRaises(MalformedRankingError):
            _validate(content)


def _candidate(index: int, report_id: str, **overrides: Any) -> Candidate:
    now = timezone.now()
    fields: dict[str, Any] = {
        "ref": f"c{index}",
        "report_id": report_id,
        "title": f"Report {index}",
        "summary_lead": f"Summary {index}",
        "status": "ready",
        "priority": "P2",
        "pull_request_state": "open",
        "source_products": ("error_tracking",),
        "scout_name": None,
        "created_at": now - datetime.timedelta(days=3),
        "updated_at": now - datetime.timedelta(hours=2),
        "predictions": ReportPredictions(
            status="scored",
            model="m@1",
            predictions=(OutcomePrediction(outcome="action", probability=0.42, lift=7.9, readable=True),),
        ),
        "needs_you": ("suggested_reviewer",),
        "tags": (),
        "pools": ("for_you_recommended",),
    }
    return Candidate(**{**fields, **overrides})


_IDS = ["018f3d0e-0000-7000-8000-000000000001", "018f3d0e-0000-7000-8000-000000000002"]
CONFIG = PersonalRankingConfig()


def _scored(probability: float) -> ReportPredictions:
    return ReportPredictions(
        status="scored",
        model="m@1",
        predictions=(OutcomePrediction(outcome="action", probability=probability, lift=None, readable=True),),
    )


class TestInputParts(SimpleTestCase):
    def test_input_hash_keeps_its_value(self) -> None:
        candidates = [_candidate(1, _IDS[0]), _candidate(2, _IDS[1], predictions=None, needs_you=())]

        assert (
            input_hash(candidates, config=CONFIG, limit=25, activity_summary_version=7, focus="checkout")
            == "3d3077866e85c6b1868f952a33a297762db56b2abc2978e2e68bdcf4811c4baf"
        )

    @parameterized.expand(
        [
            ("nothing", {}, 7, InputChanges(changed_parts=(), changed_report_count=0, max_score_move=0.0)),
            (
                "score_jitter_under_the_rounding",
                {"predictions": _scored(0.421)},
                7,
                InputChanges(changed_parts=(), changed_report_count=0, max_score_move=0.001),
            ),
            (
                "score",
                {"predictions": _scored(0.5)},
                7,
                InputChanges(changed_parts=("scores",), changed_report_count=1, max_score_move=0.08),
            ),
            (
                "summary_version",
                {},
                8,
                InputChanges(changed_parts=("activity_summary_version",), changed_report_count=0, max_score_move=0.0),
            ),
            (
                "text_and_needs_you",
                {"title": "Renamed", "needs_you": ("claimed",)},
                7,
                InputChanges(changed_parts=("text", "needs_you"), changed_report_count=1, max_score_move=0.0),
            ),
            (
                "prompt_lever",
                {},
                7,
                InputChanges(changed_parts=("config",), changed_report_count=0, max_score_move=0.0),
                dataclasses.replace(CONFIG, rank_top=10),
            ),
            (
                "reasoning_effort",
                {},
                7,
                InputChanges(changed_parts=("config",), changed_report_count=0, max_score_move=0.0),
                dataclasses.replace(CONFIG, reasoning_effort="high"),
            ),
        ]
    )
    def test_names_the_changed_parts(
        self,
        _name: str,
        overrides: dict[str, Any],
        summary_version: int,
        expected: InputChanges,
        config: PersonalRankingConfig = CONFIG,
    ) -> None:
        stored = PersonalInboxRanking(
            input_parts=input_parts(
                [_candidate(1, _IDS[0])], config=CONFIG, limit=25, activity_summary_version=7, focus=None
            )
        )
        current = input_parts(
            [_candidate(1, _IDS[0], **overrides)],
            config=config,
            limit=25,
            activity_summary_version=summary_version,
            focus=None,
        )

        assert compare_inputs(stored, current, rank_top=10) == dataclasses.replace(
            expected, joined_count=0, left_count=0, left_top_count=0
        )

    def test_counts_the_reports_that_joined_and_left_the_stored_top(self) -> None:
        ids = [f"018f3d0e-0000-7000-8000-00000000000{index}" for index in range(1, 5)]
        stored = PersonalInboxRanking(
            input_parts=input_parts(
                [_candidate(index, ids[index - 1]) for index in (1, 2, 3)],
                config=CONFIG,
                limit=25,
                activity_summary_version=7,
                focus=None,
            ),
            result={"ranked": [{"report_id": ids[1]}, {"report_id": ids[0]}, {"report_id": ids[2]}]},
        )
        current = input_parts(
            [_candidate(1, ids[0]), _candidate(4, ids[3])],
            config=CONFIG,
            limit=25,
            activity_summary_version=7,
            focus=None,
        )

        changes = compare_inputs(stored, current, rank_top=2)

        assert (changes.changed_parts, changes.joined_count, changes.left_count, changes.left_top_count) == (
            ("candidate_set",),
            1,
            2,
            1,
        )

    @parameterized.expand(
        [
            ("no_previous_list", None, ("no_previous_list",)),
            ("row_from_before_the_parts", PersonalInboxRanking(input_parts=None), ("unknown",)),
            ("unreadable_parts", PersonalInboxRanking(input_parts={"parts": []}), ("unknown",)),
        ]
    )
    def test_a_previous_list_without_parts_reports_why(
        self, _name: str, previous: PersonalInboxRanking | None, expected: tuple[str, ...]
    ) -> None:
        current = input_parts([_candidate(1, _IDS[0])], config=CONFIG, limit=25, activity_summary_version=7, focus=None)

        assert compare_inputs(previous, current, rank_top=10) == InputChanges(changed_parts=expected)


class TestPrompt(SimpleTestCase):
    def test_candidates_are_labelled_by_ref_and_the_profile_is_capped(self) -> None:
        ids = ["018f3d0e-0000-7000-8000-000000000001", "018f3d0e-0000-7000-8000-000000000002"]
        candidates = [_candidate(1, ids[0], summary_lead=""), _candidate(2, ids[1], predictions=None)]
        summary = ActivitySummaryView(
            status=ActivitySummaryStatus.READY,
            headline="Works on checkout",
            profile="p" * 2000,
            themes=(
                ActivitySummaryTheme(
                    label="Checkout", mode="build", strength="strong", refs=(), last_seen="2026-10-29"
                ),
            ),
        )
        config = PersonalRankingConfig(profile_max_chars=100)

        message = user_message(
            render_person(summary, config), candidates, focus=None, now=timezone.now(), limit=25, rank_top=10
        )

        assert not any(report_id in message for report_id in ids)
        assert "\nc1 | P2 | ready | PR open" in message
        assert "\nc2 | P2 | ready | PR open" in message
        assert "model: action 0.42 (lift 7.9)" in message
        assert message.count("model:") == 1
        assert "p" * 100 in message and "p" * 101 not in message
        assert "- Checkout (mode build, strength strong, last seen 2026-10-29)" in message

    def test_system_prompt_states_the_tier_and_reason_caps(self) -> None:
        prompt = system_prompt(
            PersonalRankingConfig(
                top_max=3, worth_a_look_max=7, reason_limits=ReasonLimits(top=90, worth_a_look=60, later=30)
            ),
            limit=25,
        )

        assert '"top" for at most 3 reports' in prompt
        assert '"worth_a_look" for at most 7 other' in prompt
        assert 'At most 90 characters for "top", 60 for "worth_a_look", 30 for "later".' in prompt


class TestConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing_payload", None, PersonalRankingConfig()),
            ("kill_switch", {"enabled": False}, PersonalRankingConfig(enabled=False)),
            (
                "invalid_and_large_values",
                {"max_candidates": 10_000, "window_days": True, "timeout_seconds": -1, "model": ""},
                PersonalRankingConfig(max_candidates=100),
            ),
            (
                "default_limit_and_rank_top_within_max_limit",
                {"default_limit": 40, "rank_top": 40, "max_limit": 30},
                PersonalRankingConfig(default_limit=30, rank_top=30, max_limit=30),
            ),
            (
                "pools_in_order_with_default_names_and_large_values_capped",
                {
                    "pools": [
                        {"source": "for_you_updated", "size": 5},
                        {"source": "assigned", "size": 0},
                        {"source": "for_you_recommended", "size": 500},
                    ]
                },
                PersonalRankingConfig(
                    pools=(
                        CandidatePool(name="for_you_updated", source="for_you_updated", size=5),
                        CandidatePool(name="assigned", source="assigned", size=0),
                        CandidatePool(name="for_you_recommended", source="for_you_recommended", size=100),
                    )
                ),
            ),
            (
                "invalid_pools_drop",
                {
                    "pools": [
                        {"source": "assigned", "size": 5, "name": "mine"},
                        {"source": "for_you_updated", "size": 5, "name": "mine"},
                        {"source": "everything", "size": 5},
                        {"source": "scored", "size": 5, "head": "action"},
                        {"source": "priority", "size": 5, "lowest_priority": "P1"},
                        {"source": "assigned", "size": 5, "head": "open"},
                        {"source": "assigned", "size": 5, "window_days": 30},
                        {"source": "assigned", "size": True},
                        {"source": "assigned", "size": -1},
                        {"source": "assigned", "size": 5, "name": "Has Spaces"},
                    ]
                },
                PersonalRankingConfig(pools=(CandidatePool(name="mine", source="assigned", size=5),)),
            ),
            (
                "no_valid_pool_keeps_the_defaults",
                {"pools": [{"source": "scored", "size": 5, "head": "action"}]},
                PersonalRankingConfig(),
            ),
            ("pools_not_a_list", {"pools": {"source": "assigned", "size": 5}}, PersonalRankingConfig()),
            (
                "pools_past_the_maximum_drop",
                {"pools": [{"source": "assigned", "size": 1, "name": f"p{index}"} for index in range(12)]},
                PersonalRankingConfig(
                    pools=tuple(CandidatePool(name=f"p{index}", source="assigned", size=1) for index in range(10))
                ),
            ),
            ("reasoning_effort", {"reasoning_effort": "high"}, PersonalRankingConfig(reasoning_effort="high")),
            ("invalid_reasoning_effort", {"reasoning_effort": "max"}, PersonalRankingConfig()),
            ("tick_without_enabled_stays_off", {"tick": {"organization_ids": ["org"]}}, PersonalRankingConfig()),
            (
                "tick_drops_invalid_values_and_caps_large_ones",
                {
                    "tick": {
                        "enabled": True,
                        "organization_ids": ["org", 3, ""],
                        "skip_team_ids": [1, True, "2"],
                        "self_driving_organization_percentage": 101,
                        "max_pairs_per_tick": 10_000,
                        "max_concurrency": 1000,
                        "max_tick_builds_per_day": -1,
                        "max_org_share": 2,
                        "overdue_after_minutes": -1,
                        "time_budget_share": 2,
                    },
                    "max_builds_per_day": 100_000,
                },
                PersonalRankingConfig(
                    max_builds_per_day=50_000,
                    tick=PersonalRankingTickConfig(
                        enabled=True,
                        organization_ids=("org",),
                        skip_team_ids=(1,),
                        max_pairs_per_tick=2000,
                        max_concurrency=100,
                        time_budget_share=0.85,
                    ),
                ),
            ),
            (
                "enabled_tick_raises_freshness_and_overdue_age_and_leaves_a_shared_reserve",
                {
                    "max_builds_per_day": 100,
                    "tick": {"enabled": True, "target_interval_minutes": 180, "max_tick_builds_per_day": 100},
                },
                PersonalRankingConfig(
                    max_builds_per_day=100,
                    freshness_minutes=180,
                    tick=PersonalRankingTickConfig(
                        enabled=True,
                        target_interval_minutes=180,
                        overdue_after_minutes=360,
                        max_tick_builds_per_day=80,
                    ),
                ),
            ),
            (
                "disabled_tick_leaves_freshness_alone",
                {"tick": {"target_interval_minutes": 180}},
                PersonalRankingConfig(),
            ),
        ]
    )
    def test_parse_config(self, _name: str, payload: Any, expected: PersonalRankingConfig) -> None:
        assert parse_config(payload) == expected


def _response(content: str | None, finish_reason: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200),
        choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=content))],
    )


class TestBuildPersonalRanking(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.llm = MagicMock()
        scoped_capture = MagicMock()
        self.capture = scoped_capture.return_value.__enter__.return_value
        self.summary: ActivitySummaryView | None = ActivitySummaryView(
            status=ActivitySummaryStatus.READY, headline="Works on checkout", version=7
        )
        for target, value in (
            ("products.signals.backend.personal_ranking.logic.build_openai_client", MagicMock(return_value=self.llm)),
            (
                "products.signals.backend.personal_ranking.logic.get_summary",
                MagicMock(side_effect=lambda *_: self.summary),
            ),
            ("products.signals.backend.personal_ranking.logic.ph_scoped_capture", scoped_capture),
            (
                "products.signals.backend.personal_ranking.candidates.fetch_source_products_for_reports",
                MagicMock(return_value={}),
            ),
            (
                "products.signals.backend.ranking.inbox_sort.posthoganalytics.get_feature_flag",
                MagicMock(return_value="action_pills"),
            ),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.create = self.llm.with_options.return_value.chat.completions.create

    def _report(self, title: str, **fields: Any) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            title=title,
            summary=f"{title} summary",
            signal_count=1,
            total_weight=1.0,
            **{
                "status": SignalReport.Status.READY,
                "latest_actionability": "immediately_actionable",
                "latest_already_addressed": False,
                **fields,
            },
        )

    def _names_me(self, report: SignalReport) -> SignalReport:
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"user_uuid": str(self.user.uuid)}]),
        )
        return report

    def _score(self, report: SignalReport, action: float) -> None:
        served = RankingModelResult(
            model_name="report_embeddings",
            model_version="2026-09-01",
            model_kind="xgboost",
            roles=["served"],
            feature_schema_version=1,
            status="scored",
            scores={"open": 0.3, "action": action, "fixed": 0.1},
            lifts={},
            metadata={"heads": []},
        )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.RANKING_SCORE,
            content=RankingScore(
                scored_at=timezone.now(), manifest_version="m", served_key=served.key, results={served.key: served}
            ).model_dump_json(),
        )

    def _prioritize(self, report: SignalReport, priority: str) -> SignalReport:
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"priority": priority, "explanation": "test"}),
        )
        return report

    def _setup_reports(self) -> dict[str, SignalReport]:
        reports = {
            "waiting": self._names_me(self._report("Waiting", status=SignalReport.Status.PENDING_INPUT)),
            "reviewing": self._names_me(self._report("Reviewing")),
            "claimed": self._report("Claimed", status=SignalReport.Status.IN_PROGRESS),
        }
        SignalReportAssignment.all_teams.create(
            team=self.team, report=reports["claimed"], actor_kind="user", actor_user=self.user
        )
        self._names_me(self._report("Resolved", status=SignalReport.Status.RESOLVED))
        # Reads as resolved while the monitoring gate is off.
        monitoring = self._report("Monitoring", status=SignalReport.Status.MONITORING)
        SignalReportAssignment.all_teams.create(
            team=self.team, report=monitoring, actor_kind="user", actor_user=self.user
        )
        return reports

    def _build(self, **kwargs: Any):
        return build_personal_ranking(self.team, self.user, config=PersonalRankingConfig(), **kwargs)

    def test_ranks_every_candidate_and_stores_one_row(self) -> None:
        reports = self._setup_reports()

        def answer(**kwargs: Any) -> SimpleNamespace:
            prompt = kwargs["messages"][1]["content"]
            refs = [line.split(" | ")[0] for line in prompt.splitlines() if line.startswith("c") and " | " in line]
            ranked = [_entry(ref, len(refs) - index, reason=f"reason {ref}") for index, ref in enumerate(refs)]
            return _response(_answer([*ranked[:-1], _entry("c99", 1)]))

        self.create.side_effect = answer
        build = self._build(focus="  checkout   bugs ")

        row = PersonalInboxRanking.objects.for_team(self.team.id).get()
        ranked_ids = [entry["report_id"] for entry in row.result["ranked"]]
        assert sorted(ranked_ids) == sorted(str(report.id) for report in reports.values())
        assert row.candidate_ids == [candidate.report_id for candidate in build.candidates]
        assert [entry["rank"] for entry in row.result["ranked"]] == [1, 2, 3]
        assert [entry["ranked_by"] for entry in row.result["ranked"]] == ["llm", "llm", "model"]
        assert all(entry["reason"] for entry in row.result["ranked"])
        assert row.result["counts"]["unknown_refs"] == 1
        assert row.status == PersonalInboxRanking.Status.OK
        assert row.personalized is True
        assert row.activity_summary_version == 7
        assert row.tokens_in == 1000
        needs_you = {candidate.report_id: candidate.needs_you for candidate in build.candidates}
        assert needs_you == {
            str(reports["waiting"].id): ("waiting_on_input",),
            str(reports["reviewing"].id): ("suggested_reviewer",),
            str(reports["claimed"].id): ("claimed",),
        }
        assert "# Focus\ncheckout bugs" in self.create.call_args.kwargs["messages"][1]["content"]
        assert self.create.call_args.kwargs["reasoning_effort"] == "low"

        self.capture.assert_called_once()
        event = self.capture.call_args.kwargs
        assert event["event"] == BUILT_EVENT
        assert event["properties"]["ranking_id"] == str(row.id)
        assert (event["properties"]["personalized"], event["properties"]["model_called"]) == (True, True)
        assert event["properties"]["tier_counts"] == {"top": 0, "worth_a_look": 2, "later": 1}
        assert event["properties"]["report_ids"] == [
            *(entry["report_id"] for entry in row.result["ranked"]),
            *(fold["report_id"] for fold in row.result["folded"]),
        ]
        serialized = json.dumps(event["properties"])
        assert "Waiting" not in serialized and "reason c" not in serialized and "checkout" not in serialized

    @parameterized.expand(
        [
            ("timeout", APITimeoutError(request=httpx.Request("POST", "https://example.com")), "timeout"),
            ("api_error", RuntimeError("gateway down"), "llm_error"),
            ("malformed", _response("not json"), "malformed_output"),
            ("truncated", _response(_answer([_entry("c1", 1)]), finish_reason="length"), "truncated_output"),
            ("ai_not_approved", "not_approved", "ai_not_approved"),
            ("no_activity_summary", "no_summary", "no_activity_summary"),
        ]
    )
    def test_model_failure_falls_back_to_model_order(self, _name: str, outcome: Any, fallback_reason: str) -> None:
        reports = self._setup_reports()
        if outcome == "not_approved":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        elif outcome == "no_summary":
            self.summary = None
        elif isinstance(outcome, Exception):
            self.create.side_effect = outcome
        else:
            self.create.return_value = outcome

        build = self._build()

        assert build.status == "fallback"
        assert build.fallback_reason == fallback_reason
        assert build.personalized is False
        assert [entry.ref for entry in build.entries] == [candidate.ref for candidate in build.candidates]
        assert {entry.ranked_by for entry in build.entries} == {"model"}
        row = PersonalInboxRanking.objects.for_team(self.team.id).get()
        assert row.fallback_reason == fallback_reason
        assert {entry["report_id"]: entry["reason"] for entry in row.result["ranked"]} == {
            str(reports["waiting"].id): "Waiting on your input.",
            str(reports["reviewing"].id): "Kept in inbox order.",
            str(reports["claimed"].id): "You claimed this report.",
        }
        model_called = not isinstance(outcome, str)
        assert self.capture.call_args.kwargs["properties"]["model_called"] is model_called
        if not model_called:
            self.create.assert_not_called()

    def test_a_model_that_rejects_reasoning_effort_gets_calls_without_it(self) -> None:
        self._setup_reports()
        rejection = BadRequestError(
            "Unsupported parameter: 'reasoning_effort'",
            response=httpx.Response(400, request=httpx.Request("POST", "https://example.com")),
            body=None,
        )
        answer = _response(_answer([_entry("c1", 1)]))
        self.create.side_effect = [rejection, answer, answer]

        with patch("products.signals.backend.personal_ranking.logic._REJECTED_REASONING_EFFORTS", set()):
            first = self._build(dry_run=True)
            second = self._build(dry_run=True)

        assert (first.status, second.status) == ("ok", "ok")
        assert [call.kwargs["reasoning_effort"] for call in self.create.call_args_list] == ["low", omit, omit]

    @parameterized.expand(
        [
            ("can_see_scores", True, True),
            ("cannot_see_ranking", False, True),
            ("nothing_tied_to_them", True, False),
        ]
    )
    def test_only_reports_tied_to_the_person_are_candidates(self, _name: str, staff: bool, has_own: bool) -> None:
        self.user.is_staff = staff
        self.user.save(update_fields=["is_staff"])
        unowned = self._prioritize(self._report("Unowned actionable"), "P0")
        self._score(unowned, action=0.9)
        own = self._names_me(self._report("Routed to me")) if has_own else None
        if own is not None:
            self._score(own, action=0.2)
        self.create.return_value = _response(_answer([_entry("c1", 1)]))

        with patch("products.signals.backend.ranking.access.feature_enabled_or_false", return_value=False):
            build = self._build(dry_run=True)

        assert str(unowned.id) not in {candidate.report_id for candidate in build.candidates}
        if own is None:
            assert (build.status, build.fallback_reason, build.model_called) == ("empty", "no_candidates", False)
            self.create.assert_not_called()
        else:
            assert [candidate.report_id for candidate in build.candidates] == [str(own.id)]
            assert (build.candidates[0].predictions is not None) is staff

    def test_configured_pools_keep_their_order_and_names(self) -> None:
        claimed = self._report("Claimed", status=SignalReport.Status.IN_PROGRESS)
        SignalReportAssignment.all_teams.create(team=self.team, report=claimed, actor_kind="user", actor_user=self.user)
        routed = self._names_me(self._report("Routed"))
        self._report("Unrelated")
        self.create.return_value = _response(_answer([_entry("c1", 1)]))
        config = PersonalRankingConfig(
            pools=(
                CandidatePool(name="assigned", source="assigned", size=0),
                CandidatePool(name="mine", source="assigned", size=5),
                CandidatePool(name="routed", source="for_you_updated", size=5),
            )
        )

        build = build_personal_ranking(self.team, self.user, config=config, dry_run=True)

        pools = [(candidate.report_id, candidate.pools) for candidate in build.candidates]
        assert pools == [(str(claimed.id), ("mine",)), (str(routed.id), ("routed",))]

    @parameterized.expand([("dry_run", True, 0), ("stored", False, 1)])
    def test_command(self, _name: str, dry_run: bool, expected_rows: int) -> None:
        reports = self._setup_reports()
        self.create.return_value = _response(_answer([_entry("c1", 1, tier="top", next_step="Review the PR")]))
        out = StringIO()

        with patch(
            "products.signals.backend.management.commands.run_personal_inbox_ranking.read_config",
            return_value=PersonalRankingConfig(),
        ):
            call_command(
                "run_personal_inbox_ranking",
                "--team-id",
                str(self.team.id),
                "--user-id",
                str(self.user.id),
                *(["--dry-run"] if dry_run else []),
                stdout=out,
            )

        assert PersonalInboxRanking.objects.for_team(self.team.id).count() == expected_rows
        assert self.capture.call_count == expected_rows
        output = out.getvalue()
        assert "status: ok" in output
        assert "model: gpt-6.1-terra, reasoning_effort: low, rank_top: 25" in output
        assert "next: Review the PR" in output
        assert all(f"] {report.title} (" in output for report in reports.values())

    def test_a_build_keeps_only_the_newest_rows_of_that_person(self) -> None:
        config = PersonalRankingConfig(max_rows_per_person=2)
        other_user = User.objects.create_and_join(self.organization, "other@example.com", None)
        other_team = Team.objects.create(organization=self.organization, name="Other")
        start = timezone.now()
        with time_machine.travel(start, tick=False):
            build_personal_ranking(self.team, other_user, config=config)
            build_personal_ranking(other_team, self.user, config=config)
        ranking_ids = []
        for minute in range(1, 5):
            with time_machine.travel(start + datetime.timedelta(minutes=minute), tick=False):
                ranking_ids.append(build_personal_ranking(self.team, self.user, config=config).ranking_id)

        mine = PersonalInboxRanking.objects.for_team(self.team.id).filter(user_id=self.user.id)
        assert {str(row_id) for row_id in mine.values_list("id", flat=True)} == set(ranking_ids[-2:])
        assert PersonalInboxRanking.objects.for_team(self.team.id).filter(user_id=other_user.id).count() == 1
        assert PersonalInboxRanking.objects.for_team(other_team.id).filter(user_id=self.user.id).count() == 1

    @parameterized.expand(
        [
            ("first summary with candidates", {}, True, False, ["first_summary"]),
            ("already has a list", {}, True, True, ["on_demand"]),
            ("disabled payload", {"enabled": False}, True, False, []),
            ("no candidates", {}, False, False, []),
        ]
    )
    def test_a_first_summary_builds_a_list_only_for_a_person_without_one(
        self, _name: str, payload: dict[str, Any], has_candidates: bool, has_list: bool, triggers: list[str]
    ) -> None:
        cache.delete(build_lock_key(self.team.id, self.user.id))
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        if has_candidates:
            self._setup_reports()
        self.create.return_value = _response(_answer([]))
        if has_list:
            self._build()
        queued: list[tuple[Any, ...]] = []

        with (
            patch("products.signals.backend.personal_ranking.config.read_flag_payload", return_value=payload),
            patch(
                "products.signals.backend.personal_ranking_tasks.build_personal_inbox_ranking.delay",
                side_effect=lambda *args: queued.append(args),
            ),
        ):
            start_first_summary_build(self.team.id, self.user.id)
            for args in queued:
                build_personal_inbox_ranking(*args)

        captured = [call.kwargs["properties"]["trigger"] for call in self.capture.call_args_list]
        assert captured == triggers
        assert PersonalInboxRanking.objects.for_team(self.team.id).filter(user_id=self.user.id).count() == len(triggers)
        assert cache.get(build_lock_key(self.team.id, self.user.id)) is None


class TestForMeEndpoint(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        TEST_clear_clients()
        TEST_reset_scripts()
        cache.delete(build_lock_key(self.team.id, self.user.id))
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        self.payload: dict[str, Any] = {"build_burst": 10}
        self.flag_enabled = True
        self.queued: list[tuple[Any, ...]] = []
        self.delay = MagicMock(side_effect=lambda *args: self.queued.append(args))
        for target, value in (
            (
                "products.signals.backend.personal_ranking.config.read_flag_payload",
                MagicMock(side_effect=lambda *_: self.payload),
            ),
            (
                "products.signals.backend.ranking.access.feature_enabled_or_false",
                MagicMock(side_effect=lambda *_args, **_kwargs: self.flag_enabled),
            ),
            (
                "products.signals.backend.personal_ranking.candidates.fetch_source_products_for_reports",
                MagicMock(return_value={}),
            ),
            ("products.signals.backend.personal_ranking.logic.ph_scoped_capture", MagicMock()),
            ("products.signals.backend.personal_ranking.serve.build_personal_inbox_ranking.delay", self.delay),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _url(self, **params: Any) -> str:
        query = "&".join(f"{key}={value}" for key, value in params.items())
        return f"/api/projects/{self.team.id}/signals/reports/for_me/" + (f"?{query}" if query else "")

    def _claimed_report(self, title: str, user: User | None = None) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team, title=title, summary=title, signal_count=1, total_weight=1.0, status="ready"
        )
        SignalReportAssignment.all_teams.create(
            team=self.team, report=report, actor_kind="user", actor_user=user or self.user
        )
        return report

    def _rows(self) -> int:
        return PersonalInboxRanking.objects.for_team(self.team.id).filter(user_id=self.user.id).count()

    def _get(self, **params: Any) -> dict[str, Any]:
        response = self.client.get(self._url(**params))
        assert response.status_code == 200, response.json()
        return response.json()

    def _run_builds(self) -> None:
        queued, self.queued = self.queued, []
        for args in queued:
            build_personal_inbox_ranking(*args)

    def _state(self, body: dict[str, Any]) -> tuple[bool, bool, bool]:
        return body["cached"], body["stale"], body["building"]

    def test_serves_without_building_and_queues_one_build_per_user(self) -> None:
        first = self._claimed_report("First")
        body = self._get()
        assert (body["fallback_reason"], self._state(body), self._rows()) == ("building", (False, False, True), 0)
        assert [entry["report"]["id"] for entry in body["results"]] == [str(first.id)]
        assert body["results"][0]["matched"]["needs_you"] == ["claimed"]
        assert self._get()["building"] is True
        assert len(self.queued) == 1

        self._run_builds()
        body = self._get()
        assert (body["fallback_reason"], self._state(body), self._rows()) == (
            "ai_not_approved",
            (True, False, False),
            1,
        )
        assert self.queued == []

        assert self._state(self._get(refresh="true")) == (True, False, True)
        self._run_builds()
        assert self._rows() == 2

        first.title = "First, edited"
        first.save()
        self._claimed_report("Not in the stored list")
        with (
            patch.object(personal_ranking_serve, "gather_candidates") as gather,
            self.assertNumQueries(24),
        ):
            body = self._get(max_age_minutes=60)
        assert (self._state(body), self.queued, gather.call_count) == ((True, True, False), [], 0)
        assert body["checked_at"] == body["generated_at"]
        assert self._state(self._get(max_age_minutes=0)) == (True, True, True)
        self._run_builds()
        assert (self._state(self._get()), self._rows()) == ((True, False, False), 3)

        second = self._claimed_report("Second")
        body = self._get()
        assert (self._state(body), self.queued) == ((True, False, False), [])
        assert len(body["results"]) == 2
        PersonalInboxRanking.objects.for_team(self.team.id).update(
            created_at=F("created_at") - datetime.timedelta(days=2)
        )
        assert self._state(self._get()) == (True, False, True)
        self._run_builds()
        body = self._get()
        assert str(second.id) in {entry["report"]["id"] for entry in body["results"]}

        assert self._state(self._get(focus="checkout")) == (True, True, True)
        self._run_builds()
        assert (self._state(self._get()), self.queued, self._rows()) == ((True, True, False), [], 5)

        self.delay.side_effect = build_personal_inbox_ranking
        body = self._get(refresh="true", wait_seconds=5)
        assert (self._state(body), self._rows()) == ((False, False, False), 5)

    def test_a_payload_change_rebuilds_the_list_and_another_limit_does_not(self) -> None:
        self._claimed_report("First")
        self._get()
        self._run_builds()
        assert self._state(self._get(limit=5)) == (True, False, False)

        self.payload = {**self.payload, "rank_top": 5}
        assert self._state(self._get()) == (True, True, False)
        assert self._state(self._get(max_age_minutes=0)) == (True, True, True)
        self._run_builds()
        assert (self._state(self._get()), self._rows()) == ((True, False, False), 2)

    @parameterized.expand(
        [
            ("during_gather", "gather_candidates", {"max_age_minutes": 0}, False, False),
            ("before_lock", "may_call_model", {"max_age_minutes": 0}, False, False),
            ("refresh", "gather_candidates", {"refresh": "true"}, False, False),
            ("refresh_before_lock", "may_call_model", {"refresh": "true"}, False, False),
            ("inputs_changed", "gather_candidates", {"max_age_minutes": 0}, True, True),
            ("focus", "gather_candidates", {"focus": "checkout"}, False, True),
        ]
    )
    def test_a_build_that_lands_during_the_read_answers_it(
        self, _name: str, step: str, params: dict[str, Any], change_inputs: bool, builds: bool
    ) -> None:
        self.payload = {"build_burst": 3, "builds_per_hour": 1}
        report = self._claimed_report("First")
        self._get()
        self._run_builds()
        report.title = "First, edited"
        report.save()
        self._get(max_age_minutes=0)

        real_step = getattr(personal_ranking_serve, step)

        def build_lands(*args: Any, **kwargs: Any) -> Any:
            self._run_builds()
            if change_inputs:
                report.title = "First, edited again"
                report.save()
            return real_step(*args, **kwargs)

        with patch.object(personal_ranking_serve, step, side_effect=build_lands):
            body = self._get(**params)

        assert (self._rows(), len(self.queued)) == (2, int(builds))
        assert self._state(body) == ((True, True, True) if builds else (True, False, False))
        self._run_builds()
        # A read that queued no build spent no bucket, so the burst still has one build left.
        assert self._get(refresh="true")["building"] is not builds

    @parameterized.expand(
        [
            ("resolved", lambda report: SignalReport.objects.filter(id=report.id).update(status="resolved")),
            ("suppressed", lambda report: SignalReport.objects.filter(id=report.id).update(status="suppressed")),
            ("claim_released", lambda report: SignalReportAssignment.all_teams.filter(report=report).delete()),
        ]
    )
    def test_a_plain_read_drops_a_report_that_is_no_longer_theirs(
        self, _name: str, leave: Callable[[SignalReport], Any]
    ) -> None:
        kept = self._claimed_report("Kept")
        left = self._claimed_report("Left")
        self._get()
        self._run_builds()
        leave(left)

        with patch.object(personal_ranking_serve, "gather_candidates") as gather:
            body = self._get()

        assert [entry["report"]["id"] for entry in body["results"]] == [str(kept.id)]
        assert (body["stale"], gather.call_count) == (True, 0)

    def test_throttled_build_serves_the_stored_list_or_the_inbox_order(self) -> None:
        self.payload = {"build_burst": 1, "builds_per_hour": 1}
        first = self._claimed_report("First")
        self._get()
        self._run_builds()

        assert (self._state(self._get(refresh="true")), self.queued) == ((True, False, False), [])
        self._claimed_report("Second")
        first.title = "First, edited"
        first.save()
        body = self._get()
        assert (self._state(body), self._rows()) == ((True, True, False), 1)
        assert [entry["report"]["id"] for entry in body["results"]] == [str(first.id)]

        PersonalInboxRanking.objects.for_team(self.team.id).all().delete()
        body = self._get()
        assert (body["fallback_reason"], body["building"], len(body["results"])) == ("rate_limited", False, 2)

    def test_failed_enqueue_serves_the_inbox_order_and_frees_the_lock(self) -> None:
        self._claimed_report("First")
        self.delay.side_effect = RuntimeError("broker down")

        body = self._get()

        assert (body["fallback_reason"], body["building"], len(body["results"])) == ("build_failed", False, 1)
        self.delay.side_effect = lambda *args: self.queued.append(args)
        assert self._get()["building"] is True

    def test_daily_cap_holds_across_hours(self) -> None:
        self.payload = {"build_burst": 10, "builds_per_hour": 120, "builds_per_day": 2}
        self._claimed_report("First")
        with time_machine.travel(timezone.now(), tick=False) as traveller:
            self._get()
            self._run_builds()
            self._get(refresh="true")
            self._run_builds()

            traveller.shift(datetime.timedelta(hours=3))
            assert (self._get(refresh="true")["building"], self._rows()) == (False, 2)

            traveller.shift(datetime.timedelta(hours=9))
            assert self._get(refresh="true")["building"] is True

    def test_shared_daily_limit_counts_only_builds_that_call_the_model(self) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.payload = {"build_burst": 10, "max_builds_per_day": 1}
        other = User.objects.create_and_join(self.organization, "other@example.com", "password")
        third = User.objects.create_and_join(self.organization, "third@example.com", "password")
        ready = ActivitySummaryView(status=ActivitySummaryStatus.READY, version=1)
        summaries = {self.user.id: ready, other.id: ready, third.id: None}
        for user in (self.user, other, third):
            self._claimed_report(f"Claimed by {user.email}", user)

        with patch(
            "products.signals.backend.personal_ranking.logic.get_summary",
            side_effect=lambda _team, user_id: summaries[user_id],
        ):
            assert self._get()["building"] is True
            self.client.force_login(other)
            body = self._get()
            assert (body["fallback_reason"], body["building"]) == ("rate_limited", False)
            self.client.force_login(third)
            assert self._get()["building"] is True

        assert [args[1] for args in self.queued] == [self.user.id, third.id]

    def test_an_old_list_is_served_at_once_and_checked_in_the_background(self) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self._claimed_report("First")
        with time_machine.travel(timezone.now(), tick=False) as traveller:
            self._get()
            self._run_builds()
            traveller.shift(datetime.timedelta(hours=2))
            with patch.object(personal_ranking_serve, "gather_candidates") as gather:
                body = self._get()
            assert (self._state(body), gather.call_count, [args[-1] for args in self.queued]) == (
                (True, False, True),
                0,
                [True],
            )
            self._run_builds()
            body = self._get()

        assert (self._state(body), self.queued, self._rows()) == ((True, False, False), [], 1)
        assert body["checked_at"] > body["generated_at"]

    def test_another_user_never_reads_your_list(self) -> None:
        self._get()
        self._run_builds()
        other = User.objects.create_and_join(self.organization, "other@example.com", "password")
        self.client.force_login(other)

        body = self._get()
        self._run_builds()

        assert (body["cached"], body["fallback_reason"]) == (False, "building")
        assert PersonalInboxRanking.objects.for_team(self.team.id).filter(user_id=other.id).count() == 1

    @parameterized.expand([("flag_off", {"enabled": True}, False), ("kill_switch", {"enabled": False}, True)])
    def test_unavailable(self, _name: str, payload: dict[str, Any], flag_enabled: bool) -> None:
        self.payload, self.flag_enabled = payload, flag_enabled
        response = self.client.get(self._url())
        if flag_enabled:
            assert response.status_code == 200
            assert (response.json()["status"], response.json()["results"]) == ("unavailable", [])
        else:
            assert response.status_code == 404
        assert (self._rows(), self.queued) == (0, [])


class TestPersonalRankingState(SimpleTestCase):
    @parameterized.expand(
        [
            ("real", "ok", True, 2, "real"),
            ("one_report", "ok", True, 1, "one_report"),
            ("not_personalized", "ok", False, 3, "not_personalized"),
            ("ok_without_reports", "ok", True, 0, "empty"),
            ("empty", "empty", False, 0, "empty"),
            ("fallback", "fallback", False, 3, "fallback"),
        ]
    )
    def test_only_an_ok_personalized_row_of_two_reports_is_real(
        self, _name: str, status: str, personalized: bool, size: int, expected: str
    ) -> None:
        assert personal_ranking_state(status, personalized, size) == expected


class TestPersonalListSort(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.payload: dict[str, Any] = {}
        self.flag_enabled = True
        self.analytics = MagicMock()
        self.analytics.get_feature_flag.return_value = "control"
        self.gather = MagicMock()
        self.delay = MagicMock()
        for target, value in (
            (
                "products.signals.backend.personal_ranking.config.read_flag_payload",
                MagicMock(side_effect=lambda *_: self.payload),
            ),
            (
                "products.signals.backend.ranking.access.feature_enabled_or_false",
                MagicMock(side_effect=lambda *_args, **_kwargs: self.flag_enabled),
            ),
            ("products.signals.backend.ranking.inbox_sort.posthoganalytics", self.analytics),
            ("products.signals.backend.personal_ranking.serve.gather_candidates", self.gather),
            ("products.signals.backend.personal_ranking.serve.build_personal_inbox_ranking.delay", self.delay),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.reports = [
            SignalReport.objects.create(
                team=self.team, title=f"R{index}", summary="s", signal_count=1, total_weight=1.0, status="ready"
            )
            for index in range(5)
        ]

    def _ranking(self, ranked: list[SignalReport], folded: list[SignalReport], **kwargs: Any) -> PersonalInboxRanking:
        defaults: dict[str, Any] = {
            "personalized": True,
            "result": {
                "ranked": [
                    {
                        "report_id": str(report.id),
                        "rank": rank,
                        "tier": "top" if rank == 1 else "later",
                        "reason": f"reason {report.title}",
                        "ranked_by": "llm" if rank == 1 else "model",
                    }
                    # Stored out of rank order, so the read must sort by rank.
                    for rank, report in reversed(list(enumerate(ranked, start=1)))
                ],
                "folded": [
                    {"report_id": str(report.id), "into_report_id": str(ranked[0].id), "reason": "same"}
                    for report in folded
                ],
            },
        }
        return PersonalInboxRanking.objects.create(
            team=self.team,
            input_hash="h",
            model="m",
            prompt_version=1,
            **{"user": self.user, "status": "ok", **defaults, **kwargs},
        )

    def _variants(self, variants: dict[str, str]) -> None:
        self.analytics.get_feature_flag.side_effect = lambda flag, *_args, **_kwargs: variants.get(flag)

    def _list(self, **params: Any) -> dict[str, Any]:
        query = "&".join(f"{key}={value}" for key, value in {"status": "ready", **params}.items())
        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/?{query}")
        assert response.status_code == 200, response.json()
        return response.json()

    def _ids(self, body: dict[str, Any]) -> list[str]:
        return [row["id"] for row in body["results"]]

    def test_puts_ranked_then_folded_reports_first_without_a_build_or_an_exposure(self) -> None:
        r0, r1, r2, r3, r4 = self.reports
        row = self._ranking([r2, r0], [r1])
        base = self._ids(self._list(sort="recommended"))
        self.analytics.reset_mock()

        body = self._list(sort="personal")

        rest = [report_id for report_id in base if report_id not in {str(r2.id), str(r0.id), str(r1.id)}]
        assert self._ids(body) == [str(r2.id), str(r0.id), str(r1.id), *rest]
        assert (body["ranker"], body["ranking_id"], body["ranking_pill"]) == ("personal", str(row.id), False)
        assert [row["inbox_merge_key"] for row in body["results"]] == [0, 1, 2, 3 + 5, 3 + 5]
        assert [(row["personal_tier"], row["personal_reason"]) for row in body["results"][:3]] == [
            ("top", "reason R2"),
            (None, None),
            (None, None),
        ]
        assert self.analytics.get_feature_flag.call_args.kwargs["send_feature_flag_events"] is False
        assert (self.gather.call_count, self.delay.call_count) == (0, 0)
        assert PersonalInboxRanking.objects.for_team(self.team.id).count() == 1

    @parameterized.expand(
        [
            ("no_row", None, True, True),
            ("empty_row", {"ranked": [], "folded": []}, True, True),
            ("not_personalized", "not_personalized", True, True),
            ("flag_off", "ranked", False, True),
            ("disabled", "ranked", True, False),
        ]
    )
    def test_falls_back_to_the_recommended_order(
        self, _name: str, row: Any, flag_enabled: bool, config_enabled: bool
    ) -> None:
        r0, r1, *_ = self.reports
        if row == "not_personalized":
            self._ranking([r0], [r1], personalized=False)
        elif row == "ranked":
            self._ranking([r0], [r1])
        elif row is not None:
            self._ranking([], [], result=row)
        base = self._list(sort="recommended")
        self.flag_enabled = flag_enabled
        self.payload = {} if config_enabled else {"enabled": False}

        body = self._list(sort="personal")

        assert self._ids(body) == self._ids(base)
        assert (body["ranker"], body["ranking_id"]) == ("priority", None)
        assert [row["inbox_merge_key"] for row in body["results"]] == [
            row["inbox_merge_key"] for row in base["results"]
        ]
        assert all(row["personal_reason"] is None for row in body["results"])
        assert (self.gather.call_count, self.delay.call_count) == (0, 0)

    def test_teammate_scope_reads_the_teammate_ranking(self) -> None:
        r0, r1, r2, r3, _ = self.reports
        teammate = User.objects.create(email="teammate@example.com")
        OrganizationMembership.objects.create(user=teammate, organization=self.organization)
        for report in (r0, r1, r2, r3):
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                content=json.dumps([{"user_uuid": str(teammate.uuid)}]),
            )
        self._ranking([r0, r1], [])
        row = self._ranking([r3, r2], [r1], user=teammate)

        body = self._list(sort="personal", scope="teammate", teammate_uuid=teammate.uuid)

        assert self._ids(body)[:3] == [str(r3.id), str(r2.id), str(r1.id)]
        assert set(self._ids(body)) == {str(r0.id), str(r1.id), str(r2.id), str(r3.id)}
        assert (body["ranker"], body["ranking_id"]) == ("personal", str(row.id))
        assert (body["results"][0]["personal_tier"], body["results"][0]["personal_reason"]) == ("top", "reason R3")
        assert (self.gather.call_count, self.delay.call_count) == (0, 0)

    def test_teammate_scope_outside_the_organization_falls_back_to_the_recommended_order(self) -> None:
        r0, r1, r2, r3, r4 = self.reports
        outsider = User.objects.create(email="outsider@example.com")
        self._ranking([r0, r1, r2, r3], [r4])
        self._ranking([r1, r0], [], user=outsider)
        # The personal arm falls back to the priority order, not to the ranker of the pills arm.
        self._variants({PERSONAL_RECOMMENDED_FLAG: "personal", RECOMMENDED_INBOX_SORT_FLAG: "action_pills"})

        body = self._list(sort="personal", scope="teammate", teammate_uuid=outsider.uuid)

        assert (body["ranker"], body["ranking_id"]) == ("priority", None)
        assert (self.gather.call_count, self.delay.call_count) == (0, 0)

    @parameterized.expand([("personal",), ("recommended",)])
    def test_later_pages_keep_the_order_of_the_first_page_after_a_rebuild(self, sort: str) -> None:
        r0, r1, r2, r3, r4 = self.reports
        self._variants({PERSONAL_RECOMMENDED_FLAG: "personal"})
        old = self._ranking([r0, r1, r2, r3], [r4])
        first = self._list(sort=sort, limit=2)
        assert (self._ids(first), first["ranking_id"]) == ([str(r0.id), str(r1.id)], str(old.id))
        self._ranking([r3, r2, r1, r0], [r4])

        second = self._list(sort=sort, limit=2, offset=2, ranking_id=first["ranking_id"])
        assert (self._ids(second), second["ranking_id"]) == ([str(r2.id), str(r3.id)], str(old.id))

        old.delete()
        latest = self._list(sort=sort, limit=2, offset=2, ranking_id=first["ranking_id"])
        assert self._ids(latest) == [str(r1.id), str(r0.id)]

    @parameterized.expand(
        [
            ("full_list", 4, "personal", "personal", [True]),
            ("full_list_in_control", 4, "control", "priority", [True]),
            # A rebuild can make an exposed person's list shorter, and they must keep their arm.
            ("short_list", 3, "personal", "personal", [False]),
            ("short_list_in_control", 3, "control", "priority", [False]),
            ("no_list", None, "personal", "priority", []),
        ]
    )
    def test_recommended_exposes_the_personal_test_only_with_a_full_list(
        self, _name: str, ranked: int | None, variant: str, ranker: str, exposures: list[bool]
    ) -> None:
        r0, r1, r2, r3, r4 = self.reports
        listed = [r3, r1, r4, r0][:ranked]
        row = self._ranking(listed, [r2]) if ranked is not None else None
        base = self._ids(self._list(sort="priority"))
        self._variants({PERSONAL_RECOMMENDED_FLAG: variant, RECOMMENDED_INBOX_SORT_FLAG: "control"})

        body = self._list(sort="recommended")

        if ranker == "personal":
            assert row is not None
            assert self._ids(body)[: len(listed) + 1] == [str(report.id) for report in [*listed, r2]]
            assert (body["ranker"], body["ranking_id"], body["ranking_pill"]) == ("personal", str(row.id), True)
            assert body["results"][0]["personal_reason"] == "reason R3"
        else:
            assert self._ids(body) == base
            assert (body["ranker"], body["ranking_id"], body["ranking_pill"]) == ("priority", None, False)
        assert [
            call.kwargs["send_feature_flag_events"]
            for call in self.analytics.get_feature_flag.call_args_list
            if call.args[0] == PERSONAL_RECOMMENDED_FLAG
        ] == exposures

    @parameterized.expand([("priority", {}), ("personal", {}), ("personal", {"scope": "teammate"})])
    def test_first_page_reports_the_viewer_ranking_status(self, sort: str, params: dict[str, Any]) -> None:
        r0, r1, r2, *_ = self.reports
        teammate = User.objects.create(email="teammate@example.com")
        OrganizationMembership.objects.create(user=teammate, organization=self.organization)
        with time_machine.travel("2026-03-01T12:00:00Z", tick=False):
            row = self._ranking([r0, r1], [r2], status="fallback", personalized=False, fallback_reason="timeout")
        PersonalInboxRanking.objects.filter(id=row.id).update(
            checked_at=datetime.datetime(2026, 3, 1, 13, 30, tzinfo=datetime.UTC)
        )
        self._ranking([r2, r1], [], user=teammate)
        if params:
            params = {**params, "teammate_uuid": teammate.uuid}

        with time_machine.travel("2026-03-01T14:00:00Z", tick=False):
            first = self._list(sort=sort, limit=2, **params)
            later = self._list(sort=sort, limit=2, offset=2, **params)

        assert first["personal_ranking_status"] == {
            "state": "fallback",
            "size": 3,
            "age_minutes": 120,
            "checked_age_minutes": 30,
            "fallback_reason": "timeout",
        }
        assert later["personal_ranking_status"] is None
        assert (self.gather.call_count, self.delay.call_count) == (0, 0)

    @parameterized.expand([("flag_off", False, None), ("no_row", True, "none")])
    def test_ranking_status_without_a_ranking(self, _name: str, flag_enabled: bool, state: str | None) -> None:
        self.flag_enabled = flag_enabled

        status = self._list(sort="priority")["personal_ranking_status"]

        if state is None:
            assert status is None
        else:
            assert status == {
                "state": state,
                "size": None,
                "age_minutes": None,
                "checked_age_minutes": None,
                "fallback_reason": None,
            }

    def test_ranking_status_adds_one_query_to_the_first_page(self) -> None:
        r0, r1, *_ = self.reports
        self._ranking([r0, r1], [])
        self._list(sort="priority")

        def queries(payload: dict[str, Any]) -> int:
            self.payload = payload
            with CaptureQueriesContext(connection) as captured:
                self._list(sort="priority")
            return len(captured)

        assert queries({}) - queries({"enabled": False}) == 1
