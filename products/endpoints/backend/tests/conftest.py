import pytest_asyncio
from asgiref.sync import sync_to_async

# Import temporal test fixtures directly
from posthog.temporal.tests.conftest import aorganization, ateam, auser, temporal_client  # noqa: F401

from products.endpoints.backend.models import Endpoint


@pytest_asyncio.fixture
async def endpoint(ateam, auser):  # noqa: F811
    """Create a test endpoint."""
    endpoint = await sync_to_async(Endpoint.objects.create)(
        name="test_temporal_endpoint",
        team=ateam,
        query={
            "kind": "HogQLQuery",
            "query": "SELECT event, distinct_id FROM events WHERE event = '$pageview' LIMIT 10",
        },
        created_by=auser,
        is_active=True,
    )
    yield endpoint
    await sync_to_async(endpoint.delete)()
