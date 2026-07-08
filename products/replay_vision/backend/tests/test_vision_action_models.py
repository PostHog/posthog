import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest

from django.db import IntegrityError
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping.manager import TeamScopeError

from products.replay_vision.backend.models import ReplayScanner, VisionAction, VisionActionRun
from products.replay_vision.backend.models.replay_scanner import ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import (
    ActionMode,
    TriggerType,
    VisionActionRunStatus,
    default_selection,
)
from products.replay_vision.backend.rrule import compute_next_occurrences, validate_rrule, validate_timezone

DAILY_9AM = "FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0"


def _make_action(team, **overrides) -> VisionAction:
    if "scanner" not in overrides:
        overrides["scanner"] = ReplayScanner.objects.create(
            team=team,
            name=f"scanner-{uuid.uuid4().hex[:8]}",
            scanner_type=ScannerType.SUMMARIZER,
            scanner_config={"prompt": "x"},
            model=ScannerModel.GEMINI_3_FLASH,
        )
    defaults: dict = {
        "team": team,
        "name": "my-action",
        "trigger_config": {"rrule": DAILY_9AM, "timezone": "UTC"},
    }
    defaults.update(overrides)
    action = VisionAction(**defaults)
    action.save()
    return action


class TestVisionActionModel(BaseTest):
    def _create_action(self, **overrides) -> VisionAction:
        return _make_action(self.team, **overrides)

    def test_defaults(self) -> None:
        action = self._create_action()
        self.assertEqual(action.enabled, True)
        self.assertEqual(action.trigger_type, TriggerType.SCHEDULE)
        self.assertEqual(action.mode, ActionMode.GROUP_SUMMARY)
        self.assertEqual(action.selection, {"window_days": 1})
        self.assertEqual(action.synthesis_config, {})
        self.assertEqual(action.delivery_config, [])
        self.assertIsNotNone(action.scanner)
        self.assertIsNone(action.hog_flow)

    def test_default_selection_is_a_fresh_dict_per_instance(self) -> None:
        # Guards against the classic mutable-default footgun.
        a = self._create_action(name="a")
        b = self._create_action(name="b")
        a.selection["window_days"] = 99
        self.assertEqual(b.selection["window_days"], 1)
        self.assertIsNot(default_selection(), default_selection())

    def test_next_run_at_computed_from_rrule_on_create(self) -> None:
        action = self._create_action()
        self.assertIsNotNone(action.next_run_at)
        assert action.next_run_at is not None
        self.assertGreater(action.next_run_at, timezone.now())
        # 9am UTC daily — the computed time must land on 09:00.
        self.assertEqual(action.next_run_at.astimezone(UTC).hour, 9)

    def test_next_run_at_none_without_rrule(self) -> None:
        action = self._create_action(trigger_config={})
        self.assertIsNone(action.next_run_at)

    def test_next_run_at_none_for_non_schedule_trigger(self) -> None:
        action = self._create_action(
            trigger_type=TriggerType.THRESHOLD,
            trigger_config={"rrule": DAILY_9AM},
        )
        self.assertIsNone(action.next_run_at)

    def test_next_run_at_recomputed_only_when_rrule_changes(self) -> None:
        action = self._create_action()
        original = action.next_run_at

        # Non-rrule change → next_run_at untouched.
        action.name = "renamed"
        action.save()
        action.refresh_from_db()
        self.assertEqual(action.next_run_at, original)

        # rrule change → recomputed (to a different time).
        action.trigger_config = {"rrule": "FREQ=DAILY;BYHOUR=17;BYMINUTE=0;BYSECOND=0", "timezone": "UTC"}
        action.save()
        action.refresh_from_db()
        self.assertIsNotNone(action.next_run_at)
        assert action.next_run_at is not None
        self.assertEqual(action.next_run_at.astimezone(UTC).hour, 17)

    def test_next_run_at_recomputed_on_timezone_change(self) -> None:
        # Same rrule, different timezone → next_run_at must move (9am UTC vs 9am Tokyo are different
        # instants). Keying the recompute on the rrule string alone would miss this.
        action = self._create_action(trigger_config={"rrule": DAILY_9AM, "timezone": "UTC"})
        original = action.next_run_at

        action.trigger_config = {"rrule": DAILY_9AM, "timezone": "Asia/Tokyo"}
        action.save()
        action.refresh_from_db()
        self.assertIsNotNone(action.next_run_at)
        self.assertNotEqual(action.next_run_at, original)
        assert action.next_run_at is not None
        # 9am Tokyo = 00:00 UTC.
        self.assertEqual(action.next_run_at.astimezone(UTC).hour, 0)

    def test_recompute_survives_update_fields(self) -> None:
        action = self._create_action()
        action.trigger_config = {"rrule": "FREQ=DAILY;BYHOUR=17;BYMINUTE=0;BYSECOND=0", "timezone": "UTC"}
        # Even with a narrow update_fields, next_run_at must be appended and persisted.
        action.save(update_fields=["trigger_config"])
        action.refresh_from_db()
        assert action.next_run_at is not None
        self.assertEqual(action.next_run_at.astimezone(UTC).hour, 17)

    def test_loading_with_deferred_fields_does_not_recurse(self) -> None:
        action = self._create_action()
        # .only() defers trigger_config/trigger_type — __init__ must not touch them.
        lite = VisionAction.all_teams.only("id", "name").get(pk=action.pk)
        self.assertEqual(lite.name, "my-action")

    def test_unique_team_name(self) -> None:
        self._create_action(name="dup")
        with self.assertRaises(IntegrityError):
            self._create_action(name="dup")

    def test_same_name_allowed_across_teams(self) -> None:
        other = self.organization.teams.create(name="other")
        self._create_action(name="shared")
        # Different team → no clash.
        _make_action(other, name="shared")

    def test_scanner_cascade_delete(self) -> None:
        scanner = ReplayScanner.objects.create(
            team=self.team,
            name="scanner",
            scanner_type=ScannerType.SUMMARIZER,
            scanner_config={"prompt": "x"},
            model=ScannerModel.GEMINI_3_FLASH,
        )
        action = self._create_action(scanner=scanner)
        scanner.delete()
        self.assertFalse(VisionAction.all_teams.filter(pk=action.pk).exists())

    def test_str(self) -> None:
        action = self._create_action(name="weekly summary")
        self.assertIn("weekly summary", str(action))


