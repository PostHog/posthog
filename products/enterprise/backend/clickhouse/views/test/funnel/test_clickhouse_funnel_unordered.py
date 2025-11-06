import json
from datetime import datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.constants import INSIGHT_FUNNELS
from posthog.models.group.util import create_group
from posthog.test.test_journeys import journeys_for
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.enterprise.backend.api.test.base import LicensedTestMixin
from products.enterprise.backend.clickhouse.views.test.funnel.util import EventPattern, FunnelRequest, get_funnel_ok


class ClickhouseTestUnorderedFunnelGroups(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    @snapshot_clickhouse_queries
    def test_unordered_funnel_with_groups(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="company", group_type_index=1
        )

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )

        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:1",
            properties={},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:2",
            properties={},
        )

        events_by_person = {
            "user_1": [
                {
                    "event": "user signed up",
                    "timestamp": datetime(2020, 1, 3, 14),
                    "properties": {"$group_0": "org:5"},
                },
                {  # same person, different group, so should count as different step 1 in funnel
                    "event": "user signed up",
                    "timestamp": datetime(2020, 1, 10, 14),
                    "properties": {"$group_0": "org:6"},
                },
            ],
            "user_2": [
                {  # different person, same group, so should count as step two in funnel
                    "event": "paid",
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$group_0": "org:5"},
                }
            ],
        }
        journeys_for(events_by_person, self.team)

        params = FunnelRequest(
            events=json.dumps(
                [
                    EventPattern(id="user signed up", type="events", order=0),
                    EventPattern(id="paid", type="events", order=1),
                ]
            ),
            date_from="2020-01-01",
            date_to="2020-01-14",
            aggregation_group_type_index=0,
            funnel_order_type="unordered",
            insight=INSIGHT_FUNNELS,
        )

        result = get_funnel_ok(self.client, self.team.pk, params)

        assert result["Completed 1 step"]["count"] == 2
        assert result["Completed 2 steps"]["count"] == 1
        assert result["Completed 2 steps"]["average_conversion_time"] == 86400
