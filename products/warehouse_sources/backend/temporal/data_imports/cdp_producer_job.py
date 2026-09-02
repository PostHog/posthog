import json
from datetime import timedelta

from prometheus_client import Counter
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.utils import CDPProducerWorkflowInputs

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer import CDPProducer

LOGGER = get_logger(__name__)

CDP_PRODUCER_RUNS_TOTAL = Counter(
    "warehouse_cdp_producer_runs_total",
    "CDP producer activity attempts by outcome",
    labelnames=["team_id", "outcome"],
)


@activity.defn
async def produce_to_cdp_kafka_activity(inputs: CDPProducerWorkflowInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    if inputs.saved_query_id is not None:
        producer = CDPProducer.for_view(
            team_id=inputs.team_id, saved_query_id=inputs.saved_query_id, job_id=inputs.job_id, logger=logger
        )
    elif inputs.schema_id is not None:
        producer = CDPProducer.for_source(
            team_id=inputs.team_id, schema_id=inputs.schema_id, job_id=inputs.job_id, logger=logger
        )
    else:
        raise ValueError("CDP producer needs either a schema_id or a saved_query_id")

    try:
        await producer.produce_to_kafka_from_s3()
    except Exception:
        CDP_PRODUCER_RUNS_TOTAL.labels(team_id=str(inputs.team_id), outcome="failed").inc()
        raise
    CDP_PRODUCER_RUNS_TOTAL.labels(team_id=str(inputs.team_id), outcome="completed").inc()


@workflow.defn(name="dwh-cdp-producer-job")
class CDPProducerJobWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> CDPProducerWorkflowInputs:
        loaded = json.loads(inputs[0])
        return CDPProducerWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: CDPProducerWorkflowInputs) -> None:
        await workflow.execute_activity(
            produce_to_cdp_kafka_activity,
            inputs,
            start_to_close_timeout=timedelta(hours=24),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
