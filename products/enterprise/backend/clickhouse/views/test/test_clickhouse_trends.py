import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Union

import pytest
from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    also_test_with_materialized_columns,
    snapshot_clickhouse_queries,
)
from unittest.case import skip
from unittest.mock import ANY

from django.core.cache import cache
from django.test import Client

from posthog.api.test.test_cohort import create_cohort_ok
from posthog.api.test.test_event_definition import create_organization, create_team, create_user
from posthog.models.group.util import create_group
from posthog.models.instance_setting import set_instance_setting
from posthog.models.team import Team
from posthog.test.test_journeys import journeys_for, update_or_create_person
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.enterprise.backend.api.test.base import LicensedTestMixin


@pytest.mark.django_db
@pytest.mark.ee
def test_includes_only_intervals_within_range(client: Client):
    """
    This is the case highlighted by https://github.com/PostHog/posthog/issues/2675

    Here the issue is that we request, for instance, 14 days as the
    date_from, display at weekly intervals but previously we
    were displaying 4 ticks on the date axis. If we were exactly on the
    beginning of the week for two weeks then we'd want 2 ticks.
    Otherwise we would have 3 ticks as the range would be intersecting
    with three weeks. We should never need to display 4 ticks.
    """
    organization = create_organization(name="test org")
    team = create_team(organization=organization)
    user = create_user("user", "pass", organization)

    client.force_login(user)
    cache.clear()

    #  I'm creating a cohort here so that I can use as a breakdown, just because
    #  this is what was used demonstrated in
    #  https://github.com/PostHog/posthog/issues/2675 but it might not be the
    #  simplest way to reproduce

    # "2021-09-19" is a sunday, i.e. beginning of week
    with freeze_time("2021-09-20T16:00:00"):
        #  First identify as a member of the cohort
        distinct_id = "abc"
        update_or_create_person(
            distinct_ids=[distinct_id],
            team_id=team.id,
            properties={"cohort_identifier": 1},
        )
        cohort = create_cohort_ok(
            client=client,
            team_id=team.id,
            name="test cohort",
            groups=[{"properties": [{"key": "cohort_identifier", "value": "1", "type": "person"}]}],
        )

        journeys_for(
            events_by_person={
                distinct_id: [
                    {"event": "$pageview", "timestamp": "2021-09-04"},
                    {"event": "$pageview", "timestamp": "2021-09-05"},
                    {"event": "$pageview", "timestamp": "2021-09-12"},
                    {"event": "$pageview", "timestamp": "2021-09-19"},
                ]
            },
            team=team,
            create_people=False,
        )

        trends = get_trends_ok(
            client,
            team=team,
            request=TrendsRequestBreakdown(
                date_from="-14days",
                date_to="2021-09-21",
                interval="week",
                insight="TRENDS",
                breakdown=json.dumps([cohort["id"]]),
                breakdown_type="cohort",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            ),
        )
        assert trends == trends | {
            "is_cached": False,
            "last_refresh": "2021-09-20T16:00:00Z",
            "next": None,
            "timezone": "UTC",
            "result": [
                {
                    "action": ANY,
                    "breakdown_value": cohort["id"],
                    "label": "test cohort",
                    "count": 2.0,
                    "data": [0.0, 1.0, 1.0],
                    "labels": ["6–11 Sep", "12–18 Sep", "19–21 Sep"],
                    "days": ["2021-09-05", "2021-09-12", "2021-09-19"],
                    "filter": ANY,
                    "order": 0,
                }
            ],
        }


