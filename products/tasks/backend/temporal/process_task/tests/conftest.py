"""Shared fixtures for workflow tests."""

import pytest

from posthog.temporal.common.logger import configure_logger

# Import fixtures from activities tests - pytest will discover them here
from products.tasks.backend.temporal.process_task.activities.tests.conftest import (  # noqa: F401
    aorganization,
    ateam,
    github_integration,
    task_workflow,
    test_task,
)


@pytest.fixture(autouse=True)
def configure_logger_auto() -> None:
    """Configure logger when running in a Temporal workflow environment."""
    configure_logger(cache_logger_on_first_use=False)
