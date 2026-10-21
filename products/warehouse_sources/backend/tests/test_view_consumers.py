from collections.abc import Callable

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.cdp.backend.models.hog_functions import HogFunction
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.api import saved_queries_feeding_consumers
from products.warehouse_sources.backend.facade.hooks import PersonPropertySourceProjection
from products.workflows.backend.facade.testing import create_workflow_for_test

VIEW_NAME = "daily_revenue"
PERSON_PROJECTION = "products.warehouse_sources.backend.view_consumers.person_property_projection_for"


def _hog_function(team_id: int) -> None:
    HogFunction.objects.create(
        team_id=team_id,
        enabled=True,
        filters={"source": "data-warehouse-view", "data_warehouse": [{"table_name": VIEW_NAME}]},
    )


def _workflow(team_id: int) -> None:
    create_workflow_for_test(
        team_id=team_id, status="active", trigger={"type": "data-warehouse-view", "table_name": VIEW_NAME}
    )


def _nothing(team_id: int) -> None:
    pass


class TestSavedQueriesFeedingConsumers(BaseTest):
    @parameterized.expand(
        [
            ("hog_function", _hog_function, None, True),
            ("workflow", _workflow, None, True),
            ("person_property", _nothing, [PersonPropertySourceProjection("distinct_id", frozenset())], True),
            ("no_consumer", _nothing, None, False),
        ]
    )
    def test_finds_views_whose_refreshes_feed_a_consumer(
        self,
        _name: str,
        add_consumer: Callable[[int], None],
        person_projection: list[PersonPropertySourceProjection] | None,
        feeds: bool,
    ) -> None:
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name=VIEW_NAME, query={"kind": "HogQLQuery", "query": "SELECT 1"}
        )
        add_consumer(self.team.pk)

        with patch(PERSON_PROJECTION, return_value=person_projection):
            feeding = saved_queries_feeding_consumers(self.team.pk, [view.id])

        assert (view.id in feeding) is feeds