@pytest.mark.django_db
@pytest.mark.ee
def test_can_specify_number_of_smoothing_intervals(client: Client):
    """
    The Smoothing feature should allow specifying a number of intervals over
    which we will provide smoothing of the aggregated trend data.
    """
    organization = create_organization(name="test org")
    team = create_team(organization=organization)
    user = create_user("user", "pass", organization)

    client.force_login(user)

    with freeze_time("2021-09-20T16:00:00"):
        journeys_for(
            events_by_person={
                "abc": [
                    {"event": "$pageview", "timestamp": "2021-09-01"},
                    {"event": "$pageview", "timestamp": "2021-09-01"},
                    {"event": "$pageview", "timestamp": "2021-09-02"},
                    {"event": "$pageview", "timestamp": "2021-09-03"},
                    {"event": "$pageview", "timestamp": "2021-09-03"},
                    {"event": "$pageview", "timestamp": "2021-09-03"},
                ]
            },
            team=team,
        )

        interval_3_trend = get_trends_ok(
            client,
            team=team,
            request=TrendsRequest(
                date_from="2021-09-01",
                date_to="2021-09-03",
                interval="day",
                insight="TRENDS",
                display="ActionsLineGraph",
                smoothing_intervals=3,
                events=[
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                    }
                ],
            ),
        )

        assert interval_3_trend == interval_3_trend | {
            "is_cached": False,
            "last_refresh": "2021-09-20T16:00:00Z",
            "next": None,
            "timezone": "UTC",
            "result": [
                {
                    "action": ANY,
                    "label": "$pageview",
                    "count": 5,
                    "data": [2.0, 1, 2.0],
                    "labels": ["1-Sep-2021", "2-Sep-2021", "3-Sep-2021"],
                    "days": ["2021-09-01", "2021-09-02", "2021-09-03"],
                    "filter": ANY,
                    "order": 0,
                }
            ],
        }

        interval_2_trend = get_trends_ok(
            client,
            team=team,
            request=TrendsRequest(
                date_from="2021-09-01",
                date_to="2021-09-03",
                interval="day",
                insight="TRENDS",
                display="ActionsLineGraph",
                smoothing_intervals=2,
                events=[
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                    }
                ],
            ),
        )

        assert interval_2_trend == interval_2_trend | {
            "is_cached": False,
            "last_refresh": "2021-09-20T16:00:00Z",
            "next": None,
            "timezone": "UTC",
            "result": [
                {
                    "action": ANY,
                    "label": "$pageview",
                    "count": 5,
                    "data": [2.0, 1, 2.0],
                    "labels": ["1-Sep-2021", "2-Sep-2021", "3-Sep-2021"],
                    "days": ["2021-09-01", "2021-09-02", "2021-09-03"],
                    "filter": ANY,
                    "order": 0,
                }
            ],
        }

        interval_1_trend = get_trends_ok(
            client,
            team=team,
            request=TrendsRequest(
                date_from="2021-09-01",
                date_to="2021-09-03",
                interval="day",
                insight="TRENDS",
                display="ActionsLineGraph",
                smoothing_intervals=1,
                events=[
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                    }
                ],
            ),
        )

        assert interval_1_trend == interval_1_trend | {
            "is_cached": False,
            "last_refresh": "2021-09-20T16:00:00Z",
            "next": None,
            "timezone": "UTC",
            "result": [
                {
                    "action": {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": ANY,
                        "properties": {},
                        "days": ["2021-09-01T00:00:00Z", "2021-09-02T00:00:00Z", "2021-09-03T00:00:00Z"],
                    },
                    "label": "$pageview",
                    "count": 6.0,
                    "data": [2, 1, 3],
                    "labels": ["1-Sep-2021", "2-Sep-2021", "3-Sep-2021"],
                    "days": ["2021-09-01", "2021-09-02", "2021-09-03"],
                    "filter": ANY,
                    "order": 0,
                }
            ],
        }


