from uuid import uuid4

import time_machine
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import fakeredis
from parameterized import parameterized

from posthog.ph_client import get_client
from posthog.redis import TEST_clear_clients

from products.tasks.backend.logic.stream.budget_steer import BudgetSteerCapture, BudgetSteerProperties
from products.tasks.backend.tasks.tasks import capture_budget_steer


class TestBudgetSteerCapture(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        TEST_clear_clients()
        self.run_id = str(uuid4())
        self.properties: BudgetSteerProperties = {
            "team_id": 1,
            "run_id": self.run_id,
            "stage": "warn",
            "mode": "publish",
            "delivered": True,
            "spent_usd": 5.0,
            "cap_usd": 10.0,
        }

    @parameterized.expand(
        [
            ((6, 2), None, "2026-01-01T23:59:59+00:00"),
            ((6, 2), "2026-01-01T23:59:58.000Z", "2026-01-01T23:59:58+00:00"),
            ((7, 4), None, "2026-01-01T23:59:59+00:00"),
            ((7, 4), "2026-01-01T23:59:58.000Z", "2026-01-01T23:59:58+00:00"),
        ]
    )
    def test_replays_preserve_timestamp_across_midnight(
        self, redis_version: tuple[int, int], event_timestamp: str | None, expected: str
    ) -> None:
        # The shared fake client speaks the newest command set, which hides commands older servers reject.
        redis = fakeredis.FakeRedis(server=fakeredis.FakeServer(version=redis_version))
        with (
            patch(
                "products.tasks.backend.logic.stream.budget_steer.get_tasks_stream_redis_sync",
                return_value=redis,
            ),
            patch("products.tasks.backend.logic.stream.budget_steer.current_app.send_task") as dispatch,
        ):
            with time_machine.travel("2026-01-01T23:59:59Z", tick=False):
                BudgetSteerCapture.enqueue(1, self.run_id, 7, self.properties, event_timestamp)
            with time_machine.travel("2026-01-02T00:00:01Z", tick=False):
                BudgetSteerCapture.enqueue(1, self.run_id, 7, self.properties, event_timestamp)

        self.assertEqual(dispatch.call_count, 2)
        self.assertEqual(dispatch.call_args_list[0], dispatch.call_args_list[1])
        self.assertEqual(dispatch.call_args.kwargs["kwargs"]["timestamp"], expected)

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_upload_failure_is_retried_before_marking_capture_complete(self) -> None:
        with patch("products.tasks.backend.logic.stream.budget_steer.current_app.send_task") as dispatch:
            BudgetSteerCapture.enqueue(1, self.run_id, 7, self.properties, "2026-01-01T00:00:00Z")
        payload = dispatch.call_args.kwargs["kwargs"]

        with (
            patch(
                "posthoganalytics.consumer.Consumer.request", side_effect=[RuntimeError("upload failed"), None]
            ) as upload,
            patch(
                "posthog.ph_client.get_client",
                side_effect=lambda region, **kwargs: get_client(region, disabled=False, max_retries=0, **kwargs),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "upload failed"):
                capture_budget_steer.run(**payload)
            capture_budget_steer.run(**payload)
            capture_budget_steer.run(**payload)

        self.assertEqual(upload.call_count, 2)
        first_event = upload.call_args_list[0].args[0][0]
        retried_event = upload.call_args_list[1].args[0][0]
        self.assertEqual(first_event["timestamp"], retried_event["timestamp"])
        self.assertEqual(first_event["uuid"], retried_event["uuid"])
        with patch("products.tasks.backend.logic.stream.budget_steer.current_app.send_task") as dispatch:
            BudgetSteerCapture.enqueue(1, self.run_id, 7, self.properties)
        dispatch.assert_not_called()
