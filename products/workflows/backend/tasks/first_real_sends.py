from django.utils import timezone

from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.first_real_sends import capture_first_real_sends


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def capture_workflow_first_real_sends() -> None:
    capture_first_real_sends(now=timezone.now())
