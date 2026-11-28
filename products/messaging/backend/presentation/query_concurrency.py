from collections.abc import Iterator
from contextlib import contextmanager

from rest_framework.exceptions import Throttled

from posthog.api.query import CONCURRENCY_LIMIT_RETRY_AFTER_SECONDS, CONCURRENCY_LIMIT_USER_MESSAGE
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.models.team import Team

from products.messaging.backend.facade.transactional_email_log import hold_query_slots


@contextmanager
def query_concurrency_slots(team: Team) -> Iterator[None]:
    """Hold the log's query slots, and answer 429 when they are full."""
    try:
        with hold_query_slots(team):
            yield
    except ConcurrencyLimitExceeded as error:
        raise Throttled(wait=CONCURRENCY_LIMIT_RETRY_AFTER_SECONDS, detail=CONCURRENCY_LIMIT_USER_MESSAGE) from error
