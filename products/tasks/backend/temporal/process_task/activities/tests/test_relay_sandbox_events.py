from parameterized import parameterized

from products.tasks.backend.temporal.process_task.activities.relay_sandbox_events import (
    _is_end_of_turn,
    _is_session_update,
)


class TestIsSessionUpdate:
    @parameterized.expand(
        [
            (
                "session_update",
                {"type": "notification", "notification": {"method": "session/update"}},
                True,
            ),
            (
                "console_notification",
                {"type": "notification", "notification": {"method": "_posthog/console"}},
                False,
            ),
            (
                "sandbox_output_notification",
                {"type": "notification", "notification": {"method": "_posthog/sandbox_output"}},
                False,
            ),
            (
                "terminal_task_complete",
                {"type": "notification", "notification": {"method": "_posthog/task_complete"}},
                False,
            ),
            (
                "terminal_error",
                {"type": "notification", "notification": {"method": "_posthog/error"}},
                False,
            ),
            (
                "non_notification_type",
                {"type": "event", "notification": {"method": "session/update"}},
                False,
            ),
            (
                "missing_notification",
                {"type": "notification"},
                False,
            ),
            (
                "empty_dict",
                {},
                False,
            ),
        ],
    )
    def test_is_session_update(self, _name: str, event_data: dict, expected: bool):
        assert _is_session_update(event_data) == expected


class TestAgentActiveReactivation:
    """Verify that agent_active is only re-activated by session/update events.

    This tests the logic from lines 231-232 of relay_sandbox_events.py:
        elif not agent_active[0] and _is_session_update(event_data):
            agent_active[0] = True
    """

    @staticmethod
    def _simulate_reactivation(event_data: dict, agent_active: bool) -> bool:
        """Replicate the inline re-activation logic from _relay_loop."""
        active = [agent_active]
        if _is_end_of_turn(event_data):
            active[0] = False
        elif not active[0] and _is_session_update(event_data):
            active[0] = True
        return active[0]

    def test_session_update_reactivates_after_end_turn(self):
        event = {"type": "notification", "notification": {"method": "session/update"}}
        assert self._simulate_reactivation(event, agent_active=False) is True

    def test_console_event_does_not_reactivate(self):
        event = {"type": "notification", "notification": {"method": "_posthog/console"}}
        assert self._simulate_reactivation(event, agent_active=False) is False

    def test_sandbox_output_does_not_reactivate(self):
        event = {"type": "notification", "notification": {"method": "_posthog/sandbox_output"}}
        assert self._simulate_reactivation(event, agent_active=False) is False

    def test_end_turn_deactivates(self):
        end_turn = {
            "type": "notification",
            "notification": {"result": {"stopReason": "end_turn"}},
        }
        assert self._simulate_reactivation(end_turn, agent_active=True) is False

    def test_full_lifecycle_turn_then_idle_then_resume(self):
        """Simulate: agent active → end_turn → console noise → session/update resumes."""
        active = [True]

        # Agent finishes turn
        end_turn = {"type": "notification", "notification": {"result": {"stopReason": "end_turn"}}}
        if _is_end_of_turn(end_turn):
            active[0] = False
        assert active[0] is False

        # Console events should NOT re-activate
        for method in ("_posthog/console", "_posthog/sandbox_output"):
            event = {"type": "notification", "notification": {"method": method}}
            if not active[0] and _is_session_update(event):
                active[0] = True
            assert active[0] is False, f"{method} should not re-activate agent"

        # session/update from new user message SHOULD re-activate
        session_event = {"type": "notification", "notification": {"method": "session/update"}}
        if not active[0] and _is_session_update(session_event):
            active[0] = True
        assert active[0] is True
