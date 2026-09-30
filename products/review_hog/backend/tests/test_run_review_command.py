from io import StringIO

from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase

from parameterized import parameterized

from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL


class TestRunReviewCommand(SimpleTestCase):
    @parameterized.expand(
        [
            ("default", [], REVIEW_MODE_FULL, False),
            ("full", ["--review-mode", "full"], REVIEW_MODE_FULL, False),
            ("flash", ["--review-mode", "flash"], REVIEW_MODE_FLASH, False),
            ("flash_publish", ["--review-mode", "flash", "--publish"], REVIEW_MODE_FLASH, True),
        ]
    )
    def test_dispatches_selected_mode_with_opt_in_publishing(
        self, _name: str, args: list[str], expected_mode: str, expected_publish: bool
    ) -> None:
        output = StringIO()
        with patch(
            "products.review_hog.backend.management.commands.run_review.execute_review_pr_workflow",
            return_value="report-id",
        ) as execute:
            call_command(
                "run_review",
                "--pr-url",
                "https://github.com/PostHog/posthog/pull/7",
                "--team-id",
                "1",
                "--user-id",
                "2",
                *args,
                stdout=output,
            )

        execute.assert_called_once_with(
            pr_url="https://github.com/PostHog/posthog/pull/7",
            team_id=1,
            user_id=2,
            publish=expected_publish,
            acting_user_id=2,
            review_mode=expected_mode,
        )
        assert f"· {expected_mode} · {'publish' if expected_publish else 'no-publish'}" in output.getvalue()
