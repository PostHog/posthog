import json
import datetime
import dataclasses
from io import StringIO
from types import SimpleNamespace
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase
from django.utils import timezone

import httpx
from openai import APITimeoutError
from parameterized import parameterized

from posthog.models import User
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
from products.signals.backend.personal_ranking.candidates import Candidate
from products.signals.backend.personal_ranking.config import (
    CandidatePool,
    PersonalRankingConfig,
    ReasonLimits,
    parse_config,
)
from products.signals.backend.personal_ranking.logic import BUILT_EVENT, build_personal_ranking
from products.signals.backend.personal_ranking.prompt import render_person, user_message
from products.signals.backend.personal_ranking.validation import MalformedRankingError, validate_ranking
from products.signals.backend.personal_ranking_tasks import build_lock_key, build_personal_inbox_ranking
from products.signals.backend.ranking.report_predictions import OutcomePrediction, ReportPredictions

REFS = ["c1", "c2", "c3", "c4"]
MODEL_REASONS = {ref: f"model {ref}" for ref in REFS}
LIMITS = ReasonLimits(top=40, worth_a_look=30, later=20)


def _entry(ref: str, rank: Any, tier: str = "worth_a_look", reason: str = "matches", next_step: str | None = None):
    return {"ref": ref, "rank": rank, "tier": tier, "reason": reason, "matched": None, "next_step": next_step}


def _answer(ranked: list[dict], folded: list[dict] | None = None) -> str:
    return json.dumps({"ranked": ranked, "folded": folded or []})