class TestVisionActionScoping(BaseTest):
    def test_for_team_returns_only_that_teams_actions(self) -> None:
        other = self.organization.teams.create(name="other")
        mine = _make_action(self.team, name="mine")
        _make_action(other, name="theirs")

        ids = list(VisionAction.objects.for_team(self.team.id).values_list("id", flat=True))
        self.assertEqual(ids, [mine.id])

    def test_objects_fail_closed_without_team_context(self) -> None:
        _make_action(self.team)
        with self.assertRaises(TeamScopeError):
            list(VisionAction.objects.all())

    def test_unscoped_sees_all_teams(self) -> None:
        other = self.organization.teams.create(name="other")
        _make_action(self.team, name="mine")
        _make_action(other, name="theirs")
        self.assertEqual(VisionAction.objects.unscoped().count(), 2)


class TestVisionActionRunModel(BaseTest):
    def _run(self, action: VisionAction | None = None, **overrides) -> VisionActionRun:
        # Default to a uniquely-named action so repeated calls don't trip the (team, name)
        # constraint — that would mask the constraint a given test actually means to exercise.
        if action is None:
            action = _make_action(self.team, name=f"run-action-{uuid.uuid4().hex[:8]}")
        defaults: dict = {
            "vision_action": action,
            "team": self.team,
            "idempotency_key": "key-1",
        }
        defaults.update(overrides)
        run = VisionActionRun(**defaults)
        run.save()
        return run

    def test_defaults(self) -> None:
        run = self._run()
        self.assertEqual(run.status, VisionActionRunStatus.RUNNING)
        self.assertEqual(run.observation_count, 0)
        self.assertEqual(run.synthesized_markdown, "")
        self.assertEqual(run.output, {})
        self.assertIsNone(run.error)

    def test_idempotency_key_unique(self) -> None:
        # Both runs share one action, so the only constraint in play is idempotency_key uniqueness.
        action = _make_action(self.team, name="shared-action")
        self._run(action=action, idempotency_key="dup")
        with self.assertRaises(IntegrityError):
            self._run(action=action, idempotency_key="dup")

    def test_run_cascade_deleted_with_action(self) -> None:
        action = _make_action(self.team, name="parent")
        run = VisionActionRun(vision_action=action, team=self.team, idempotency_key="k")
        run.save()
        action.delete()
        self.assertFalse(VisionActionRun.all_teams.filter(pk=run.pk).exists())


