from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from posthog.models.team.team import Team
from products.issue_tracker.backend.models import Issue


class Command(BaseCommand):
    help = "Generate demo data for the issue tracker"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to generate issues for",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing issues before generating new ones",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        clear_existing = options["clear"]

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Team with ID {team_id} does not exist!"))
            return

        if clear_existing:
            deleted_count = Issue.objects.filter(team=team).delete()[0]
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} existing issues"))

        # Demo issues data from demoData.ts
        demo_issues = [
            {
                "title": "Memory leak in session recording module",
                "description": "Users reporting browser crashes during long recording sessions, memory usage keeps growing",
                "status": Issue.Status.BACKLOG,
                "origin_product": Issue.OriginProduct.ERROR_TRACKING,
                "position": 1,
                "created_at": parse_datetime("2024-01-15T10:30:00Z"),
                "updated_at": parse_datetime("2024-01-15T10:30:00Z"),
            },
            {
                "title": "Add dark mode toggle to settings",
                "description": "User requested feature to enable dark mode across the entire application interface",
                "status": Issue.Status.BACKLOG,
                "origin_product": Issue.OriginProduct.USER_CREATED,
                "position": 2,
                "created_at": parse_datetime("2024-01-14T09:15:00Z"),
                "updated_at": parse_datetime("2024-01-14T09:15:00Z"),
            },
            {
                "title": "Add a new form to the homepage to collect user details",
                "description": "Add a new form to the homepage to collect user details. Email, name, and a checkbox to opt in to marketing emails, the data can just alert, no need to store it.. Make sure it is behind a feature flag.",
                "status": Issue.Status.BACKLOG,
                "origin_product": Issue.OriginProduct.EVAL_CLUSTERS,
                "position": 0,
                "created_at": parse_datetime("2024-01-13T14:20:00Z"),
                "updated_at": parse_datetime("2024-01-16T11:45:00Z"),
            },
            {
                "title": "User cannot access dashboard after password reset",
                "description": "Multiple support tickets about users being locked out after password reset flow",
                "status": Issue.Status.DONE,
                "origin_product": Issue.OriginProduct.SUPPORT_QUEUE,
                "position": 0,
                "created_at": parse_datetime("2024-01-12T16:00:00Z"),
                "updated_at": parse_datetime("2024-01-17T08:30:00Z"),
            },
            {
                "title": "Fix JavaScript error in event tracking",
                "description": "TypeError: Cannot read property of undefined in tracking script causing events to fail",
                "status": Issue.Status.DONE,
                "origin_product": Issue.OriginProduct.ERROR_TRACKING,
                "position": 0,
                "created_at": parse_datetime("2024-01-10T11:00:00Z"),
                "updated_at": parse_datetime("2024-01-19T12:00:00Z"),
            },
            {
                "title": "Custom dashboard widget for conversion metrics",
                "description": "User-requested feature to create custom widgets showing conversion funnel data",
                "status": Issue.Status.BACKLOG,
                "origin_product": Issue.OriginProduct.USER_CREATED,
                "position": 3,
                "created_at": parse_datetime("2024-01-09T10:15:00Z"),
                "updated_at": parse_datetime("2024-01-09T10:15:00Z"),
            },
            {
                "title": "Background color of the dashboard is not correct",
                "description": "The background color of the dashboard is not correct, it should be red",
                "status": Issue.Status.BACKLOG,
                "origin_product": Issue.OriginProduct.USER_CREATED,
                "position": 4,
                "created_at": parse_datetime("2024-01-08T15:30:00Z"),
                "updated_at": parse_datetime("2024-01-08T15:30:00Z"),
            },
        ]

        created_issues = []
        for issue_data in demo_issues:
            issue = Issue.objects.create(team=team, **issue_data)
            created_issues.append(issue)

        self.stdout.write(
            self.style.SUCCESS(f"Successfully created {len(created_issues)} demo issues for team '{team.name}'")
        )

        for issue in created_issues:
            self.stdout.write(f"  - {issue.title} ({issue.get_status_display()})")
