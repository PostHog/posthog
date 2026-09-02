import uuid
import random
import functools

import pytest

from django.conf import settings

import aioboto3
import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team

TEST_ROOT_BUCKET = "test-ducklake"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


@pytest.fixture
def bucket_name(request) -> str:
    try:
        return request.param
    except AttributeError:
        return f"{TEST_ROOT_BUCKET}-{uuid.uuid4()}"


@pytest_asyncio.fixture
async def minio_client(bucket_name):
    async with create_test_client(
        "s3",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ) as client:
        try:
            await client.head_bucket(Bucket=bucket_name)
        except Exception:
            await client.create_bucket(Bucket=bucket_name)

        yield client


@pytest_asyncio.fixture
async def aorganization():
    org = await sync_to_async(Organization.objects.create)(
        name=f"DuckLakeTestOrg-{random.randint(1, 99999)}", is_ai_data_processing_approved=True
    )

    yield org

    await sync_to_async(org.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization, name=f"DuckLakeTestTeam-{random.randint(1, 99999)}"
    )

    yield team

    await sync_to_async(team.delete)()


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return ActivityEnvironment()
