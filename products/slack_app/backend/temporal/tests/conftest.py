# These tests ran under posthog/temporal/tests/conftest.py before they moved here, so re-import the fixtures they rely on.
from posthog.temporal.tests.conftest import _ignore_sigpipe, configure_logger_auto, temporal_client  # noqa: F401
