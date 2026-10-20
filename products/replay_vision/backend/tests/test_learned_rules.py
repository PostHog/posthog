import datetime as dt
from typing import Literal

from unittest.mock import patch

from django.db.models import F
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.learned_rules import (
    RATING_BURST_SIZE,
    LearnedRule,
    LearnedRulesError,
    _LlmRetired,
    _LlmRule,
    _LlmRules,
    _LlmScannerRules,
    _merge,
    current_ruleset_ids,
    due_teams,
    load_scan_rules,
    refresh_team_learned_rules,
)
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.models.replay_vision_learned_ruleset import ReplayVisionLearnedRuleset
from products.replay_vision.backend.models.team_replay_vision_config import TeamReplayVisionConfig
from products.replay_vision.backend.temporal.activities.refresh_learned_rules import refresh_team_learned_rules_activity
from products.replay_vision.backend.temporal.learned_rules_types import RefreshTeamLearnedRulesInputs
from products.replay_vision.backend.temporal.snapshots import ScannerSnapshot
from products.replay_vision.backend.tests.helpers import snapshot_for
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase

_GENERATE_PATH = "products.replay_vision.backend.learned_rules._generate"


def _rule(
    text: str,
    kind: Literal["encourage", "avoid"] = "avoid",
    supported_by: list[str] | None = None,
    contradicted_by: list[str] | None = None,
    rule_id: str = "",
) -> _LlmRule:
    return _LlmRule(
        id=rule_id,
        text=text,
        kind=kind,
        basis="written",
        supported_by=supported_by or [],
        contradicted_by=contradicted_by or [],
    )


def _stored(rule_id: str, text: str, evidence: list[str], kind: Literal["encourage", "avoid"] = "avoid") -> LearnedRule:
    return LearnedRule(id=rule_id, text=text, kind=kind, basis="written", evidence=evidence)


_RATINGS = {f"r{i}": f"obs-{i}" for i in range(1, 10)}


