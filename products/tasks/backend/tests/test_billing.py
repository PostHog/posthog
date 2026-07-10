import datetime

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

import requests
from rest_framework.exceptions import NotAuthenticated

from products.tasks.backend.billing import get_seat_covered_distinct_ids


@override_settings(BILLING_SERVICE_API_KEY="pk_test_roster_key")
class TestActiveRoster(TestCase):
    def test_missing_api_key_raises(self):
        with override_settings(BILLING_SERVICE_API_KEY=""):
            with self.assertRaises(NotAuthenticated):
                get_seat_covered_distinct_ids("posthog_code", datetime.date(2026, 7, 9))

    @patch("products.tasks.backend.billing.requests.get")
    def test_partitions_seat_covered_from_usage_plan_and_roster_absent_seats(self, mock_get):
        """Only non-usage-plan seats (free/pro/alpha) are seat-covered; usage-plan seats and
        distinct_ids absent from the roster altogether stay billable."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "results": [
                        {
                            "user_distinct_id": "user_pro",
                            "plan_key": "posthog-code-pro",
                            "status": "active",
                            "organization_id": "org_1",
                        },
                        {
                            "user_distinct_id": "user_usage_plan",
                            "plan_key": "posthog-code-usage-20260709",
                            "status": "active",
                            "organization_id": "org_2",
                        },
                    ],
                    "next": None,
                }
            ),
        )

        seat_covered = get_seat_covered_distinct_ids("posthog_code", datetime.date(2026, 7, 9))

        self.assertEqual(seat_covered, {"user_pro"})
        self.assertNotIn("user_usage_plan", seat_covered)
        self.assertNotIn("user_no_seat", seat_covered)

    @patch("products.tasks.backend.billing.requests.get")
    def test_roster_fetch_follows_pagination(self, mock_get):
        mock_get.side_effect = [
            MagicMock(
                status_code=200,
                json=MagicMock(
                    return_value={
                        "results": [
                            {
                                "user_distinct_id": "user_1",
                                "plan_key": "posthog-code-free",
                                "status": "active",
                                "organization_id": "org_1",
                            }
                        ],
                        "next": "cursor_2",
                    }
                ),
            ),
            MagicMock(
                status_code=200,
                json=MagicMock(
                    return_value={
                        "results": [
                            {
                                "user_distinct_id": "user_2",
                                "plan_key": "posthog-code-free",
                                "status": "active",
                                "organization_id": "org_1",
                            }
                        ],
                        "next": None,
                    }
                ),
            ),
        ]

        seat_covered = get_seat_covered_distinct_ids("posthog_code", datetime.date(2026, 7, 9))

        self.assertEqual(seat_covered, {"user_1", "user_2"})
        self.assertEqual(mock_get.call_count, 2)
        first_call_params = mock_get.call_args_list[0].kwargs["params"]
        second_call_params = mock_get.call_args_list[1].kwargs["params"]
        self.assertNotIn("cursor", first_call_params)
        self.assertEqual(second_call_params["cursor"], "cursor_2")

    @patch("products.tasks.backend.billing.requests.get")
    def test_roster_fetch_raises_after_retries_exhausted(self, mock_get):
        """A failing roster fetch must raise, not be treated as an empty (bill-everyone) or full
        (bill-no-one) roster by callers."""
        mock_get.side_effect = requests.exceptions.ConnectionError("boom")

        with self.assertRaises(requests.exceptions.ConnectionError):
            get_seat_covered_distinct_ids("posthog_code", datetime.date(2026, 7, 9))

        self.assertEqual(mock_get.call_count, 3)  # retry tries on _fetch_active_roster_page
