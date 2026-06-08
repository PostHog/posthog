import random

import pytest

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.temporal.common.logger import configure_logger


@pytest_asyncio.fixture(autouse=True, scope="module", loop_scope="module")
async def configure_logger_auto() -> None:
    configure_logger(cache_logger_on_first_use=False)


@pytest.fixture
def organization():
    org = Organization.objects.create(
        name=f"PulseTestOrg-{random.randint(1, 99999)}", is_ai_data_processing_approved=True
    )
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    team = Team.objects.create(organization=organization, name=f"PulseTestTeam-{random.randint(1, 99999)}")
    yield team
    team.delete()


@pytest_asyncio.fixture
async def aorganization():
    org = await sync_to_async(Organization.objects.create)(
        name=f"PulseTestOrg-{random.randint(1, 99999)}", is_ai_data_processing_approved=True
    )
    yield org
    await sync_to_async(org.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization, name=f"PulseTestTeam-{random.randint(1, 99999)}"
    )
    yield team
    await sync_to_async(team.delete)()
