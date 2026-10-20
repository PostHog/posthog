from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.constants import (
    ABANDONED_CHECKOUTS,
    ORDERS,
    SHOPIFY_GRAPHQL_OBJECTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    PHASE_ALL,
    PHASE_EARLIEST,
    PHASE_LATEST,
    ShopifyQueryCostExceededError,
    ShopifyResumeConfig,
    _make_paginated_shopify_request,
    shopify_source,
)


def _build_response(
    object_name: str, nodes: list[dict[str, Any]], has_next_page: bool, end_cursor: str | None
) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = {
        "data": {
            object_name: {
                "nodes": nodes,
                "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
            }
        }
    }
    return response


def _make_manager(can_resume: bool = False, resume_state: ShopifyResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    return manager


def _record_post_vars(sess: MagicMock, responses: list[MagicMock]) -> list[dict[str, Any]]:
    """Capture the `variables` dict by value at call time.

    The production code passes the `variables` dict by reference and mutates it
    between pages, so reading it off `call_args_list` after the fact reflects
    only the final state, not per-call state.
    """
    captured: list[dict[str, Any]] = []
    iter_responses = iter(responses)

    def _post(url: str, json: dict[str, Any] | None = None, **kwargs: Any) -> MagicMock:
        captured.append(dict((json or {}).get("variables", {})))
        return next(iter_responses)

    sess.post.side_effect = _post
    return captured


class TestMakePaginatedShopifyRequest:
    def test_saves_state_after_each_page_except_final(self) -> None:
        graphql_object = SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS]
        logger = MagicMock()
        manager = _make_manager()
        sess = MagicMock()
        sess.post.side_effect = [
            _build_response(ABANDONED_CHECKOUTS, [{"id": "1"}], has_next_page=True, end_cursor="cursor-1"),
            _build_response(ABANDONED_CHECKOUTS, [{"id": "2"}], has_next_page=True, end_cursor="cursor-2"),
            _build_response(ABANDONED_CHECKOUTS, [{"id": "3"}], has_next_page=False, end_cursor=None),
        ]

        batches = list(
            _make_paginated_shopify_request(
                "https://example.invalid/graphql",
                sess,
                graphql_object,
                logger,
                phase=PHASE_ALL,
                resumable_source_manager=manager,
            )
        )

        assert len(batches) == 3
        # save_state fires only when has_next_page is True (final page is terminal).
        assert manager.save_state.call_count == 2
        saved_configs = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved_configs[0] == ShopifyResumeConfig(phase=PHASE_ALL, cursor="cursor-1")
        assert saved_configs[1] == ShopifyResumeConfig(phase=PHASE_ALL, cursor="cursor-2")

    @pytest.mark.parametrize(
        "object_name, costs, expected_page_sizes",
        [
            # 450 points at 20 rows leaves room for 40 rows under the 900 point target.
            (ORDERS, [{"requestedQueryCost": 450}], [20, 40]),
            (ORDERS, [{"requestedQueryCost": 10}], [20, 250]),
            # Half of a 400 point bucket is 200 points, which is 40 rows at 5 points a row.
            (ORDERS, [{"requestedQueryCost": 100, "throttleStatus": {"maximumAvailable": 400}}], [20, 40]),
            # A cost above the target at a size Shopify answered keeps that size.
            (ORDERS, [{"requestedQueryCost": 782}, {"requestedQueryCost": 938}], [20, 23, 23]),
            (ABANDONED_CHECKOUTS, [{"requestedQueryCost": 450}], [100, 100]),
        ],
    )
    def test_grows_page_from_reported_cost_only_for_cost_limited_objects(
        self, object_name: str, costs: list[dict[str, Any]], expected_page_sizes: list[int]
    ) -> None:
        sess = MagicMock()
        pages = []
        for index, cost in enumerate(costs):
            page = _build_response(object_name, [{"id": str(index)}], has_next_page=True, end_cursor=f"cursor-{index}")
            page.json.return_value["extensions"] = {"cost": cost}
            pages.append(page)
        captured = _record_post_vars(
            sess, [*pages, _build_response(object_name, [{"id": "last"}], has_next_page=False, end_cursor=None)]
        )

        list(
            _make_paginated_shopify_request(
                "https://example.invalid/graphql", sess, SHOPIFY_GRAPHQL_OBJECTS[object_name], MagicMock()
            )
        )

        assert [variables["pageSize"] for variables in captured] == expected_page_sizes

    @pytest.mark.parametrize(
        "failed_requests",
        [
            [{"errors": [{"message": "Query cost is too high", "extensions": {"code": "MAX_COST_EXCEEDED"}}]}],
            [{"errors": [{"message": "Query cost is 1057, which exceeds the single query max cost limit (1000)."}]}],
            [requests.exceptions.ReadTimeout("Read timed out")] * 5,
        ],
        ids=["cost_error_code", "cost_error_message", "timeouts_until_retries_run_out"],
    )
    @patch("tenacity.nap.time.sleep")
    def test_grown_page_that_fails_is_read_again_at_the_starting_size_for_the_rest_of_the_read(
        self, _mock_sleep: MagicMock, failed_requests: list[Any]
    ) -> None:
        def page(node_id: str, end_cursor: str | None) -> MagicMock:
            response = _build_response(
                ORDERS, [{"id": node_id}], has_next_page=end_cursor is not None, end_cursor=end_cursor
            )
            response.json.return_value["extensions"] = {"cost": {"requestedQueryCost": 450}}
            return response

        def failure(outcome: Any) -> Any:
            if isinstance(outcome, Exception):
                return outcome
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = outcome
            return response

        outcomes = [
            page("1", "cursor-1"),
            *[failure(outcome) for outcome in failed_requests],
            page("2", "cursor-2"),
            page("3", None),
        ]
        captured: list[tuple[int, str | None]] = []
        sess = MagicMock()

        def post(url: str, json: dict[str, Any], **kwargs: Any) -> MagicMock:
            captured.append((json["variables"]["pageSize"], json["variables"].get("cursor")))
            outcome = outcomes[len(captured) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        sess.post.side_effect = post

        batches = list(
            _make_paginated_shopify_request(
                "https://example.invalid/graphql", sess, SHOPIFY_GRAPHQL_OBJECTS[ORDERS], MagicMock()
            )
        )

        assert batches == [[{"id": "1"}], [{"id": "2"}], [{"id": "3"}]]
        assert captured == [
            (20, None),
            *[(40, "cursor-1")] * len(failed_requests),
            (20, "cursor-1"),
            (20, "cursor-2"),
        ]

    def test_cost_rejection_at_the_starting_size_fails_after_one_request(self) -> None:
        sess = MagicMock()
        rejected = MagicMock()
        rejected.status_code = 200
        rejected.json.return_value = {
            "errors": [{"message": "Query cost is too high", "extensions": {"code": "MAX_COST_EXCEEDED"}}]
        }
        sess.post.return_value = rejected

        with pytest.raises(ShopifyQueryCostExceededError):
            list(
                _make_paginated_shopify_request(
                    "https://example.invalid/graphql", sess, SHOPIFY_GRAPHQL_OBJECTS[ORDERS], MagicMock()
                )
            )

        assert sess.post.call_count == 1

    def test_seeds_initial_cursor_on_resume(self) -> None:
        graphql_object = SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS]
        logger = MagicMock()
        manager = _make_manager()
        sess = MagicMock()
        captured = _record_post_vars(
            sess, [_build_response(ABANDONED_CHECKOUTS, [{"id": "5"}], has_next_page=False, end_cursor=None)]
        )

        list(
            _make_paginated_shopify_request(
                "https://example.invalid/graphql",
                sess,
                graphql_object,
                logger,
                phase=PHASE_ALL,
                initial_cursor="resume-cursor",
                resumable_source_manager=manager,
            )
        )

        assert sess.post.call_count == 1
        assert captured[0]["cursor"] == "resume-cursor"

    def test_tags_saved_state_with_phase(self) -> None:
        graphql_object = SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS]
        logger = MagicMock()
        manager = _make_manager()
        sess = MagicMock()
        sess.post.side_effect = [
            _build_response(ABANDONED_CHECKOUTS, [{"id": "1"}], has_next_page=True, end_cursor="next"),
            _build_response(ABANDONED_CHECKOUTS, [{"id": "2"}], has_next_page=False, end_cursor=None),
        ]

        list(
            _make_paginated_shopify_request(
                "https://example.invalid/graphql",
                sess,
                graphql_object,
                logger,
                query="created_at:>'2026-01-01'",
                phase=PHASE_LATEST,
                resumable_source_manager=manager,
            )
        )

        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args_list[0].args[0]
        assert saved == ShopifyResumeConfig(phase=PHASE_LATEST, cursor="next")

    def test_no_save_without_manager(self) -> None:
        graphql_object = SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS]
        logger = MagicMock()
        sess = MagicMock()
        sess.post.side_effect = [
            _build_response(ABANDONED_CHECKOUTS, [{"id": "1"}], has_next_page=True, end_cursor="next"),
            _build_response(ABANDONED_CHECKOUTS, [{"id": "2"}], has_next_page=False, end_cursor=None),
        ]

        batches = list(
            _make_paginated_shopify_request(
                "https://example.invalid/graphql",
                sess,
                graphql_object,
                logger,
                phase=PHASE_ALL,
            )
        )

        assert len(batches) == 2


