from datetime import datetime

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.hogql.query import execute_hogql_query

from products.signals.backend.emission.front_conversations import FRONT_CONFIG


@pytest.mark.django_db
class TestFrontPartitionField(ClickhouseTestMixin, BaseTest):
    def test_a_fractional_epoch_resolves_to_a_datetime(self):
        # Only ClickHouse shows this one. The query parses and names known functions either way,
        # but an accurate cast of a fractional epoch returns NULL, which drops every Front
        # conversation out of the time filter and emits nothing.
        expression = FRONT_CONFIG.partition_field.replace("created_at", "1701292649.333")

        result = execute_hogql_query(f"SELECT {expression}", team=self.team)

        assert result.results[0][0] == datetime(2023, 11, 29, 21, 17, 29)
