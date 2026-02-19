import pytest_asyncio
from asgiref.sync import sync_to_async

# Import temporal test fixtures directly
from posthog.temporal.tests.conftest import aorganization, ateam, auser, temporal_client  # noqa: F401

from products.endpoints.backend.models import Endpoint, EndpointVersion


def create_endpoint_with_version(
    name, team, query, created_by, is_active=True, description="", cache_age_seconds=None, current_version=1, **kwargs
):
    """Helper to create an endpoint with its initial version.

    This is the standard way to create endpoints since query data is stored on EndpointVersion.
    """
    endpoint = Endpoint.objects.create(
        name=name,
        team=team,
        created_by=created_by,
        is_active=is_active,
        current_version=current_version,
        **kwargs,
    )
    EndpointVersion.objects.create(
        endpoint=endpoint,
        version=current_version,
        query=query,
        description=description,
        cache_age_seconds=cache_age_seconds,
        created_by=created_by,
    )
    return endpoint


@pytest_asyncio.fixture
async def endpoint(ateam, auser):  # noqa: F811
    """Create a test endpoint."""
    endpoint = await sync_to_async(create_endpoint_with_version)(
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
