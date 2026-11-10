"""How far trace span ingestion has reached, so a traces alert never reads a window still being written."""

import datetime as dt

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Product
from posthog.models import Team

from products.alerts_platform.backend.facade.ingestion_checkpoint import fetch_ingestion_checkpoint


def fetch_traces_checkpoint(
    team: Team, *, ch_user: ClickHouseUser = ClickHouseUser.DEFAULT, max_execution_time: int | None = None
) -> dt.datetime | None:
    return fetch_ingestion_checkpoint(
        team,
        consumption_table=("posthog", "trace_spans_kafka_metrics"),
        product=Product.TRACING,
        source="traces_alert",
        ch_user=ch_user,
        max_execution_time=max_execution_time,
    )