@pytest.mark.django_db
@pytest.mark.ee
def test_smoothing_intervals_copes_with_null_values(client: Client):
    """
    The Smoothing feature should allow specifying a number of intervals over
    which we will provide smoothing of the aggregated trend data.
    """
    organization = create_organization(name="test org")
    team = create_team(organization=organization)
    user = create_user("user", "pass", organization)

    client.force_login(user)
    cache.clear()

    with freeze_time("2021-09-20T16:00:00"):
        journeys_for(
            events_by_person={
                "abc": [
                    {"event": "$pageview", "timestamp": "2021-09-01"},
                    {"event": "$pageview", "timestamp": "2021-09-01"},
                    {"event": "$pageview", "timestamp": "2021-09-01"},
                    # No events on 2 Sept
                    {"event": "$pageview", "timestamp": "2021-09-03"},
                    {"event": "$pageview", "timestamp": "2021-09-03"},
                    {"event": "$pageview", "timestamp": "2021-09-03"},
                ]
            },
            team=team,
        )

        interval_3_trend = get_trends_ok(
            client,
            team=team,
            request=TrendsRequest(
                date_from="2021-09-01",
                date_to="2021-09-03",
                interval="day",
                insight="TRENDS",
                display="ActionsLineGraph",
                smoothing_intervals=3,
                events=[
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                    }
                ],
            ),
        )

        assert interval_3_trend == interval_3_trend | {
            "is_cached": False,
            "last_refresh": "2021-09-20T16:00:00Z",
            "next": None,
            "timezone": "UTC",
            "result": [
                {
                    "action": ANY,
                    "label": "$pageview",
                    "count": 6.0,
                    "data": [3.0, 1.0, 2.0],
                    "labels": ["1-Sep-2021", "2-Sep-2021", "3-Sep-2021"],
                    "days": ["2021-09-01", "2021-09-02", "2021-09-03"],
                    "filter": ANY,
                    "order": 0,
                }
            ],
        }

        interval_1_trend = get_trends_ok(
            client,
            team=team,
            request=TrendsRequest(
                date_from="2021-09-01",
                date_to="2021-09-03",
                interval="day",
                insight="TRENDS",
                display="ActionsLineGraph",
                smoothing_intervals=1,
                events=[
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                    }
                ],
            ),
        )

        assert interval_1_trend == interval_1_trend | {
            "is_cached": False,
            "last_refresh": "2021-09-20T16:00:00Z",
            "next": None,
            "timezone": "UTC",
            "result": [
                {
                    "action": ANY,
                    "label": "$pageview",
                    "count": 6.0,
                    "data": [3.0, 0.0, 3.0],
                    "labels": ["1-Sep-2021", "2-Sep-2021", "3-Sep-2021"],
                    "days": ["2021-09-01", "2021-09-02", "2021-09-03"],
                    "filter": ANY,
                    "order": 0,
                }
            ],
        }


@dataclass
class TrendsRequest:
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    interval: Optional[str] = None
    insight: Optional[str] = None
    display: Optional[str] = None
    compare: Optional[bool] = None
    events: list[dict[str, Any]] = field(default_factory=list)
    properties: list[dict[str, Any]] = field(default_factory=list)
    smoothing_intervals: Optional[int] = 1
    refresh: Optional[bool] = False


@dataclass
class TrendsRequestBreakdown(TrendsRequest):
    breakdown: Optional[Union[list[int], str]] = None
    breakdown_type: Optional[str] = None


def get_trends(client, request: Union[TrendsRequestBreakdown, TrendsRequest], team: Team):
    data: dict[str, Any] = {
        "date_from": request.date_from,
        "date_to": request.date_to,
        "interval": request.interval,
        "insight": request.insight,
        "display": request.display,
        "compare": request.compare,
        "events": json.dumps(request.events),
        "properties": json.dumps(request.properties),
        "smoothing_intervals": request.smoothing_intervals,
        "refresh": request.refresh,
    }

    if isinstance(request, TrendsRequestBreakdown):
        data["breakdown"] = request.breakdown
        data["breakdown_type"] = request.breakdown_type

    filtered_data = {k: v for k, v in data.items() if v is not None}

    return client.get(f"/api/projects/{team.id}/insights/trend/", data=filtered_data)


def get_trends_ok(client: Client, request: TrendsRequest, team: Team):
    response = get_trends(client=client, request=request, team=team)
    assert response.status_code == 200, response.content
    return response.json()


@dataclass
class NormalizedTrendResult:
    value: float
    label: str
    breakdown_value: Optional[Union[str, int]]


def get_trends_time_series_ok(
    client: Client, request: TrendsRequest, team: Team, with_order: bool = False
) -> dict[str, dict[str, NormalizedTrendResult]]:
    data = get_trends_ok(client=client, request=request, team=team)
    res = {}
    for item in data["result"]:
        collect_dates = {}
        for idx, date in enumerate(item["days"]):
            collect_dates[date] = NormalizedTrendResult(
                value=item["data"][idx],
                label=item["labels"][idx],
                breakdown_value=item.get("breakdown_value", None),
            )
        suffix = " - {}".format(item["compare_label"]) if item.get("compare_label") else ""
        if with_order:
            suffix += " - {}".format(item["action"]["order"]) if item["action"].get("order") is not None else ""
        res["{}{}".format(item["label"], suffix)] = collect_dates

    return res