class TestRruleHelper(BaseTest):
    def test_validate_rejects_dtstart(self) -> None:
        with self.assertRaises(ValueError):
            validate_rrule("DTSTART:20260101T090000\nFREQ=DAILY")

    def test_validate_rejects_lowercase_dtstart(self) -> None:
        # dateutil uppercases property names, so a lowercase dtstart must not slip past the guard.
        with self.assertRaises(ValueError):
            validate_rrule("dtstart:20260101T090000\nFREQ=DAILY")

    @parameterized.expand(
        [
            ("bad_freq", "FREQ=NONSENSE;INTERVAL=banana"),  # rrulestr -> ValueError
            ("bad_byday", "FREQ=DAILY;BYDAY=XX"),  # rrulestr -> ValueError
            ("bad_interval", "FREQ=DAILY;INTERVAL=abc"),  # rrulestr -> ValueError
            ("empty", ""),  # rrulestr -> ValueError
            ("not_an_rrule", "not an rrule at all"),  # rrulestr -> ValueError
            ("missing_freq", "COUNT=5"),  # rrulestr -> TypeError (the case the narrow catch handled)
        ]
    )
    def test_validate_normalizes_malformed_to_value_error(self, _label: str, rrule: str) -> None:
        # rrulestr raises ValueError for most malformed input and TypeError only for missing FREQ —
        # both must surface as the documented ValueError, never leak as an unhandled TypeError.
        with self.assertRaises(ValueError):
            validate_rrule(rrule)

    def test_validate_accepts_valid(self) -> None:
        validate_rrule("FREQ=WEEKLY;BYDAY=MO,WE,FR;BYHOUR=9")

    def test_validate_timezone_accepts_valid(self) -> None:
        validate_timezone("Europe/Prague")
        validate_timezone("UTC")

    @parameterized.expand([("unknown", "Mars/Phobos"), ("garbage", "not a tz"), ("empty", "")])
    def test_validate_timezone_rejects_invalid(self, _label: str, tz: str) -> None:
        with self.assertRaises(ValueError):
            validate_timezone(tz)

    def test_occurrences_are_future_and_utc(self) -> None:
        starts = datetime(2026, 1, 1, tzinfo=UTC)
        after = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        out = compute_next_occurrences(DAILY_9AM, starts_at=starts, after=after, count=3)
        self.assertEqual(len(out), 3)
        for dt in out:
            self.assertEqual(dt.tzinfo, UTC)
            self.assertGreater(dt, after)
        # Strictly increasing.
        self.assertEqual(out, sorted(out))

    def test_exhausted_rrule_returns_empty(self) -> None:
        starts = datetime(2026, 1, 1, tzinfo=UTC)
        after = datetime(2030, 1, 1, tzinfo=UTC)
        # COUNT=1 from 2026 is long exhausted by 2030.
        out = compute_next_occurrences("FREQ=DAILY;COUNT=1", starts_at=starts, after=after, count=5)
        self.assertEqual(out, [])

    def test_dst_keeps_local_wall_clock(self) -> None:
        # 9am Europe/Prague should stay 9am local across the spring DST switch,
        # which means the UTC hour shifts from 8 (winter, UTC+1) to 7 (summer, UTC+2).
        tz = "Europe/Prague"
        starts = datetime(2026, 1, 1, tzinfo=ZoneInfo(tz))
        winter = compute_next_occurrences(
            DAILY_9AM, starts_at=starts, timezone_str=tz, after=datetime(2026, 1, 15, tzinfo=UTC), count=1
        )[0]
        summer = compute_next_occurrences(
            DAILY_9AM, starts_at=starts, timezone_str=tz, after=datetime(2026, 7, 15, tzinfo=UTC), count=1
        )[0]
        self.assertEqual(winter.astimezone(ZoneInfo(tz)).hour, 9)
        self.assertEqual(summer.astimezone(ZoneInfo(tz)).hour, 9)
        self.assertEqual(winter.hour, 8)  # UTC
        self.assertEqual(summer.hour, 7)  # UTC


class TestVisionActionStress(BaseTest):
    @parameterized.expand(
        [
            ("daily", "FREQ=DAILY;BYHOUR=9", "UTC"),
            ("weekly_mwf", "FREQ=WEEKLY;BYDAY=MO,WE,FR;BYHOUR=8", "UTC"),
            ("monthly_first_weekday", "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1;BYHOUR=7", "America/New_York"),
            ("biweekly", "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU;BYHOUR=10", "Europe/London"),
            ("hourly", "FREQ=HOURLY;INTERVAL=6", "Asia/Tokyo"),
            ("yearly", "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1;BYHOUR=0", "UTC"),
        ]
    )
    def test_varied_rrules_all_compute_a_future_run(self, label: str, rrule: str, tz: str) -> None:
        action = _make_action(self.team, name=label, trigger_config={"rrule": rrule, "timezone": tz})
        self.assertIsNotNone(action.next_run_at)
        assert action.next_run_at is not None
        self.assertGreater(action.next_run_at, timezone.now())

    def test_bulk_create_and_due_scan(self) -> None:
        # Stand up many actions, half in the past (due) and half in the future, then exercise
        # the exact predicate the scheduler fan-out will use and assert it returns only the due ones.
        past = timezone.now() - timedelta(hours=1)
        future = timezone.now() + timedelta(days=1)
        due_ids = set()
        for i in range(200):
            action = _make_action(self.team, name=f"action-{i}", trigger_config={})
            if i % 2 == 0:
                action.next_run_at = past
                due_ids.add(action.id)
            else:
                action.next_run_at = future
            action.save(update_fields=["next_run_at"])

        scanned = set(
            VisionAction.objects.for_team(self.team.id)
            .filter(enabled=True, trigger_type=TriggerType.SCHEDULE, next_run_at__lte=timezone.now())
            .values_list("id", flat=True)
        )
        self.assertEqual(scanned, due_ids)

    def test_disabled_actions_excluded_from_due_scan(self) -> None:
        past = timezone.now() - timedelta(hours=1)
        enabled = _make_action(self.team, name="on", trigger_config={})
        enabled.next_run_at = past
        enabled.save(update_fields=["next_run_at"])
        disabled = _make_action(self.team, name="off", trigger_config={}, enabled=False)
        disabled.next_run_at = past
        disabled.save(update_fields=["next_run_at"])

        scanned = set(
            VisionAction.objects.for_team(self.team.id)
            .filter(enabled=True, next_run_at__lte=timezone.now())
            .values_list("id", flat=True)
        )
        self.assertEqual(scanned, {enabled.id})
