from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase

import jwt
import requests
from parameterized import parameterized

from posthog.plugins.plugin_server_api import reschedule_hog_flow_parked_jobs

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.timing_reschedule import (
    get_all_timing_action_ids,
    get_timing_reschedule_action_ids,
    parse_delay_duration_seconds,
    use_workflows_timing_reschedule,
)
from products.workflows.backend.tasks.hog_flows import reschedule_hog_flow_timing

RESCHEDULE_CLIENT_PATH = "products.workflows.backend.tasks.hog_flows.reschedule_hog_flow_parked_jobs"


def _delay(action_id: str = "delay_1", duration: str = "7d") -> dict:
    return {"id": action_id, "type": "delay", "config": {"delay_duration": duration}}


def _window(action_id: str = "wait_1", **config) -> dict:
    return {"id": action_id, "type": "wait_until_time_window", "config": {"day": "any", "time": "any", **config}}


class TestTimingRescheduleDiff(SimpleTestCase):
    @parameterized.expand(
        [
            ("days", "7d", 7 * 86400.0),
            ("fractional_hours", "1.5h", 5400.0),
            ("minutes", "10m", 600.0),
            ("seconds", "45s", 45.0),
            ("clamped_days", "45d", 30 * 86400.0),
            ("clamped_hours", "48h", 24 * 3600.0),
            ("garbage", "banana", None),
            ("missing_unit", "7", None),
            ("not_a_string", 7, None),
            ("none", None, None),
        ]
    )
    def test_parse_delay_duration_seconds(self, _name, value, expected):
        assert parse_delay_duration_seconds(value) == expected

    @parameterized.expand(
        [
            ("shortened", "7d", "1d", True),
            ("lengthened", "1d", "7d", False),
            ("unchanged", "7d", "7d", False),
            ("unit_equivalent", "1d", "24h", False),
            # 168h is clamped to the 24h unit max at runtime (mirroring the worker), so this
            # apparent no-op rewrite is really a shortening
            ("clamped_shortening", "7d", "168h", True),
            ("clamp_equivalent", "45d", "35d", False),
            ("unparseable_after", "7d", "banana", True),
            ("unparseable_before", "banana", "7d", True),
            ("unparseable_unchanged", "banana", "banana", False),
        ]
    )
    def test_delay_duration_edits(self, _name, before, after, expect_sweep):
        result = get_timing_reschedule_action_ids([_delay(duration=before)], [_delay(duration=after)])
        assert result == (["delay_1"] if expect_sweep else [])

    @parameterized.expand(
        [
            ("day_changed", {"day": "weekday"}, True),
            ("time_changed", {"time": ["09:00", "10:00"]}, True),
            ("timezone_changed", {"timezone": "Europe/Lisbon"}, True),
            ("person_timezone_toggled", {"use_person_timezone": True}, True),
            ("fallback_changed", {"fallback_timezone": "UTC"}, True),
            ("unchanged", {}, False),
        ]
    )
    def test_time_window_edits(self, _name, config_change, expect_sweep):
        result = get_timing_reschedule_action_ids([_window()], [_window(**config_change)])
        assert result == (["wait_1"] if expect_sweep else [])

    @parameterized.expand(
        [
            ("delay_to_window", _delay(action_id="a"), _window(action_id="a"), True),
            ("delay_to_function", _delay(action_id="a"), {"id": "a", "type": "function", "config": {}}, True),
            ("function_to_delay", {"id": "a", "type": "function", "config": {}}, _delay(action_id="a"), True),
            (
                "function_to_function",
                {"id": "a", "type": "function", "config": {"x": 1}},
                {"id": "a", "type": "function", "config": {"x": 2}},
                False,
            ),
        ]
    )
    def test_type_changes(self, _name, before, after, expect_sweep):
        result = get_timing_reschedule_action_ids([before], [after])
        assert result == (["a"] if expect_sweep else [])

    def test_added_and_deleted_timing_actions_do_not_sweep(self):
        assert get_timing_reschedule_action_ids([], [_delay()]) == []
        assert get_timing_reschedule_action_ids([_delay()], []) == []
        assert get_timing_reschedule_action_ids(None, None) == []

    def test_multiple_changed_actions_are_sorted_and_deduped(self):
        before = [_delay("delay_b", "7d"), _delay("delay_a", "7d"), _window("wait_1")]
        after = [_delay("delay_b", "1d"), _delay("delay_a", "1d"), _window("wait_1", day="weekend")]
        assert get_timing_reschedule_action_ids(before, after) == ["delay_a", "delay_b", "wait_1"]

    def test_pathological_diff_over_cap_sweeps_nothing(self):
        before = [_delay(f"delay_{i}", "7d") for i in range(101)]
        after = [_delay(f"delay_{i}", "1d") for i in range(101)]
        assert get_timing_reschedule_action_ids(before, after) == []

    def test_all_timing_action_ids_returns_only_timing_steps(self):
        actions = [
            _delay("delay_b"),
            _window("wait_a"),
            {"id": "fn_1", "type": "function", "config": {}},
            {"id": "cond_1", "type": "wait_until_condition", "config": {}},
        ]
        assert get_all_timing_action_ids(actions) == ["delay_b", "wait_a"]
        assert get_all_timing_action_ids(None) == []

    def test_all_timing_action_ids_over_cap_sweeps_nothing(self):
        assert get_all_timing_action_ids([_delay(f"delay_{i}") for i in range(101)]) == []