def get_trends_aggregate_ok(client: Client, request: TrendsRequest, team: Team) -> dict[str, NormalizedTrendResult]:
    data = get_trends_ok(client=client, request=request, team=team)
    res = {}
    for item in data["result"]:
        res[item["label"]] = NormalizedTrendResult(
            value=item["aggregated_value"],
            label=item["action"]["name"],
            breakdown_value=item.get("breakdown_value", None),
        )

    return res


class ClickhouseTestTrends(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    @snapshot_clickhouse_queries
    def test_insight_trends_basic(self):
        events_by_person = {
            "1": [{"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3)}],
            "2": [{"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3)}],
        }
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data = get_trends_time_series_ok(self.client, request, self.team)

        assert data["$pageview"]["2012-01-13"].value == 0
        assert data["$pageview"]["2012-01-14"].value == 2
        assert data["$pageview"]["2012-01-14"].label == "14-Jan-2012"
        assert data["$pageview"]["2012-01-15"].value == 0

    def test_insight_trends_entity_overlap(self):
        events_by_person = {
            "1": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2012, 1, 14, 3),
                    "properties": {"key": "val"},
                }
            ],
            "2": [{"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3)}],
            "3": [{"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3)}],
        }
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    },
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 1,
                        "properties": [{"key": "key", "value": "val"}],
                        "math_property": None,
                    },
                ],
            )
            data = get_trends_time_series_ok(self.client, request, self.team, with_order=True)

        assert data["$pageview - 0"]["2012-01-13"].value == 0
        assert data["$pageview - 0"]["2012-01-14"].value == 3
        assert data["$pageview - 1"]["2012-01-14"].value == 1
        assert data["$pageview - 0"]["2012-01-14"].label == "14-Jan-2012"
        assert data["$pageview - 0"]["2012-01-15"].value == 0

    @snapshot_clickhouse_queries
    def test_insight_trends_aggregate(self):
        events_by_person = {
            "1": [{"event": "$pageview", "timestamp": datetime(2012, 1, 13, 3)}],
            "2": [{"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3)}],
        }
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
                display="ActionsPie",
                events=[
                    {
                        "id": "$pageview",
                        "math": None,
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data = get_trends_aggregate_ok(self.client, request, self.team)

        assert data["$pageview"].value == 2
        assert data["$pageview"].label == "$pageview"

    @snapshot_clickhouse_queries
    def test_insight_trends_cumulative(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"key": "some_val"})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"key": "some_val"})
        _create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"key": "some_val"})

        events_by_person = {
            "p1": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "val"},
                },
                {
                    "event": "$pageview",
                    "timestamp": datetime(2012, 1, 14, 3),
                    "properties": {"key": "val"},
                },
            ],
            "p2": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "notval"},
                }
            ],
            "p3": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2012, 1, 14, 3),
                    "properties": {"key": "val"},
                }
            ],
        }
        journeys_for(events_by_person, self.team, create_people=False)

        # Total Volume
        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
                display="ActionsLineGraphCumulative",
                events=[
                    {
                        "id": "$pageview",
                        "math": None,
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data_response = get_trends_time_series_ok(self.client, request, self.team)

        assert data_response["$pageview"]["2012-01-13"].value == 2
        assert data_response["$pageview"]["2012-01-14"].value == 4
        assert data_response["$pageview"]["2012-01-15"].value == 4
        assert data_response["$pageview"]["2012-01-14"].label == "14-Jan-2012"

        # DAU

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
                display="ActionsLineGraphCumulative",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data_response = get_trends_time_series_ok(self.client, request, self.team)

        assert data_response["$pageview"]["2012-01-13"].value == 2
        assert data_response["$pageview"]["2012-01-14"].value == 3
        assert data_response["$pageview"]["2012-01-15"].value == 3
        assert data_response["$pageview"]["2012-01-14"].label == "14-Jan-2012"

        # breakdown
        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequestBreakdown(
                date_from="-14d",
                display="ActionsLineGraphCumulative",
                breakdown="key",
                breakdown_type="event",
                events=[
                    {
                        "id": "$pageview",
                        "math": None,
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data_response = get_trends_time_series_ok(self.client, request, self.team)

        assert data_response["val"]["2012-01-13"].value == 1
        assert data_response["val"]["2012-01-13"].breakdown_value == "val"
        assert data_response["val"]["2012-01-14"].value == 3
        assert data_response["val"]["2012-01-14"].label == "14-Jan-2012"

        # breakdown wau
        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequestBreakdown(
                date_from="-14d",
                display="ActionsLineGraphCumulative",
                breakdown="key",
                breakdown_type="event",
                events=[
                    {
                        "id": "$pageview",
                        "math": "weekly_active",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [{"type": "person", "key": "key", "value": "some_val"}],
                        "math_property": None,
                    }
                ],
                properties=[{"type": "person", "key": "key", "value": "some_val"}],
            )
            data_response = get_trends_time_series_ok(self.client, request, self.team)

        assert data_response["val"]["2012-01-13"].value == 1
        assert data_response["val"]["2012-01-13"].breakdown_value == "val"
        assert data_response["val"]["2012-01-14"].value == 3
        assert data_response["val"]["2012-01-14"].label == "14-Jan-2012"

        # breakdown dau
        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequestBreakdown(
                date_from="-14d",
                display="ActionsLineGraphCumulative",
                breakdown="key",
                breakdown_type="event",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data_response = get_trends_time_series_ok(self.client, request, self.team)

        assert data_response["val"]["2012-01-13"].value == 1
        assert data_response["val"]["2012-01-13"].breakdown_value == "val"
        assert data_response["val"]["2012-01-14"].value == 2
        assert data_response["val"]["2012-01-14"].label == "14-Jan-2012"

    @also_test_with_materialized_columns(["key"])
    def test_breakdown_with_filter(self):
        events_by_person = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "val"},
                }
            ],
            "person2": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "oh"},
                }
            ],
        }
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            params = TrendsRequestBreakdown(
                date_from="-14d",
                breakdown="key",
                events=[{"id": "sign up", "name": "sign up", "type": "events", "order": 0}],
                properties=[{"key": "key", "value": "oh", "operator": "not_icontains"}],
            )
            data_response = get_trends_time_series_ok(self.client, params, self.team)

        assert data_response["val"]["2012-01-13"].value == 1
        assert data_response["val"]["2012-01-13"].breakdown_value == "val"

        with freeze_time("2012-01-15T04:01:34.000Z"):
            params = TrendsRequestBreakdown(
                date_from="-14d",
                breakdown="key",
                display="ActionsPie",
                events=[{"id": "sign up", "name": "sign up", "type": "events", "order": 0}],
            )
            aggregate_response = get_trends_aggregate_ok(self.client, params, self.team)

        assert aggregate_response["val"].value == 1

    def test_insight_trends_compare(self):
        events_by_person = {
            "p1": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2012, 1, 5, 3),
                    "properties": {"key": "val"},
                },
                {
                    "event": "$pageview",
                    "timestamp": datetime(2012, 1, 14, 3),
                    "properties": {"key": "val"},
                },
            ],
            "p2": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2012, 1, 5, 3),
                    "properties": {"key": "notval"},
                },
                {
                    "event": "$pageview",
                    "timestamp": datetime(2012, 1, 14, 3),
                    "properties": {"key": "notval"},
                },
            ],
        }
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-7d",
                compare=True,
                events=[
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "order": 0,
                    }
                ],
            )
            data_response = get_trends_time_series_ok(self.client, request, self.team)

        assert data_response["$pageview - current"]["2012-01-13"].value == 0
        assert data_response["$pageview - current"]["2012-01-14"].value == 2

        assert data_response["$pageview - previous"]["2012-01-04"].value == 0
        assert data_response["$pageview - previous"]["2012-01-05"].value == 2


