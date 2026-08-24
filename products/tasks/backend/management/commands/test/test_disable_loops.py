from io import StringIO

from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team, User

from products.tasks.backend.loop_lifecycle import DEFAULT_PAUSE_MESSAGE
from products.tasks.backend.models import Loop, Task, TaskRun

LIFECYCLE_MODULE = "products.tasks.backend.loop_lifecycle"
ENABLED_LOOPS = ("a1", "a2", "b1")


class TestDisableLoops(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.mock_pause_schedules = patch(f"{LIFECYCLE_MODULE}.pause_loop_schedules").start()
        self.mock_dispatch = patch(f"{LIFECYCLE_MODULE}.dispatch_loop_event").start()
        self.mock_signal = patch(f"{LIFECYCLE_MODULE}.signal_loop_run_cancelled").start()
        self.addCleanup(patch.stopall)

        self.org_a = Organization.objects.create(name="Org A")
        self.org_b = Organization.objects.create(name="Org B")
        self.team_a1 = Team.objects.create(organization=self.org_a, name="A1")
        self.team_a2 = Team.objects.create(organization=self.org_a, name="A2")
        self.team_b1 = Team.objects.create(organization=self.org_b, name="B1")
        self.user = User.objects.create_user(email="owner@example.com", first_name="Owner", password=None)
        self.loops = {
            "a1": self._loop(self.team_a1, "a1"),
            "a1-paused": self._loop(self.team_a1, "a1-paused", enabled=False),
            "a1-deleted": self._loop(self.team_a1, "a1-deleted", deleted=True),
            "a2": self._loop(self.team_a2, "a2"),
            "b1": self._loop(self.team_b1, "b1"),
        }
        self.placeholders = {
            "team_a1": str(self.team_a1.id),
            "team_a2": str(self.team_a2.id),
            "org_a": str(self.org_a.id),
            "org_b": str(self.org_b.id),
            "loop_a2": str(self.loops["a2"].id),
            "loop_b1": str(self.loops["b1"].id),
            "loop_a1_deleted": str(self.loops["a1-deleted"].id),
        }

    def _loop(self, team: Team, name: str, **overrides: object) -> Loop:
        fields: dict[str, object] = {
            "team": team,
            "created_by": self.user,
            "name": name,
            "instructions": "Summarize",
            "runtime_adapter": "claude",
            "model": "claude-sonnet-5",
            "enabled": True,
        }
        fields.update(overrides)
        return Loop.objects.unscoped().create(**fields)

    def _call(self, *args: str) -> str:
        stdout = StringIO()
        call_command("disable_loops", *[arg.format(**self.placeholders) for arg in args], stdout=stdout)
        return stdout.getvalue()

    def _state(self) -> dict[str, tuple[bool, str | None]]:
        return {
            loop.name: (loop.enabled, loop.disabled_reason)
            for loop in Loop.objects.unscoped().filter(id__in=[loop.id for loop in self.loops.values()])
        }

    def _assert_untouched(self, names: tuple[str, ...] = ENABLED_LOOPS) -> None:
        state = self._state()
        assert all(state[name] == (True, None) for name in names)
        assert state["a1-paused"] == (False, None)
        assert state["a1-deleted"] == (True, None)

    def _in_flight_run(self, loop: Loop) -> TaskRun:
        task = Task.objects.create(
            team=loop.team,
            created_by=self.user,
            title="Active",
            description="d",
            origin_product=Task.OriginProduct.LOOP,
            internal=True,
        )
        run = task.create_run(mode="background", extra_state={"loop_id": str(loop.id)})
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status", "updated_at"])
        return run

    @parameterized.expand(
        [
            ("all", ["--all"], {"a1", "a2", "b1"}),
            ("team", ["--team-id", "{team_a1}"], {"a1"}),
            ("teams", ["--team-id", "{team_a1}", "{team_a2}"], {"a1", "a2"}),
            ("organization", ["--organization-id", "{org_a}"], {"a1", "a2"}),
            ("loop_ids", ["--loop-id", "{loop_a2}", "{loop_b1}"], {"a2", "b1"}),
            ("loop_ids_skip_deleted", ["--loop-id", "{loop_a2}", "{loop_a1_deleted}"], {"a2"}),
            ("team_and_organization_intersect", ["--team-id", "{team_a1}", "--organization-id", "{org_b}"], set()),
        ]
    )
    def test_pauses_only_matching_enabled_loops(self, _name: str, args: list[str], expected: set[str]) -> None:
        output = self._call(*args, "--reason", "maintenance", "--yes")

        state = self._state()
        assert {name for name in ENABLED_LOOPS if state[name] == (False, "maintenance")} == expected
        self._assert_untouched(tuple(name for name in ENABLED_LOOPS if name not in expected))
        assert {call.args[0].name for call in self.mock_pause_schedules.call_args_list} == expected
        assert {call.args[0].name for call in self.mock_dispatch.call_args_list} == expected
        if expected:
            assert f"Paused {len(expected)} loop(s) with reason 'maintenance'." in output
        else:
            assert "No loops to pause." in output

    def test_dry_run_changes_nothing(self) -> None:
        output = self._call("--all", "--reason", "maintenance", "--dry-run")

        assert "3 to pause, 1 already paused (skipped)" in output
        assert "Dry run: 3 loop(s) would be paused." in output
        self._assert_untouched()
        self.mock_pause_schedules.assert_not_called()
        self.mock_dispatch.assert_not_called()

    @parameterized.expand(
        [
            ("default_message", [], DEFAULT_PAUSE_MESSAGE),
            ("custom_message", ["--message", "Paused while we fix things."], "Paused while we fix things."),
        ]
    )
    def test_notifies_owner_with_reason_and_message(self, _name: str, args: list[str], expected_body: str) -> None:
        self._call("--loop-id", "{loop_a2}", "--reason", "maintenance", "--yes", *args)

        self.mock_dispatch.assert_called_once()
        loop, event, payload = self.mock_dispatch.call_args.args
        assert (loop.id, event) == (self.loops["a2"].id, "needs_attention")
        assert payload == {"reason": "maintenance", "body": expected_body}

    def test_no_notify_skips_notification(self) -> None:
        self._call("--loop-id", "{loop_a2}", "--reason", "maintenance", "--yes", "--no-notify")

        assert self._state()["a2"] == (False, "maintenance")
        self.mock_dispatch.assert_not_called()

    @parameterized.expand(
        [
            ("keeps_runs_by_default", [], TaskRun.Status.IN_PROGRESS, 0),
            ("cancels_runs_on_request", ["--cancel-runs"], TaskRun.Status.CANCELLED, 1),
        ]
    )
    def test_cancel_runs_flag(self, _name: str, args: list[str], expected_status: str, expected_signals: int) -> None:
        run = self._in_flight_run(self.loops["a2"])

        output = self._call("--loop-id", "{loop_a2}", "--reason", "maintenance", "--yes", *args)

        run.refresh_from_db()
        assert run.status == expected_status
        assert self.mock_signal.call_count == expected_signals
        assert ("Cancelled 1 in-flight run(s)." in output) == bool(expected_signals)

    @parameterized.expand(
        [
            ("no_filters", ["--reason", "maintenance"]),
            ("all_with_filter", ["--all", "--team-id", "{team_a1}", "--reason", "maintenance"]),
            ("reason_not_snake_case", ["--all", "--reason", "Billing Hold"]),
            ("reason_too_long", ["--all", "--reason", "x" * 65]),
            ("bad_loop_uuid", ["--loop-id", "not-a-uuid", "--reason", "maintenance"]),
            ("unknown_loop", ["--loop-id", "00000000-0000-0000-0000-000000000000", "--reason", "maintenance"]),
            ("bad_organization_uuid", ["--organization-id", "nope", "--reason", "maintenance"]),
        ]
    )
    def test_rejects_invalid_arguments(self, _name: str, args: list[str]) -> None:
        with self.assertRaises(CommandError):
            self._call(*args, "--yes")

        self._assert_untouched()
        self.mock_pause_schedules.assert_not_called()

    def test_refuses_without_yes_when_not_interactive(self) -> None:
        with patch("sys.stdin") as stdin, self.assertRaises(CommandError):
            stdin.isatty.return_value = False
            self._call("--all", "--reason", "maintenance")

        self._assert_untouched()
        self.mock_pause_schedules.assert_not_called()
