import re
from typing import Any

from posthog.clickhouse.query_tagging import Product
from posthog.temporal.health_checks.rollups.framework import DailyRollup

from products.web_analytics.backend.models.health_rollups import HostProxyDaily
from products.web_analytics.backend.rollups.properties import event_property, has_event_property

MAX_HOST_LENGTH = 253
HOST_PATTERN = r"^[A-Za-z0-9._\-]+(?::\d{1,5})?$"
_HOST_RE = re.compile(HOST_PATTERN)

MAX_HOSTS_PER_TEAM_DAY = 50

# The busiest hosts of each team keep both of their rows. A host is proxied when any of its events was,
# so a cap per proxy state could drop the one proxied row of a host and keep its unproxied row.
HOST_PROXY_FILL_SQL = """
SELECT team_id, host, has_custom_api_host, event_count
FROM (
    SELECT
        team_id,
        host,
        has_custom_api_host,
        event_count,
        dense_rank() OVER (PARTITION BY team_id ORDER BY host_event_count DESC, host) AS host_rank
    FROM (
        SELECT
            team_id,
            {host} AS host,
            {has_custom_api_host} AS has_custom_api_host,
            count() AS event_count,
            sum(count()) OVER (PARTITION BY team_id, host) AS host_event_count
        FROM events
        WHERE team_id >= %(team_id_start)s
          AND team_id < %(team_id_end)s
          AND timestamp >= %(day_start)s
          AND timestamp < %(day_end)s
          AND event IN ('$pageview', '$screen')
          AND length(host) BETWEEN 1 AND %(max_host_length)s
          AND match(host, %(host_pattern)s)
        GROUP BY team_id, host, has_custom_api_host
    )
)
WHERE host_rank <= %(max_hosts)s
"""


def is_valid_host(host: str) -> bool:
    if not host or len(host) > MAX_HOST_LENGTH:
        return False
    return bool(_HOST_RE.fullmatch(host))


class HostProxyDailyRollup(DailyRollup):
    model = HostProxyDaily
    product = Product.WEB_ANALYTICS
    columns = ("team_id", "day", "host", "has_custom_api_host", "event_count")
    retention_days = 35

    @classmethod
    def fill_sql(cls) -> str:
        return HOST_PROXY_FILL_SQL.format(
            host=event_property("$host"), has_custom_api_host=has_event_property("$lib_custom_api_host")
        )

    @classmethod
    def fill_params(cls) -> dict[str, Any]:
        return {
            "max_host_length": MAX_HOST_LENGTH,
            "host_pattern": HOST_PATTERN,
            "max_hosts": MAX_HOSTS_PER_TEAM_DAY,
        }
