from django.db import transaction

import structlog

from posthog.models.integration import GitHubIntegration, Integration

from .models import SignalReport

logger = structlog.get_logger(__name__)


def create_task_for_signal_report(sender, instance: SignalReport, created: bool, **kwargs):
    """
    When a SignalReport is created, create an AI coding Task to address the issue.

    Only triggers if the team has a GitHub integration with accessible repositories.
    Uses the top-starred repository from the integration.
    """
    if not created:
        return

    team_id = instance.team_id
    report_id = str(instance.id)
    title = instance.title
    summary = instance.summary

    def do_create_task():
        from products.tasks.backend.models import Task, TaskRun
        from products.tasks.backend.temporal.client import execute_task_processing_workflow

        github_integration = Integration.objects.filter(team_id=team_id, kind="github").first()

        if not github_integration:
            logger.info(
                "signal_report.no_github_integration",
                signal_report_id=report_id,
                team_id=team_id,
            )
            return

        gh = GitHubIntegration(github_integration)
        repository = gh.get_top_starred_repository()

        if not repository:
            logger.info(
                "signal_report.no_repositories",
                signal_report_id=report_id,
                team_id=team_id,
            )
            return

        task_title = title or "Issue from session summary"
        task_description = summary or "An issue was identified from session summary analysis."

        task = Task.objects.create(
            team_id=team_id,
            title=task_title,
            description=task_description,
            origin_product=Task.OriginProduct.SESSION_SUMMARIES,
            github_integration=github_integration,
            repository=repository,
        )

        task_run = task.create_run(environment=TaskRun.Environment.CLOUD)

        execute_task_processing_workflow(
            task_id=str(task.id),
            run_id=str(task_run.id),
            team_id=team_id,
            skip_user_check=True,
        )

        logger.info(
            "signal_report.task_created",
            signal_report_id=report_id,
            task_id=str(task.id),
            task_run_id=str(task_run.id),
            repository=repository,
        )

    transaction.on_commit(do_create_task)