class ClickhouseTestTrendsGroups(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    def _create_groups(self):
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
            group_type_index=0,
            group_key="org:7",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:10",
            properties={"industry": "finance"},
        )

    @snapshot_clickhouse_queries
    def test_aggregating_by_group(self):
        self._create_groups()

        events_by_person = {
            "person1": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"$group_0": "org:5"},
                },
                {
                    "event": "$pageview",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"$group_0": "org:6"},
                },
                {
                    "event": "$pageview",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"$group_0": "org:6", "$group_1": "company:10"},
                },
            ]
        }
        journeys_for(events_by_person, self.team)

        request = TrendsRequest(
            date_from="2020-01-01 00:00:00",
            date_to="2020-01-12 00:00:00",
            events=[
                {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "math": "unique_group",
                    "math_group_type_index": 0,
                }
            ],
        )
        data_response = get_trends_time_series_ok(self.client, request, self.team)

        assert data_response["$pageview"]["2020-01-01"].value == 0
        assert data_response["$pageview"]["2020-01-02"].value == 2

    @snapshot_clickhouse_queries
    def test_aggregating_by_session(self):
        events_by_person = {
            "person1": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"$session_id": "1"},
                },
                {
                    "event": "$pageview",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"$session_id": "1"},
                },
                {
                    "event": "$pageview",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"$session_id": "2"},
                },
            ],
            "person2": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"$session_id": "3"},
                }
            ],
        }
        journeys_for(events_by_person, self.team)

        request = TrendsRequest(
            date_from="2020-01-01 00:00:00",
            date_to="2020-01-12 00:00:00",
            events=[
                {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "math": "unique_session",
                }
            ],
        )
        data_response = get_trends_time_series_ok(self.client, request, self.team)

        assert data_response["$pageview"]["2020-01-01"].value == 1
        assert data_response["$pageview"]["2020-01-02"].value == 2


