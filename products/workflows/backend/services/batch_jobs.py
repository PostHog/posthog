from typing import Any
from uuid import UUID

from products.workflows.backend.facade.contracts import WorkflowBatchJob
from products.workflows.backend.facade.enums import HogFlowBatchJobState
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob


def to_batch_job(job: HogFlowBatchJob) -> WorkflowBatchJob:
    return WorkflowBatchJob(
        id=job.id,
        hog_flow_id=job.hog_flow_id,
        status=HogFlowBatchJobState(job.status),
        filters=job.filters,
        variables=job.variables,
        created_at=job.created_at,
        updated_at=job.updated_at,
        created_by=job.created_by,
    )


def create_batch_job(
    *,
    team_id: int,
    hog_flow_id: UUID,
    created_by_id: int,
    variables: dict[str, Any],
    filters: dict[str, Any],
    status: HogFlowBatchJobState | None = None,
) -> WorkflowBatchJob:
    """Save the job row. Its post_save receiver dispatches the run to the plugin server."""
    job = HogFlowBatchJob.objects.create(
        team_id=team_id,
        hog_flow_id=hog_flow_id,
        created_by_id=created_by_id,
        variables=variables,
        filters=filters,
        **({} if status is None else {"status": status}),
    )
    return to_batch_job(job)
