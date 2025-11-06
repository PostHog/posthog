from posthog.queries.stickiness.stickiness import Stickiness

from products.enterprise.backend.clickhouse.queries.stickiness.stickiness_actors import ClickhouseStickinessActors
from products.enterprise.backend.clickhouse.queries.stickiness.stickiness_event_query import (
    ClickhouseStickinessEventsQuery,
)


class ClickhouseStickiness(Stickiness):
    event_query_class = ClickhouseStickinessEventsQuery
    actor_query_class = ClickhouseStickinessActors