class ClickhouseTestTrendsCaching(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    @snapshot_clickhouse_queries
    def test_insight_trends_merging(self):
        set_instance_setting("STRICT_CACHING_TEAMS", "all")

        events_by_person = {
            "1": [{"event": "$pageview", "timestamp": datetime(2012, 1, 13, 3)}],
            "2": [{"event": "$pageview", "timestamp": datetime(2012, 1, 13, 3)}],
        }
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data = get_trends_time_series_ok(self.client, request, self.team)

        assert data["$pageview"]["2012-01-13"].value == 2
        assert data["$pageview"]["2012-01-14"].value == 0
        assert data["$pageview"]["2012-01-15"].value == 0

        events_by_person = {"1": [{"event": "$pageview", "timestamp": datetime(2012, 1, 15, 3)}]}
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
                refresh=True,
            )
            data = get_trends_time_series_ok(self.client, request, self.team)

        assert data["$pageview"]["2012-01-13"].value == 2
        assert data["$pageview"]["2012-01-14"].value == 0
        assert data["$pageview"]["2012-01-15"].value == 1

    @skip("Don't handle breakdowns right now")
    def test_insight_trends_merging_breakdown(self):
        set_instance_setting("STRICT_CACHING_TEAMS", "all")

        events_by_person = {
            "1": [
                {
                    "event": "$action",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "1"},
                },
                {
                    "event": "$action",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "2"},
                },
            ],
            "2": [
                {
                    "event": "$action",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "1"},
                }
            ],
        }
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequestBreakdown(
                date_from="-14d",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$action",
                        "math": "dau",
                        "name": "$action",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
                breakdown="key",
            )
            data = get_trends_time_series_ok(self.client, request, self.team)

        assert data["$action - 1"]["2012-01-13"].value == 2
        assert data["$action - 1"]["2012-01-14"].value == 0
        assert data["$action - 1"]["2012-01-15"].value == 0

        assert data["$action - 2"]["2012-01-13"].value == 1
        assert data["$action - 2"]["2012-01-14"].value == 0
        assert data["$action - 2"]["2012-01-15"].value == 0

        events_by_person = {
            "1": [
                {
                    "event": "$action",
                    "timestamp": datetime(2012, 1, 15, 3),
                    "properties": {"key": "2"},
                }
            ],
            "2": [
                {
                    "event": "$action",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "2"},
                }
            ],  # this won't be counted
        }
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequestBreakdown(
                date_from="-14d",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$action",
                        "math": "dau",
                        "name": "$action",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
                breakdown="key",
                refresh=True,
            )
            data = get_trends_time_series_ok(self.client, request, self.team)

        assert data["$action - 1"]["2012-01-13"].value == 2
        assert data["$action - 1"]["2012-01-14"].value == 0
        assert data["$action - 1"]["2012-01-15"].value == 0

        assert data["$action - 2"]["2012-01-13"].value == 1
        assert data["$action - 2"]["2012-01-14"].value == 0
        assert data["$action - 2"]["2012-01-15"].value == 1

    @skip("Don't handle breakdowns right now")
    def test_insight_trends_merging_breakdown_multiple(self):
        set_instance_setting("STRICT_CACHING_TEAMS", "all")

        events_by_person = {
            "1": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "1"},
                },
                {
                    "event": "$action",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "1"},
                },
                {
                    "event": "$action",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "2"},
                },
            ],
            "2": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "1"},
                },
                {
                    "event": "$action",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "1"},
                },
            ],
        }
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequestBreakdown(
                date_from="-14d",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    },
                    {
                        "id": "$action",
                        "math": "dau",
                        "name": "$action",
                        "custom_name": None,
                        "type": "events",
                        "order": 1,
                        "properties": [],
                        "math_property": None,
                    },
                ],
                breakdown="key",
            )
            data = get_trends_time_series_ok(self.client, request, self.team)

        assert data["$pageview - 1"]["2012-01-13"].value == 2
        assert data["$pageview - 1"]["2012-01-14"].value == 0
        assert data["$pageview - 1"]["2012-01-15"].value == 0

        assert data["$action - 1"]["2012-01-13"].value == 2
        assert data["$action - 1"]["2012-01-14"].value == 0
        assert data["$action - 1"]["2012-01-15"].value == 0

        assert data["$action - 2"]["2012-01-13"].value == 1
        assert data["$action - 2"]["2012-01-14"].value == 0
        assert data["$action - 2"]["2012-01-15"].value == 0

        events_by_person = {
            "1": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2012, 1, 15, 3),
                    "properties": {"key": "1"},
                },
                {
                    "event": "$action",
                    "timestamp": datetime(2012, 1, 15, 3),
                    "properties": {"key": "2"},
                },
            ],
            "2": [
                {
                    "event": "$action",
                    "timestamp": datetime(2012, 1, 13, 3),
                    "properties": {"key": "2"},
                }  # this won't be counted
            ],
        }
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequestBreakdown(
                date_from="-14d",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    },
                    {
                        "id": "$action",
                        "math": "dau",
                        "name": "$action",
                        "custom_name": None,
                        "type": "events",
                        "order": 1,
                        "properties": [],
                        "math_property": None,
                    },
                ],
                breakdown="key",
                refresh=True,
            )
            data = get_trends_time_series_ok(self.client, request, self.team)

        assert data["$pageview - 1"]["2012-01-13"].value == 2
        assert data["$pageview - 1"]["2012-01-14"].value == 0
        assert data["$pageview - 1"]["2012-01-15"].value == 1

        assert data["$action - 1"]["2012-01-13"].value == 2
        assert data["$action - 1"]["2012-01-14"].value == 0
        assert data["$action - 1"]["2012-01-15"].value == 0

        assert data["$action - 2"]["2012-01-13"].value == 1
        assert data["$action - 2"]["2012-01-14"].value == 0
        assert data["$action - 2"]["2012-01-15"].value == 1

    # When the latest time interval in the cached result doesn't match the current interval, do not use caching pattern
    @snapshot_clickhouse_queries
    def test_insight_trends_merging_skipped_interval(self):
        set_instance_setting("STRICT_CACHING_TEAMS", "all")

        events_by_person = {
            "1": [{"event": "$pageview", "timestamp": datetime(2012, 1, 13, 3)}],
            "2": [{"event": "$pageview", "timestamp": datetime(2012, 1, 13, 3)}],
        }
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-14T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data = get_trends_time_series_ok(self.client, request, self.team)

        assert data["$pageview"]["2012-01-13"].value == 2
        assert data["$pageview"]["2012-01-14"].value == 0

        events_by_person = {
            "1": [{"event": "$pageview", "timestamp": datetime(2012, 1, 15, 3)}],
            "2": [{"event": "$pageview", "timestamp": datetime(2012, 1, 16, 3)}],
        }
        journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-16T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
                refresh=True,
            )
            data = get_trends_time_series_ok(self.client, request, self.team)

        assert data["$pageview"]["2012-01-13"].value == 2
        assert data["$pageview"]["2012-01-14"].value == 0
        assert data["$pageview"]["2012-01-15"].value == 1
        assert data["$pageview"]["2012-01-16"].value == 1
