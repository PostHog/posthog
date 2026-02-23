from celery import shared_task


@shared_task(ignore_result=True)
def process_twig_mention(event: dict, integration_id: int) -> None:
    """Process a Twig app_mention event asynchronously (local region only)."""
    from posthog.models.integration import Integration

    from products.slack_app.backend.api import handle_twig_app_mention

    integration = Integration.objects.select_related("team", "team__organization").get(id=integration_id)
    handle_twig_app_mention(event, integration)
