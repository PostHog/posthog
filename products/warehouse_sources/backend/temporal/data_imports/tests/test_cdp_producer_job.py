import pytest

from posthog.temporal.utils import CDPProducerWorkflowInputs

from products.warehouse_sources.backend.temporal.data_imports.cdp_producer_job import produce_to_cdp_kafka_activity


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_produce_to_cdp_kafka_activity_requires_a_schema_or_saved_query(team):
    inputs = CDPProducerWorkflowInputs(team_id=team.id, job_id="job-id", schema_id=None, saved_query_id=None)

    with pytest.raises(ValueError, match="CDP producer needs either a schema_id or a saved_query_id"):
        await produce_to_cdp_kafka_activity(inputs)
