# The workflow tests use core's temporal test fixtures: a team whose organization approved AI data
# processing, a live Temporal client, and the logger setup every temporal test runs under.
import pytest

from posthog.models import OrganizationMembership
from posthog.temporal.conftest import _restore_structlog_config  # noqa: F401
from posthog.temporal.tests.conftest import (  # noqa: F401
    _ignore_sigpipe,
    configure_logger_auto,
    organization,
    team,
    temporal_client,
)


@pytest.fixture
def user(request, base_test_mixin_fixture):
    # The temporal team lives in its own organization, so the shared user is made a member of it.
    # Deliveries run as the subscription's creator and stop when that creator is not a member.
    user = base_test_mixin_fixture.user
    temporal_team = request.getfixturevalue("team")
    OrganizationMembership.objects.get_or_create(organization_id=temporal_team.organization_id, user=user)
    return user