@pytest.fixture(autouse=True)
def _mock_access_token():
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify._get_shopify_access_token",
        return_value="test-token",
    ):
        yield


class TestShopifySourceResume:
    def test_fresh_full_refresh_starts_without_cursor_and_saves_state(self) -> None:
        logger = MagicMock()
        manager = _make_manager(can_resume=False)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify.requests.Session"
        ) as session_cls:
            sess = session_cls.return_value
            captured = _record_post_vars(
                sess,
                [
                    _build_response(ORDERS, [{"id": "1"}], has_next_page=True, end_cursor="cursor-1"),
                    _build_response(ORDERS, [{"id": "2"}], has_next_page=False, end_cursor=None),
                ],
            )

            source = shopify_source(
                shopify_store_id="store",
                shopify_client_id="id",
                shopify_client_secret="secret",
                graphql_object_name=ORDERS,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                logger=logger,
                resumable_source_manager=manager,
                should_use_incremental_field=False,
            )
            batches = list(source.items())

        assert len(batches) == 2
        manager.can_resume.assert_called_once()
        manager.load_state.assert_not_called()
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args_list[0].args[0]
        assert saved == ShopifyResumeConfig(phase=PHASE_ALL, cursor="cursor-1")

        assert "cursor" not in captured[0]

    def test_resume_full_refresh_seeds_cursor_and_skips_initial_request(self) -> None:
        logger = MagicMock()
        resume_state = ShopifyResumeConfig(phase=PHASE_ALL, cursor="resume-here")
        manager = _make_manager(can_resume=True, resume_state=resume_state)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify.requests.Session"
        ) as session_cls:
            sess = session_cls.return_value
            captured = _record_post_vars(
                sess,
                [_build_response(ORDERS, [{"id": "3"}], has_next_page=False, end_cursor=None)],
            )

            source = shopify_source(
                shopify_store_id="store",
                shopify_client_id="id",
                shopify_client_secret="secret",
                graphql_object_name=ORDERS,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                logger=logger,
                resumable_source_manager=manager,
                should_use_incremental_field=False,
            )
            batches = list(source.items())

        assert len(batches) == 1
        manager.load_state.assert_called_once()
        # Exactly one request: the resumed page. The initial (cursor-less) request is skipped.
        assert sess.post.call_count == 1
        assert captured[0]["cursor"] == "resume-here"

    def test_resume_latest_phase_skips_earliest_sweep(self) -> None:
        logger = MagicMock()
        resume_state = ShopifyResumeConfig(phase=PHASE_LATEST, cursor="latest-cursor")
        manager = _make_manager(can_resume=True, resume_state=resume_state)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify.requests.Session"
        ) as session_cls:
            sess = session_cls.return_value
            captured = _record_post_vars(
                sess,
                [_build_response(ORDERS, [{"id": "9"}], has_next_page=False, end_cursor=None)],
            )

            source = shopify_source(
                shopify_store_id="store",
                shopify_client_id="id",
                shopify_client_secret="secret",
                graphql_object_name=ORDERS,
                db_incremental_field_last_value="2026-01-10",
                db_incremental_field_earliest_value="2026-01-01",
                logger=logger,
                resumable_source_manager=manager,
                should_use_incremental_field=True,
            )
            batches = list(source.items())

        assert len(batches) == 1
        # Only the latest sweep runs, seeded with the resume cursor.
        assert sess.post.call_count == 1
        assert captured[0]["cursor"] == "latest-cursor"
        assert captured[0]["query"] == "updated_at:>'2026-01-10'"

    def test_resume_earliest_phase_runs_remaining_earliest_then_latest(self) -> None:
        logger = MagicMock()
        resume_state = ShopifyResumeConfig(phase=PHASE_EARLIEST, cursor="earliest-cursor")
        manager = _make_manager(can_resume=True, resume_state=resume_state)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify.requests.Session"
        ) as session_cls:
            sess = session_cls.return_value
            captured = _record_post_vars(
                sess,
                [
                    # remaining earliest page (final)
                    _build_response(ORDERS, [{"id": "e1"}], has_next_page=False, end_cursor=None),
                    # latest sweep starts fresh (no cursor)
                    _build_response(ORDERS, [{"id": "l1"}], has_next_page=False, end_cursor=None),
                ],
            )

            source = shopify_source(
                shopify_store_id="store",
                shopify_client_id="id",
                shopify_client_secret="secret",
                graphql_object_name=ORDERS,
                db_incremental_field_last_value="2026-01-10",
                db_incremental_field_earliest_value="2026-01-01",
                logger=logger,
                resumable_source_manager=manager,
                should_use_incremental_field=True,
            )
            batches = list(source.items())

        assert len(batches) == 2
        assert sess.post.call_count == 2

        assert captured[0]["cursor"] == "earliest-cursor"
        assert captured[0]["query"] == "updated_at:<'2026-01-01'"

        assert "cursor" not in captured[1]
        assert captured[1]["query"] == "updated_at:>'2026-01-10'"
