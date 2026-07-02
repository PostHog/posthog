from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit import (
    ConvertKitResumeConfig,
    _format_incremental_value,
    build_initial_params,
    convertkit_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.settings import CONVERTKIT_ENDPOINTS


def _make_response(json_data: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    return response


def _make_manager(can_resume: bool = False, state: ConvertKitResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


def _page(key: str, ids: list[int], has_next: bool, end_cursor: str | None) -> dict:
    return {
        key: [{"id": i} for i in ids],
        "pagination": {"has_next_page": has_next, "end_cursor": end_cursor},
    }


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "cursor-value", "cursor-value"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        result = _format_incremental_value(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildInitialParams:
    def test_includes_per_page_and_extra_params(self) -> None:
        params = build_initial_params(
            CONVERTKIT_ENDPOINTS["subscribers"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params["per_page"] == 1000
        # subscribers must request every status, not just active.
        assert params["status"] == "all"

    @parameterized.expand(
        [
            ("created_at", "created_after"),
            ("updated_at", "updated_after"),
        ]
    )
    def test_incremental_field_maps_to_filter_param(self, field: str, expected_param: str) -> None:
        params = build_initial_params(
            CONVERTKIT_ENDPOINTS["subscribers"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            incremental_field=field,
        )
        assert params[expected_param] == "2026-01-02T03:04:05Z"
        # Only the chosen field's param is set.
        other_param = "updated_after" if expected_param == "created_after" else "created_after"
        assert other_param not in params

    def test_no_filter_when_not_using_incremental(self) -> None:
        params = build_initial_params(
            CONVERTKIT_ENDPOINTS["subscribers"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert "created_after" not in params

    def test_no_filter_for_non_incremental_endpoint(self) -> None:
        # broadcasts has no server-side timestamp filter, so no filter param is ever added.
        params = build_initial_params(
            CONVERTKIT_ENDPOINTS["broadcasts"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert "created_after" not in params
        assert "status" not in params


class TestGetRows:
    def test_paginates_until_no_next_page(self) -> None:
        manager = _make_manager(can_resume=False)
        logger = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit.make_tracked_session"
        ) as session_cls:
            session = session_cls.return_value
            session.get.side_effect = [
                _make_response(_page("subscribers", [1, 2], has_next=True, end_cursor="C2")),
                _make_response(_page("subscribers", [3], has_next=False, end_cursor=None)),
            ]

            batches = list(
                get_rows(api_key="key", endpoint="subscribers", logger=logger, resumable_source_manager=manager)
            )

        assert batches == [[{"id": 1}, {"id": 2}], [{"id": 3}]]
        assert session.get.call_count == 2
        # State saved once, with the first page's end_cursor.
        saved = [call.args[0].after for call in manager.save_state.call_args_list]
        assert saved == ["C2"]
        # The second request carries the cursor.
        assert "after=C2" in session.get.call_args_list[1].args[0]

    def test_resumes_from_saved_cursor(self) -> None:
        manager = _make_manager(can_resume=True, state=ConvertKitResumeConfig(after="C5"))
        logger = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit.make_tracked_session"
        ) as session_cls:
            session = session_cls.return_value
            session.get.side_effect = [_make_response(_page("subscribers", [9], has_next=False, end_cursor=None))]

            batches = list(
                get_rows(api_key="key", endpoint="subscribers", logger=logger, resumable_source_manager=manager)
            )

        assert batches == [[{"id": 9}]]
        manager.load_state.assert_called_once()
        assert "after=C5" in session.get.call_args_list[0].args[0]

    def test_empty_page_yields_nothing_and_does_not_save(self) -> None:
        manager = _make_manager(can_resume=False)
        logger = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit.make_tracked_session"
        ) as session_cls:
            session = session_cls.return_value
            session.get.side_effect = [_make_response(_page("subscribers", [], has_next=False, end_cursor=None))]

            batches = list(
                get_rows(api_key="key", endpoint="subscribers", logger=logger, resumable_source_manager=manager)
            )

        assert batches == []
        manager.save_state.assert_not_called()


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_source_create", 403, None, True),
            ("forbidden_for_specific_endpoint", 403, "subscribers", False),
            ("server_error", 500, None, False),
        ]
    )
    def test_status_code_mapping(self, _name: str, status: int, endpoint: str | None, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit.make_tracked_session"
        ) as session_cls:
            session_cls.return_value.get.return_value = _make_response({}, status_code=status)
            is_valid, _error = validate_credentials("key", endpoint)
        assert is_valid is expected_valid

    def test_network_error_is_invalid(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit.make_tracked_session"
        ) as session_cls:
            session_cls.return_value.get.side_effect = Exception("boom")
            is_valid, error = validate_credentials("key")
        assert is_valid is False
        assert error is not None

    def test_unknown_endpoint_returns_error_without_request(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit.make_tracked_session"
        ) as session_cls:
            is_valid, error = validate_credentials("key", "not_a_real_endpoint")
        assert is_valid is False
        assert error is not None
        session_cls.assert_not_called()


class TestConvertKitSource:
    @parameterized.expand(
        [
            ("subscribers", ["id"], "created_at"),
            ("purchases", ["id"], "transaction_time"),
            ("custom_fields", ["id"], None),
            ("email_templates", ["id"], None),
        ]
    )
    def test_source_response_partitioning(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        manager = _make_manager(can_resume=False)
        logger = MagicMock()

        response = convertkit_source(api_key="key", endpoint=endpoint, logger=logger, resumable_source_manager=manager)

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None

    def test_source_threads_manager_and_yields(self) -> None:
        manager = _make_manager(can_resume=False)
        logger = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit.make_tracked_session"
        ) as session_cls:
            session_cls.return_value.get.side_effect = [
                _make_response(_page("tags", [7], has_next=False, end_cursor=None))
            ]
            response = convertkit_source(
                api_key="key", endpoint="tags", logger=logger, resumable_source_manager=manager
            )
            batches = list(cast(Iterable[Any], response.items()))

        assert batches == [[{"id": 7}]]
        manager.can_resume.assert_called_once()
