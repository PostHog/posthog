from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ColumnTypeCategory,
    RowFilterColumn,
    ValidatedRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.constants import (
    BLOGS,
    COLLECTIONS,
    CUSTOMERS,
    ORDERS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    row_filter_search_terms,
    shopify_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import ShopifySource

CREATED_AT_COLUMN = RowFilterColumn(name="created_at", data_type="timestamp", operators=(">", ">=", "<", "<="))


def _created_at_filter(operator: str, value: datetime) -> ValidatedRowFilter:
    return ValidatedRowFilter(
        column="created_at", operator=operator, value=value, category=ColumnTypeCategory.TIMESTAMP
    )


def _response(object_name: str) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = {
        "data": {object_name: {"nodes": [{"id": "1"}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
    }
    return response


class TestRowFilterColumns:
    @pytest.mark.parametrize(
        "schema_name, expected",
        [
            (ORDERS, (CREATED_AT_COLUMN,)),
            (CUSTOMERS, (CREATED_AT_COLUMN,)),
            ("discountCodes", (CREATED_AT_COLUMN,)),
            (COLLECTIONS, ()),
            (BLOGS, ()),
        ],
    )
    def test_columns_by_schema(self, schema_name: str, expected: tuple[RowFilterColumn, ...]) -> None:
        assert ShopifySource().row_filter_columns_for_schema(schema_name) == expected


class TestRowFilterSearchTerms:
    @pytest.mark.parametrize(
        "schema_name, row_filter, expected",
        [
            (
                ORDERS,
                _created_at_filter(">=", datetime(2024, 1, 1, tzinfo=UTC)),
                "created_at:>='2024-01-01T00:00:00+00:00'",
            ),
            # A value without a timezone is read as UTC.
            (ORDERS, _created_at_filter("<", datetime(2024, 1, 1)), "created_at:<'2024-01-01T00:00:00+00:00'"),
            (
                CUSTOMERS,
                _created_at_filter(">", datetime(2024, 1, 1, tzinfo=UTC)),
                "customer_date:>'2024-01-01T00:00:00+00:00'",
            ),
        ],
    )
    def test_term(self, schema_name: str, row_filter: ValidatedRowFilter, expected: str) -> None:
        assert row_filter_search_terms(schema_name, [row_filter]) == [expected]

    @pytest.mark.parametrize(
        "schema_name, row_filter",
        [
            (COLLECTIONS, _created_at_filter(">=", datetime(2024, 1, 1, tzinfo=UTC))),
            (
                ORDERS,
                ValidatedRowFilter(
                    column="updated_at",
                    operator=">=",
                    value=datetime(2024, 1, 1, tzinfo=UTC),
                    category=ColumnTypeCategory.TIMESTAMP,
                ),
            ),
            (
                ORDERS,
                ValidatedRowFilter(
                    column="created_at",
                    operator="=",
                    value=datetime(2024, 1, 1, tzinfo=UTC),
                    category=ColumnTypeCategory.TIMESTAMP,
                ),
            ),
        ],
    )
    def test_filter_without_a_search_term_raises(self, schema_name: str, row_filter: ValidatedRowFilter) -> None:
        with pytest.raises(ValueError, match="cannot apply the row filter"):
            row_filter_search_terms(schema_name, [row_filter])


class TestShopifySourceQueries:
    @pytest.mark.parametrize(
        "incremental, last_value, earliest_value, expected_queries",
        [
            (False, None, None, ["created_at:>='2024-01-01T00:00:00+00:00'"]),
            (True, None, None, ["created_at:>='2024-01-01T00:00:00+00:00'"]),
            (
                True,
                "2026-01-10",
                "2026-01-01",
                [
                    "updated_at:<'2026-01-01' AND created_at:>='2024-01-01T00:00:00+00:00'",
                    "updated_at:>'2026-01-10' AND created_at:>='2024-01-01T00:00:00+00:00'",
                ],
            ),
        ],
    )
    def test_every_read_carries_the_filter(
        self, incremental: bool, last_value: str | None, earliest_value: str | None, expected_queries: list[str]
    ) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False
        queries: list[Any] = []

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify.requests.Session"
        ) as session_cls:

            def _post(url: str, json: dict[str, Any] | None = None, **kwargs: Any) -> MagicMock:
                queries.append((json or {}).get("variables", {}).get("query"))
                return _response(ORDERS)

            session_cls.return_value.post.side_effect = _post

            source = shopify_source(
                shopify_store_id="store",
                shopify_client_id=None,
                shopify_client_secret=None,
                shopify_access_token="shpat_test",
                graphql_object_name=ORDERS,
                db_incremental_field_last_value=last_value,
                db_incremental_field_earliest_value=earliest_value,
                logger=MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=incremental,
                row_filters=[_created_at_filter(">=", datetime(2024, 1, 1, tzinfo=UTC))],
            )
            list(source.items())

        assert queries == expected_queries
