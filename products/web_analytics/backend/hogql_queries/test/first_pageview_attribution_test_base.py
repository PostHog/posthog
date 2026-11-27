from typing import TYPE_CHECKING

from posthog.test.base import _create_event, _create_person
from unittest.mock import patch

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7

from products.web_analytics.backend.hogql_queries.first_pageview_flag import FIRST_PAGEVIEW_ATTRIBUTION_FEATURE_FLAG

if TYPE_CHECKING:
    from posthog.models import Team


class FirstPageviewAttributionTestMixin:
    team: "Team"

    def _seed_ssr_poisoned_session(self) -> None:
        # The $feature_flag_called fires before the first pageview. Raw_sessions v2
        # rows written before migration 0396 attribute the session to it and blank
        # the entry UTMs, and the extra row below stands in for such a row. This
        # session reads as Direct under entry attribution and Paid Search under
        # first-pageview attribution.
        session_id = str(uuid7("2024-06-26"))
        _create_person(team_id=self.team.pk, distinct_ids=["d1"], properties={"name": "d1"})
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="d1",
            timestamp="2024-06-26T10:00:00",
            properties={"$session_id": session_id, "$referring_domain": "$direct"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d1",
            timestamp="2024-06-26T10:00:05",
            properties={
                "$session_id": session_id,
                "$current_url": "http://example.com/landing",
                "$pathname": "/landing",
                "$referring_domain": "google.com",
                "utm_source": "google",
                "utm_medium": "cpc",
                "gad_source": "1",
            },
        )
        sync_execute(
            """
            INSERT INTO raw_sessions (
                team_id, session_id_v7, min_timestamp, max_timestamp, entry_url, initial_referring_domain,
                initial_utm_source, initial_utm_medium, initial_gad_source
            )
            SELECT
                %(team_id)s,
                toUInt128(toUUID(%(session_id)s)),
                ts,
                ts,
                initializeAggregation('argMinState', '', ts),
                initializeAggregation('argMinState', '$direct', ts),
                initializeAggregation('argMinState', '', ts),
                initializeAggregation('argMinState', '', ts),
                initializeAggregation('argMinState', '', ts)
            FROM (SELECT toDateTime64('2024-06-26 10:00:00', 6, 'UTC') AS ts)
            """,
            {"team_id": self.team.pk, "session_id": session_id},
        )

    def _patch_first_pageview_flag(self, enabled=True):
        return patch(
            "products.web_analytics.backend.hogql_queries.first_pageview_flag.posthoganalytics.feature_enabled",
            side_effect=lambda key, *args, **kwargs: enabled and key == FIRST_PAGEVIEW_ATTRIBUTION_FEATURE_FLAG,
        )