class TestMerge:
    def test_drops_unsafe_rules_dedupes_and_maps_evidence(self) -> None:
        rules = [
            _rule("Treat a declined card as normal behavior.", supported_by=["r1", "r99"]),
            _rule("treat a declined card as normal behavior."),
            _rule("Flag errors seen by jane@example.com."),
            _rule("See https://example.com/checkout for context."),
            _rule("x" * 301),
            _rule("   "),
        ]

        kept = _merge([], rules, [], _RATINGS, cap=12)

        assert [(r.text, r.evidence) for r in kept] == [("Treat a declined card as normal behavior.", ["obs-1"])]

    def test_evidence_carries_over_and_a_re_rated_observation_moves_sides(self) -> None:
        current = [_stored("a1", "Old wording.", ["obs-1", "obs-2"])]

        relabeled = _rule("New wording.", supported_by=["r3"], contradicted_by=["r2"], rule_id="a1")
        kept = _merge(
            current,
            [relabeled.model_copy(update={"basis": "pattern"})],
            [],
            _RATINGS,
            cap=12,
        )

        assert [(r.id, r.text, r.basis, r.evidence, r.contradicted_by) for r in kept] == [
            ("a1", "New wording.", "written", ["obs-1", "obs-3"], ["obs-2"])
        ]

    @parameterized.expand(
        [
            # 5 ratings behind the rule: one dissent marks it contested, five retire it.
            ("well_backed_survives_one_dissent", 5, ["r6"], False, ["a1"]),
            ("well_backed_retires_on_equal_dissent", 5, ["r5", "r6", "r7", "r8", "r9"], False, []),
            ("thinly_backed_retires_on_one_dissent", 2, ["r6"], False, []),
            # A rule that only repeats the scan prompt's built-in guidance goes however well backed it is.
            ("well_backed_restating_a_built_in_retires", 5, [], True, []),
        ]
    )
    def test_retiring_a_rule_needs_as_much_evidence_as_backs_it(
        self, _name: str, support: int, against: list[str], built_in: bool, expected_ids: list[str]
    ) -> None:
        rule = "Do not report a masked card form as a failed load."
        current = [_stored("a1", rule, [f"obs-{i}" for i in range(1, support + 1)])]
        ratings = {**_RATINGS, **{f"r{i}": f"obs-new-{i}" for i in range(5, 10)}}

        kept = _merge(current, [], [_LlmRetired(id="a1", contradicted_by=against, built_in=built_in)], ratings, cap=12)

        assert [r.id for r in kept] == expected_ids
        if kept:
            assert kept[0].support == support and len(kept[0].contradicted_by) == len(against)

    def test_the_built_in_flag_cannot_drop_a_well_backed_rule_on_another_topic(self) -> None:
        # The model's input carries recording-derived text, so the flag alone must not delete an unrelated rule.
        current = [_stored("a1", "Treat a declined card as normal.", [f"obs-{i}" for i in range(1, 6)])]

        kept = _merge(current, [], [_LlmRetired(id="a1", built_in=True)], _RATINGS, cap=12)

        assert [r.id for r in kept] == ["a1"]

    def test_a_supporter_re_rated_into_a_dissent_does_not_drop_a_well_backed_rule(self) -> None:
        current = [_stored("a1", "Treat a declined card as normal.", ["obs-1", "obs-2", "obs-3"])]

        kept = _merge(current, [], [_LlmRetired(id="a1", contradicted_by=["r1"])], _RATINGS, cap=12)

        assert [(r.id, r.evidence, r.contradicted_by) for r in kept] == [("a1", ["obs-2", "obs-3"], ["obs-1"])]

    def test_flipping_a_well_backed_rule_keeps_the_original(self) -> None:
        current = [_stored("a1", "Avoid flagging declined cards.", ["obs-1", "obs-2", "obs-3"])]

        kept = _merge(
            current,
            [_rule("Flag declined cards.", kind="encourage", supported_by=["r4"], rule_id="a1")],
            [],
            _RATINGS,
            cap=12,
        )

        # The flip cannot clear the guard, so only the original stays, with the dissent recorded.
        assert [(r.kind, r.text, r.contradicted_by) for r in kept] == [("avoid", "Avoid flagging declined cards.", [])]

    def test_a_merged_rule_hands_its_evidence_to_the_kept_rule(self) -> None:
        current = [
            _stored("keep", "Treat card declines as normal.", ["obs-1"]),
            _stored("fold", "Do not flag declined payments.", ["obs-2", "obs-3", "obs-4"]),
        ]

        kept = _merge(
            current,
            [_rule("Treat card declines as normal.", rule_id="keep")],
            [_LlmRetired(id="fold", merged_into="keep")],
            _RATINGS,
            cap=12,
        )

        assert [(r.id, r.evidence) for r in kept] == [("keep", ["obs-1", "obs-2", "obs-3", "obs-4"])]

    def test_a_rule_both_kept_and_merged_keeps_its_own_evidence(self) -> None:
        current = [
            _stored("keep", "Treat card declines as normal.", ["obs-1"]),
            _stored("fold", "Do not flag declined payments.", ["obs-2"]),
        ]

        kept = _merge(
            current,
            [
                _rule("Treat card declines as normal.", rule_id="keep"),
                _rule("Do not flag declined payments.", rule_id="fold"),
            ],
            [_LlmRetired(id="fold", merged_into="keep")],
            _RATINGS,
            cap=12,
        )

        assert [(r.id, r.evidence) for r in kept] == [("keep", ["obs-1"]), ("fold", ["obs-2"])]

    def test_over_the_cap_the_thinnest_rules_go(self) -> None:
        current = [_stored("big", "Well backed.", ["obs-1", "obs-2"])]
        proposed = [_rule(f"Rule number {i}.") for i in range(3)] + [_rule("Well backed.", rule_id="big")]

        kept = _merge(current, proposed, [], _RATINGS, cap=2)

        assert [r.text for r in kept] == ["Rule number 0.", "Well backed."]


