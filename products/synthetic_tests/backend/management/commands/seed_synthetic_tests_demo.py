"""
Seed demo synthetic tests + run history for the hackathon demo.

Usage:
    python manage.py seed_synthetic_tests_demo --team-id 2
    python manage.py seed_synthetic_tests_demo --team-id 2 --wipe

Creates 4 tests with realistic run history (mix of green/red) so the list view
and a test detail page are demo-ready without waiting for the scheduler.
"""

import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from products.synthetic_tests.backend.models import SyntheticTest, SyntheticTestRun

DEMO_TESTS = [
    {
        "name": "Cloud signup smoke",
        "target_url": "https://us.posthog.com/signup",
        "steps": [
            {"type": "navigate", "url": "https://us.posthog.com/signup"},
            {"type": "wait_for_selector", "selector": "[data-attr=signup-email]"},
            {"type": "type", "selector": "[data-attr=signup-email]", "value": "test+synth@posthog.com"},
            {"type": "type", "selector": "[data-attr=signup-password]", "value": "Hackathon123!"},
            {"type": "click", "selector": "[data-attr=signup-submit]"},
            {"type": "wait_for_selector", "selector": "[data-attr=onboarding-step-platform]"},
            {"type": "assert_url_contains", "value": "/onboarding"},
        ],
        "schedule_cron": "*/5 * * * *",
        "failure_rate": 0.05,
    },
    {
        "name": "Pricing page loads",
        "target_url": "https://posthog.com/pricing",
        "steps": [
            {"type": "navigate", "url": "https://posthog.com/pricing"},
            {"type": "wait_for_selector", "selector": "[data-attr=pricing-table]"},
            {"type": "assert_text_visible", "value": "Free for first"},
        ],
        "schedule_cron": "0 * * * *",
        "failure_rate": 0.0,
    },
    {
        "name": "Docs search works",
        "target_url": "https://posthog.com/docs",
        "steps": [
            {"type": "navigate", "url": "https://posthog.com/docs"},
            {"type": "click", "selector": "[data-attr=docs-search-input]"},
            {"type": "type", "selector": "[data-attr=docs-search-input]", "value": "session replay"},
            {"type": "wait_for_selector", "selector": "[data-attr=search-result]"},
            {"type": "assert_element_exists", "selector": "[data-attr=search-result]"},
        ],
        "schedule_cron": "0 * * * *",
        "failure_rate": 0.1,
    },
    {
        "name": "Broken: checkout flow (demo)",
        "target_url": "https://app.example.com/checkout",
        "steps": [
            {"type": "navigate", "url": "https://app.example.com/checkout"},
            {"type": "click", "selector": "[data-attr=add-to-cart]"},
            {"type": "click", "selector": "[data-attr=checkout]"},
            {"type": "wait_for_selector", "selector": "[data-attr=payment-form]"},
            {"type": "assert_url_contains", "value": "/success"},
        ],
        "schedule_cron": "*/15 * * * *",
        "failure_rate": 1.0,  # always fails — shows the red state in demo
    },
]

RUN_HISTORY_COUNT = 24


class Command(BaseCommand):
    help = "Seed demo synthetic tests with realistic run history."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--wipe", action="store_true", help="Delete existing synthetic tests for this team first.")

    def handle(self, *args, **options) -> None:
        team_id: int = options["team_id"]
        if options["wipe"]:
            count, _ = SyntheticTest.objects.filter(team_id=team_id).delete()
            self.stdout.write(self.style.WARNING(f"Deleted {count} existing synthetic tests"))

        now = timezone.now()
        for fixture in DEMO_TESTS:
            test = SyntheticTest.objects.create(
                team_id=team_id,
                name=fixture["name"],
                target_url=fixture["target_url"],
                steps=fixture["steps"],
                schedule_cron=fixture["schedule_cron"],
                status=SyntheticTest.Status.ACTIVE,
                next_run_at=now + timedelta(minutes=5),
                last_run_at=now - timedelta(minutes=random.randint(1, 30)),
            )
            self._seed_run_history(test, fixture["failure_rate"], now)
            self.stdout.write(self.style.SUCCESS(f"  ✔ {fixture['name']}"))

        self.stdout.write(self.style.SUCCESS(f"\nSeeded {len(DEMO_TESTS)} tests for team {team_id}"))

    def _seed_run_history(self, test: SyntheticTest, failure_rate: float, now) -> None:
        cadence_min = self._cron_to_minutes(test.schedule_cron)
        for idx in range(RUN_HISTORY_COUNT):
            started = now - timedelta(minutes=cadence_min * (idx + 1))
            failed = random.random() < failure_rate
            status_value = SyntheticTestRun.Status.FAILED if failed else SyntheticTestRun.Status.PASSED
            duration = random.randint(900, 2800) if not failed else random.randint(4500, 6000)
            SyntheticTestRun.objects.create(
                synthetic_test=test,
                started_at=started,
                finished_at=started + timedelta(milliseconds=duration),
                status=status_value,
                duration_ms=duration,
                error_message=(f"Selector [data-attr=payment-form] timed out after 5000ms" if failed else ""),
                error_step_index=(len(test.steps) - 2) if failed else None,
            )

    @staticmethod
    def _cron_to_minutes(cron: str) -> int:
        """Cheap cadence lookup for fixtures."""
        if cron.startswith("*/5"):
            return 5
        if cron.startswith("*/15"):
            return 15
        if cron.startswith("0 *"):
            return 60
        return 60