def _validate(content: str | None, limit: int = 2):
    return validate_ranking(
        content, refs=REFS, model_reasons=MODEL_REASONS, limit=limit, reason_limits=LIMITS, next_step_max_chars=12
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
        ]
    )
    def test_order_covers_every_unfolded_candidate(
        self, _name: str, ranked: list[dict], folded: list[dict], expected_refs: list[str], expected_counts: dict
    ) -> None:
        result = _validate(_answer(ranked, folded))

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

        message = user_message(render_person(summary, config), candidates, focus=None, now=timezone.now(), limit=25)

        assert not any(report_id in message for report_id in ids)
        assert "\nc1 | P2 | ready | PR open" in message
        assert "\nc2 | P2 | ready | PR open" in message
        assert "model: action 0.42 (lift 7.9)" in message
        assert message.count("model:") == 1
        assert "p" * 100 in message and "p" * 101 not in message
        assert "- Checkout (mode build, strength strong, last seen 2026-10-29)" in message


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
                "default_limit_within_max_limit",
                {"default_limit": 40, "max_limit": 30},
                PersonalRankingConfig(default_limit=30, max_limit=30),
            ),
            (
                "pools_in_order_with_default_names_and_large_values_capped",
                {
                    "pools": [
                        {"source": "priority", "size": 5, "lowest_priority": "P0", "window_days": 1000},
                        {"source": "assigned", "size": 0},
                        {"source": "scored", "size": 500, "head": "fixed", "has_pr": True, "actionable_only": True},
                    ]
                },
                PersonalRankingConfig(
                    pools=(
                        CandidatePool(name="priority", source="priority", size=5, lowest_priority="P0", window_days=90),
                        CandidatePool(name="assigned", source="assigned", size=0),
                        CandidatePool(
                            name="scored_fixed",
                            source="scored",
                            size=100,
                            head="fixed",
                            has_pr=True,
                            actionable_only=True,
                        ),
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
                        {"source": "scored", "size": 5},
                        {"source": "assigned", "size": 5, "head": "open"},
                        {"source": "assigned", "size": True},
                        {"source": "assigned", "size": -1},
                        {"source": "priority", "size": 5, "lowest_priority": "urgent"},
                        {"source": "priority", "size": 5, "has_pr": "yes"},
                        {"source": "assigned", "size": 5, "name": "Has Spaces"},
                    ]
                },
                PersonalRankingConfig(pools=(CandidatePool(name="mine", source="assigned", size=5),)),
            ),
            ("no_valid_pool_keeps_the_defaults", {"pools": [{"source": "scored", "size": 5}]}, PersonalRankingConfig()),
            ("pools_not_a_list", {"pools": {"source": "assigned", "size": 5}}, PersonalRankingConfig()),
            (
                "pools_past_the_maximum_drop",
                {"pools": [{"source": "assigned", "size": 1, "name": f"p{index}"} for index in range(12)]},
                PersonalRankingConfig(
                    pools=tuple(CandidatePool(name=f"p{index}", source="assigned", size=1) for index in range(10))
                ),
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
        for target, value in (
            ("products.signals.backend.personal_ranking.logic.build_openai_client", MagicMock(return_value=self.llm)),
            ("products.signals.backend.personal_ranking.logic.ph_scoped_capture", scoped_capture),
            (
                "products.signals.backend.personal_ranking.candidates.fetch_source_products_for_reports",
                MagicMock(return_value={}),
            ),
            (
                "products.signals.backend.ranking.inbox_sort.posthoganalytics.get_feature_flag",
                MagicMock(return_value="action"),
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

    @parameterized.expand([("no_summary", False), ("ready_summary", True)])
    def test_ranks_every_candidate_and_stores_one_row(self, _name: str, with_summary: bool) -> None:
        reports = self._setup_reports()
        summary = (
            ActivitySummaryView(status=ActivitySummaryStatus.READY, headline="Works on checkout", version=7)
            if with_summary
            else None
        )

        def answer(**kwargs: Any) -> SimpleNamespace:
            prompt = kwargs["messages"][1]["content"]
            refs = [line.split(" | ")[0] for line in prompt.splitlines() if line.startswith("c") and " | " in line]
            ranked = [_entry(ref, len(refs) - index, reason=f"reason {ref}") for index, ref in enumerate(refs)]
            return _response(_answer([*ranked[:-1], _entry("c99", 1)]))

        self.create.side_effect = answer
        with patch("products.signals.backend.personal_ranking.logic.get_summary", return_value=summary):
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
        assert row.personalized is with_summary
        assert row.activity_summary_version == (7 if with_summary else None)
        assert row.tokens_in == 1000
        needs_you = {candidate.report_id: candidate.needs_you for candidate in build.candidates}
        assert needs_you == {
            str(reports["waiting"].id): ("waiting_on_input",),
            str(reports["reviewing"].id): ("suggested_reviewer",),
            str(reports["claimed"].id): ("claimed",),
        }
        assert "# Focus\ncheckout bugs" in self.create.call_args.kwargs["messages"][1]["content"]

        self.capture.assert_called_once()
        event = self.capture.call_args.kwargs
        assert event["event"] == BUILT_EVENT
        assert event["properties"]["ranking_id"] == str(row.id)
        assert event["properties"]["personalized"] is with_summary
        serialized = json.dumps(event["properties"])
        assert "Waiting" not in serialized and "reason c" not in serialized and "checkout" not in serialized

    @parameterized.expand(
        [
            ("timeout", APITimeoutError(request=httpx.Request("POST", "https://example.com")), "timeout"),
            ("api_error", RuntimeError("gateway down"), "llm_error"),
            ("malformed", _response("not json"), "malformed_output"),
            ("truncated", _response(_answer([_entry("c1", 1)]), finish_reason="length"), "truncated_output"),
            ("ai_not_approved", None, "ai_not_approved"),
        ]
    )
    def test_model_failure_falls_back_to_model_order(self, _name: str, outcome: Any, fallback_reason: str) -> None:
        self._setup_reports()
        if outcome is None:
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
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
        assert len(row.result["ranked"]) == 3
        if outcome is None:
            self.create.assert_not_called()

    @parameterized.expand(
        [
            ("can_see_scores", True, True, True),
            ("cannot_see_ranking", False, True, False),
            ("no_scores_as_in_eu", True, False, False),
        ]
    )
    def test_ranking_pools_join_only_with_access_and_scores(
        self, _name: str, staff: bool, scored: bool, expect_pool: bool
    ) -> None:
        self.user.is_staff = staff
        self.user.save(update_fields=["is_staff"])
        unowned = self._report("Unowned actionable")
        if scored:
            self._score(unowned, action=0.8)
        self.create.return_value = _response(_answer([_entry("c1", 1)]))

        with patch("products.signals.backend.ranking.access.feature_enabled_or_false", return_value=False):
            build = self._build(dry_run=True)

        pools = {candidate.report_id: candidate.pools for candidate in build.candidates}
        if expect_pool:
            assert pools == {str(unowned.id): ("actionable", "new")}
            assert build.candidates[0].predictions is not None
        else:
            assert pools == {}
            assert build.status == "empty"
            self.create.assert_not_called()

    @parameterized.expand([("can_see_scores", True), ("cannot_see_ranking", False)])
    def test_configured_pools_keep_their_order_and_names(self, _name: str, staff: bool) -> None:
        self.user.is_staff = staff
        self.user.save(update_fields=["is_staff"])
        urgent = self._prioritize(self._report("Urgent and unscored"), "P1")
        self._prioritize(self._report("Not urgent"), "P3")
        scored = self._report("Scored")
        self._score(scored, action=0.8)
        claimed = self._report("Claimed", status=SignalReport.Status.IN_PROGRESS)
        SignalReportAssignment.all_teams.create(team=self.team, report=claimed, actor_kind="user", actor_user=self.user)
        self.create.return_value = _response(_answer([_entry("c1", 1)]))
        config = PersonalRankingConfig(
            pools=(
                CandidatePool(name="assigned", source="assigned", size=0),
                CandidatePool(name="scored_action", source="scored", size=5, head="action"),
                CandidatePool(name="urgent", source="priority", size=5),
            )
        )

        with patch("products.signals.backend.ranking.access.feature_enabled_or_false", return_value=False):
            build = build_personal_ranking(self.team, self.user, config=config, dry_run=True)

        pools = [(candidate.report_id, candidate.pools) for candidate in build.candidates]
        expected = [(str(urgent.id), ("urgent",))]
        if staff:
            expected = [(str(scored.id), ("scored_action",)), *expected]
        assert pools == expected

    @parameterized.expand([("dry_run", True, 0), ("stored", False, 1)])
    def test_command(self, _name: str, dry_run: bool, expected_rows: int) -> None:
        reports = self._setup_reports()
        self.create.return_value = _response(_answer([_entry("c1", 1, tier="top", next_step="Review the PR")]))
        out = StringIO()

        with patch("products.signals.backend.personal_ranking.logic.read_config", return_value=PersonalRankingConfig()):
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
        assert "next: Review the PR" in output
        assert all(f"] {report.title} (" in output for report in reports.values())


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

    def _claimed_report(self, title: str) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team, title=title, summary=title, signal_count=1, total_weight=1.0, status="ready"
        )
        SignalReportAssignment.all_teams.create(team=self.team, report=report, actor_kind="user", actor_user=self.user)
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
        assert self._state(self._get()) == (True, True, True)
        self._run_builds()
        assert (self._state(self._get()), self._rows()) == ((True, False, False), 3)

        second = self._claimed_report("Second")
        assert self._state(self._get()) == (True, True, True)
        self._run_builds()
        body = self._get()
        assert {entry["report"]["id"] for entry in body["results"]} == {str(first.id), str(second.id)}

        assert self._state(self._get(focus="checkout")) == (True, True, True)
        self._run_builds()
        assert (self._state(self._get()), self._rows()) == ((True, True, True), 5)
        self._run_builds()

        self.delay.side_effect = build_personal_inbox_ranking
        body = self._get(refresh="true", wait_seconds=5)
        assert (self._state(body), self._rows()) == ((False, False, False), 7)

    def test_throttled_build_serves_the_stored_list_or_the_inbox_order(self) -> None:
        self.payload = {"build_burst": 1, "builds_per_hour": 1}
        first = self._claimed_report("First")
        self._get()
        self._run_builds()

        assert (self._state(self._get(refresh="true")), self.queued) == ((True, False, False), [])
        self._claimed_report("Second")
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
