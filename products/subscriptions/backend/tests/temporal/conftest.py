# The workflow tests use core's temporal test fixtures: a team whose organization approved AI data
# processing, a live Temporal client, and the logger setup every temporal test runs under.
from posthog.temporal.conftest import _restore_structlog_config  # noqa: F401
from posthog.temporal.tests.conftest import (  # noqa: F401
    _ignore_sigpipe,
    configure_logger_auto,
    organization,
    team,
    temporal_client,
)
