from uuid import UUID

from products.tasks.backend.logic.services.gateway_usage import record_generation_request, schedule_gateway_usage
from products.tasks.backend.models import TaskRun


def accept_generation_request(*, team_id: int, run_id: UUID, request_id: str) -> bool:
    try:
        record_generation_request(team_id=team_id, run_id=run_id, request_id=request_id)
    except TaskRun.DoesNotExist:
        return False
    schedule_gateway_usage(team_id=team_id, run_id=run_id)
    return True