class TestTimingRescheduleFlag(SimpleTestCase):
    def _team(self) -> MagicMock:
        return MagicMock(uuid="team-uuid", organization_id="org-id", id=1)

    @parameterized.expand([("on", True), ("off", False)])
    def test_flag_value_passthrough(self, _name, enabled):
        with patch("posthoganalytics.feature_enabled", return_value=enabled):
            assert use_workflows_timing_reschedule(self._team()) is enabled

    def test_flag_check_failure_defaults_off(self):
        with patch("posthoganalytics.feature_enabled", side_effect=Exception("flag service down")):
            assert use_workflows_timing_reschedule(self._team()) is False


class TestRescheduleParkedJobsClient(BaseTest):
    @patch("posthog.plugins.plugin_server_api.internal_requests.post")
    def test_call_carries_a_scoped_jwt_and_timeout(self, mock_post):
        reschedule_hog_flow_parked_jobs(team_id=self.team.id, hog_flow_id="flow-uuid", action_ids=["delay_1"])

        kwargs = mock_post.call_args.kwargs
        # A hung plugin server must not pin the calling Celery worker indefinitely
        assert kwargs["timeout"] == 30
        # Auth is a scoped per-call JWT, never the fleet-wide internal secret
        assert "x-internal-api-secret" not in {k.lower() for k in kwargs["headers"]}
        token = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        claims = jwt.decode(
            token,
            settings.WORKFLOWS_RESCHEDULE_JWT_SECRETS[0],
            audience="posthog:workflows:reschedule_parked",
            algorithms=["HS256"],
        )
        assert claims["team_id"] == self.team.id
        assert claims["hog_flow_id"] == "flow-uuid"

    @patch("posthog.plugins.plugin_server_api.internal_requests.post")
    def test_call_fails_closed_when_key_unprovisioned(self, mock_post):
        with self.settings(WORKFLOWS_RESCHEDULE_JWT_SECRETS=[]):
            with self.assertRaises(RuntimeError):
                reschedule_hog_flow_parked_jobs(team_id=self.team.id, hog_flow_id="flow-uuid", action_ids=["delay_1"])
        mock_post.assert_not_called()


class TestRescheduleHogFlowTimingTask(BaseTest):
    def _create_flow(self, status: str = "active") -> HogFlow:
        return HogFlow.objects.create(name="Test Flow", team=self.team, status=status)

    def _response(self, payload: dict, status_code: int = 200) -> MagicMock:
        response = MagicMock(status_code=status_code)
        response.json.return_value = payload
        if status_code >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error", response=response)
        else:
            response.raise_for_status.return_value = None
        return response

    @patch(RESCHEDULE_CLIENT_PATH)
    def test_single_slice_when_done(self, mock_client):
        flow = self._create_flow()
        mock_client.return_value = self._response({"swept": 3, "remaining": 0, "done": True})

        with patch.object(reschedule_hog_flow_timing, "apply_async") as mock_apply:
            reschedule_hog_flow_timing(team_id=self.team.id, hog_flow_id=str(flow.id), action_ids=["delay_1"])

        mock_client.assert_called_once_with(
            team_id=self.team.id,
            hog_flow_id=str(flow.id),
            action_ids=["delay_1"],
            sweep_floor=None,
            sweep_until=None,
        )
        mock_apply.assert_not_called()

    @patch(RESCHEDULE_CLIENT_PATH)
    def test_re_enqueues_with_returned_bounds_until_done(self, mock_client):
        flow = self._create_flow()
        mock_client.return_value = self._response(
            {
                "swept": 100,
                "remaining": 40,
                "done": False,
                "sweep_floor": "2026-07-15T00:10:00Z",
                "sweep_until": "2026-07-15T00:40:00Z",
            }
        )

        with patch.object(reschedule_hog_flow_timing, "apply_async") as mock_apply:
            reschedule_hog_flow_timing(
                team_id=self.team.id, hog_flow_id=str(flow.id), action_ids=["delay_1"], slice_count=2
            )

        mock_apply.assert_called_once_with(
            kwargs={
                "team_id": self.team.id,
                "hog_flow_id": str(flow.id),
                "action_ids": ["delay_1"],
                "sweep_floor": "2026-07-15T00:10:00Z",
                "sweep_until": "2026-07-15T00:40:00Z",
                "slice_count": 3,
            },
            countdown=5,
        )

    @patch(RESCHEDULE_CLIENT_PATH)
    def test_error_response_raises_for_retry(self, mock_client):
        flow = self._create_flow()
        mock_client.return_value = self._response({}, status_code=503)

        with self.assertRaises(requests.HTTPError):
            reschedule_hog_flow_timing(team_id=self.team.id, hog_flow_id=str(flow.id), action_ids=["delay_1"])

    @parameterized.expand([("disabled", "draft"), ("archived", "archived")])
    @patch(RESCHEDULE_CLIENT_PATH)
    def test_skips_inactive_flows(self, _name, status, mock_client):
        flow = self._create_flow(status=status)

        reschedule_hog_flow_timing(team_id=self.team.id, hog_flow_id=str(flow.id), action_ids=["delay_1"])

        mock_client.assert_not_called()

    @patch(RESCHEDULE_CLIENT_PATH)
    def test_stops_at_slice_limit(self, mock_client):
        flow = self._create_flow()

        reschedule_hog_flow_timing(
            team_id=self.team.id, hog_flow_id=str(flow.id), action_ids=["delay_1"], slice_count=501
        )

        mock_client.assert_not_called()