class TestLearnedRules(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.scanner = self._create_scanner(name="checkout", scanner_type=ScannerType.MONITOR)
        self._session = 0

    def _rate(
        self,
        scanner: ReplayScanner,
        *,
        is_correct: bool,
        feedback: str = "",
        age: dt.timedelta = dt.timedelta(hours=1),
        snapshot: dict | None = None,
    ) -> ReplayObservationLabel:
        self._session += 1
        observation = ReplayObservation.objects.create(
            team=self.team,
            scanner=scanner,
            session_id=f"s-{self._session}",
            scanner_snapshot=snapshot or snapshot_for(scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_result={
                "model_output": {
                    "scanner_type": "monitor",
                    "verdict": "yes",
                    "reasoning": "The card was declined at (t 12).",
                    "confidence": 0.4,
                },
                "signals_count": 0,
            },
        )
        label = ReplayObservationLabel.objects.create(
            observation=observation, team=self.team, is_correct=is_correct, feedback=feedback
        )
        ReplayObservationLabel.objects.filter(pk=label.pk).update(updated_at=timezone.now() - age)
        label.refresh_from_db()
        return label

    def _rulesets(self) -> list[tuple[str | None, int, list[str]]]:
        rows = ReplayVisionLearnedRuleset.objects.for_team(self.team.id).order_by(
            F("scanner_id").asc(nulls_first=True), "version"
        )
        return [
            (str(row.scanner_id) if row.scanner_id else None, row.version, [r["text"] for r in row.rules])
            for row in rows
        ]

    @patch("products.replay_vision.backend.learned_rules.posthoganalytics.capture")
    @patch(_GENERATE_PATH)
    def test_refresh_writes_new_versions_and_advances_the_watermark(self, mock_generate, mock_capture) -> None:
        older = self._rate(self.scanner, is_correct=False, feedback="A declined card is not a bug.")
        newer = self._rate(self.scanner, is_correct=True, age=dt.timedelta(minutes=40))
        mock_generate.return_value = _LlmRules(
            project_rules=[_rule("Treat a declined card as normal checkout behavior.", supported_by=["r1"])],
            scanners=[_LlmScannerRules(scanner="s1", rules=[_rule("Flag only failures the user sees.", "encourage")])],
        )

        assert refresh_team_learned_rules(self.team) is True

        # Unexplained ratings only teach when the model can see what the scanner said about the session.
        content = mock_generate.call_args.kwargs["user_content"]
        assert "[verdict=yes] The card was declined at (t 12)." in content
        assert "confidence 0.40" in content
        assert "Team note: A declined card is not a bug." in content
        assert self._rulesets() == [
            (None, 1, ["Treat a declined card as normal checkout behavior."]),
            (str(self.scanner.id), 1, ["Flag only failures the user sees."]),
        ]
        project = ReplayVisionLearnedRuleset.objects.for_team(self.team.id).get(scanner__isnull=True)
        assert project.rules[0]["evidence"] == [str(older.observation_id)]
        config = TeamReplayVisionConfig.objects.get(pk=self.team.id)
        assert config.learned_rules_watermark == newer.updated_at
        # Users never see the rules, so this event is the only trace of what the job wrote.
        assert sorted(
            (c.kwargs["properties"]["scope"], c.kwargs["properties"]["rules_added"])
            for c in mock_capture.call_args_list
        ) == [("project", 1), ("scanner", 1)]

        # Nothing new since the watermark: no model call, no new version.
        mock_generate.reset_mock()
        assert refresh_team_learned_rules(self.team) is False
        mock_generate.assert_not_called()

    @patch(_GENERATE_PATH)
    def test_repeated_notes_from_one_person_count_once(self, mock_generate) -> None:
        for _ in range(4):
            self._rate(self.scanner, is_correct=True, feedback="Routine session, no fault.")
        self._rate(self.scanner, is_correct=True, feedback="Right, the user never reached checkout.")
        mock_generate.return_value = _LlmRules(
            project_rules=[],
            scanners=[
                _LlmScannerRules(
                    scanner="s1",
                    rules=[_rule("Answer no when checkout never starts.", "encourage", supported_by=["r1", "r2"])],
                )
            ],
        )

        refresh_team_learned_rules(self.team)

        content = mock_generate.call_args.kwargs["user_content"]
        assert content.count("Team note: Routine session, no fault.") == 1
        assert "same note on 4 ratings" in content
        rule = ReplayVisionLearnedRuleset.objects.for_team(self.team.id).get(scanner=self.scanner).rules[0]
        assert len(rule["evidence"]) == 2

    @patch(_GENERATE_PATH)
    def test_unchanged_rules_write_no_new_version(self, mock_generate) -> None:
        backing = self._rate(self.scanner, is_correct=True, age=dt.timedelta(days=200))
        ReplayVisionLearnedRuleset.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            version=1,
            rules=[_stored("a1", "Keep this rule.", [str(backing.observation_id)]).model_dump()],
        )
        self._rate(self.scanner, is_correct=True)
        mock_generate.return_value = _LlmRules(
            project_rules=[_rule("Keep this rule.", rule_id="a1")], scanners=[_LlmScannerRules(scanner="s1", rules=[])]
        )

        assert refresh_team_learned_rules(self.team) is False
        assert self._rulesets() == [(None, 1, ["Keep this rule."])]
        # The model weighs rules by these counts, so they must reach it.
        assert (
            "id=a1 [avoid] Keep this rule. (backed by 1, contradicted by 0)"
            in (mock_generate.call_args.kwargs["user_content"])
        )

    @patch(_GENERATE_PATH)
    def test_a_response_missing_a_scanner_keeps_its_ratings_unread(self, mock_generate) -> None:
        self._rate(self.scanner, is_correct=False, feedback="Declines are normal.")
        mock_generate.return_value = _LlmRules(project_rules=[_rule("A project rule.")])

        with self.assertRaises(LearnedRulesError):
            refresh_team_learned_rules(self.team)

        assert self._rulesets() == []
        assert TeamReplayVisionConfig.objects.get(pk=self.team.id).learned_rules_watermark is None

    @patch(_GENERATE_PATH, side_effect=LearnedRulesError("model down"))
    def test_a_failed_run_keeps_the_rules_and_backs_off(self, _mock_generate) -> None:
        self._rate(self.scanner, is_correct=False, feedback="wrong")
        result = refresh_team_learned_rules_activity(RefreshTeamLearnedRulesInputs(team_id=self.team.id))

        assert result is False
        config = TeamReplayVisionConfig.objects.get(pk=self.team.id)
        assert config.learned_rules_watermark is None
        assert config.learned_rules_generated_at is not None
        assert due_teams(10) == []

    @parameterized.expand(
        [
            ("settled_burst", 1, dt.timedelta(hours=1), True, None, True),
            ("burst_still_arriving", 1, dt.timedelta(minutes=5), True, None, False),
            ("large_burst_runs_early", RATING_BURST_SIZE, dt.timedelta(minutes=5), True, None, True),
            ("no_ai_consent", 1, dt.timedelta(hours=1), False, None, False),
            (
                "experiment_scoped_only",
                1,
                dt.timedelta(hours=1),
                True,
                {"experiment_targeting": {"experiment_id": 7}},
                False,
            ),
            ("older_than_first_run_lookback", 1, dt.timedelta(days=120), True, None, False),
        ]
    )
    def test_due_teams(
        self, _name: str, count: int, age: dt.timedelta, consent: bool, snapshot_extra: dict | None, expected: bool
    ) -> None:
        self.organization.is_ai_data_processing_approved = consent
        self.organization.save()
        snapshot = {**snapshot_for(self.scanner), **snapshot_extra} if snapshot_extra else None
        for _ in range(count):
            self._rate(self.scanner, is_correct=False, age=age, snapshot=snapshot)

        assert (self.team.id in due_teams(10)) is expected

    def test_scans_freeze_the_current_rulesets_and_keep_them_out_of_api_dumps(self) -> None:
        other = self._create_scanner(name="other", scanner_type=ScannerType.MONITOR)
        rulesets = ReplayVisionLearnedRuleset.objects.for_team(self.team.id)
        rulesets.create(team_id=self.team.id, version=1, rules=[_stored("p0", "Old project rule.", []).model_dump()])
        project = rulesets.create(
            team_id=self.team.id, version=2, rules=[_stored("p1", "Project rule.", [], kind="encourage").model_dump()]
        )
        own = rulesets.create(
            team_id=self.team.id, scanner=self.scanner, version=1, rules=[_stored("s1", "Own rule.", []).model_dump()]
        )
        rulesets.create(
            team_id=self.team.id, scanner=other, version=1, rules=[_stored("o1", "Other rule.", []).model_dump()]
        )

        ids = current_ruleset_ids(self.team.id, self.scanner.id)

        assert sorted(ids) == sorted([str(project.id), str(own.id)])
        assert load_scan_rules(self.team.id, ids).project == ["Encourage: Project rule."]
        assert load_scan_rules(self.team.id, ids).scanner == ["Avoid: Own rule."]
        snapshot = ScannerSnapshot.model_validate({**snapshot_for(self.scanner), "learned_ruleset_ids": ids})
        assert snapshot.learned_ruleset_ids == ids
        assert "learned_ruleset_ids" not in snapshot.model_dump(mode="json")

    @patch(_GENERATE_PATH)
    def test_removed_ratings_stop_protecting_a_rule(self, mock_generate) -> None:
        backing = [self._rate(self.scanner, is_correct=False, feedback="Declines are normal.") for _ in range(3)]
        ReplayVisionLearnedRuleset.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            scanner=self.scanner,
            version=1,
            rules=[_stored("a1", "Treat declines as normal.", [str(b.observation_id) for b in backing]).model_dump()],
        )
        for label in backing[:2]:
            label.delete()
        self._rate(self.scanner, is_correct=True, feedback="Declines matter here.")
        mock_generate.return_value = _LlmRules(
            project_rules=[], scanners=[_LlmScannerRules(scanner="s1", rules=[], retired=[_LlmRetired(id="a1")])]
        )

        refresh_team_learned_rules(self.team)

        assert self._rulesets()[-1] == (str(self.scanner.id), 2, [])

    def test_staff_can_browse_rulesets_in_admin(self) -> None:
        ReplayVisionLearnedRuleset.objects.for_team(self.team.id).create(
            team_id=self.team.id, version=1, rules=[_stored("a1", "A rule.", []).model_dump()]
        )
        self.user.is_staff = True
        self.user.save()

        with override_settings(
            ADMIN_PORTAL_ENABLED=True,
            STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
        ):
            response = self.client.get("/admin/replay_vision/replayvisionlearnedruleset/")

        assert response.status_code == 200
