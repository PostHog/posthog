import pytest

from temporalio.testing import ActivityEnvironment


@pytest.fixture
def activity_environment():
    return ActivityEnvironment()
