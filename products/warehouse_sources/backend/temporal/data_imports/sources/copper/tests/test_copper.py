from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.copper import (
    COPPER_DEFAULT_PAGE_SIZE,
    CopperResumeConfig,
    _to_unix_seconds,
    copper_source,
    get_rows,
    validate_credentials,
)


def _make_response(json_data: Any, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    return response


def _make_manager(can_resume: bool = False, state: CopperResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


def _records(ids: list[int]) -> list[dict]:
    return [{"id": i, "date_created": 1700000000 + i, "date_modified": 1700000100 + i} for i in ids]


def _patch_session():
    return patch("products.warehouse_sources.backend.temporal.data_imports.sources.copper.copper.make_tracked_session")


class TestToUnixSeconds:
    @parameterized.expand(
        [
            ("none", None, None),
            ("int", 1700000000, 1700000000),
            ("float", 1700000000.7, 1700000000),
            ("numeric_string", "1700000000", 1700000000),
            ("bool_true", True, None),
            ("garbage", "not-a-number", None),
        ]
    )
    def test_scalar_coercion(self, _name: str, value: Any, expected: int | None) -> None:
        assert _to_unix_seconds(value) == expected

    def test_datetime_coercion(self) -> None:
        dt = datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        assert _to_unix_seconds(dt) == int(dt.timestamp())

    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime(2023, 11, 14, 22, 13, 20)
        assert _to_unix_seconds(naive) == int(datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC).timestamp())

    def test_date_treated_as_utc(self) -> None:
        assert _to_unix_seconds(date(2023, 11, 14)) == int(datetime(2023, 11, 14, tzinfo=UTC).timestamp())


class TestGetRows:
    def test_paginated_terminates_on_short_page(self) -> None:
        manager = _make_manager()
        logger = MagicMock()

        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.request.return_value = _make_response(_records([1, 2]))

            batches = list(
                get_rows(
                    api_key="key",
                    user_email="user@example.com",
                    endpoint="people",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert len(batches) == 1
        assert [r["id"] for r in batches[0]] == [1, 2]
        assert session.request.call_count == 1
        # A short first page terminates the loop without persisting resume state.
        manager.save_state.assert_not_called()

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = _make_manager()
        logger = MagicMock()

        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.request.return_value = _make_response([])

            batches = list(
                get_rows(
                    api_key="key",
                    user_email="user@example.com",
                    endpoint="companies",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert batches == []
        manager.save_state.assert_not_called()

    def test_save_state_called_per_full_page(self) -> None:
        full_page_a = _records(list(range(COPPER_DEFAULT_PAGE_SIZE)))
        full_page_b = _records(
            list(range(COPPER_DEFAULT_PAGE_SIZE, COPPER_DEFAULT_PAGE_SIZE + COPPER_DEFAULT_PAGE_SIZE))
        )
        tail = _records([99999])

        manager = _make_manager()
        logger = MagicMock()

        # Capture page_number at call time: the request body is a single dict mutated in place,
        # so recording it directly would only show its final value.
        requested_pages: list[int] = []
        responses = iter([_make_response(full_page_a), _make_response(full_page_b), _make_response(tail)])

        def fake_request(method: str, url: str, json: dict, timeout: int) -> MagicMock:
            requested_pages.append(json["page_number"])
            return next(responses)

        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.request.side_effect = fake_request

            list(
                get_rows(
                    api_key="key",
                    user_email="user@example.com",
                    endpoint="people",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        saved_pages = [call.args[0].page_number for call in manager.save_state.call_args_list]
        assert saved_pages == [2, 3]
        assert requested_pages == [1, 2, 3]

    def test_resume_starts_from_saved_page(self) -> None:
        manager = _make_manager(can_resume=True, state=CopperResumeConfig(page_number=4))
        logger = MagicMock()

        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.request.return_value = _make_response(_records([1]))

            list(
                get_rows(
                    api_key="key",
                    user_email="user@example.com",
                    endpoint="people",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert session.request.call_args_list[0].kwargs["json"]["page_number"] == 4
        manager.load_state.assert_called_once()

    @parameterized.expand(
        [
            ("date_modified", "minimum_modified_date", "date_modified"),
            ("date_created", "minimum_created_date", "date_created"),
        ]
    )
    def test_incremental_sets_filter_and_sort(self, incremental_field: str, min_param: str, sort_field: str) -> None:
        manager = _make_manager()
        logger = MagicMock()

        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.request.return_value = _make_response([])

            list(
                get_rows(
                    api_key="key",
                    user_email="user@example.com",
                    endpoint="people",
                    logger=logger,
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=1700000000,
                    incremental_field=incremental_field,
                )
            )

        body = session.request.call_args_list[0].kwargs["json"]
        assert body[min_param] == 1700000000
        assert body["sort_by"] == sort_field
        assert body["sort_direction"] == "asc"

    def test_full_refresh_sorts_by_created_for_searchable(self) -> None:
        manager = _make_manager()
        logger = MagicMock()

        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.request.return_value = _make_response([])

            list(
                get_rows(
                    api_key="key",
                    user_email="user@example.com",
                    endpoint="people",
                    logger=logger,
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        body = session.request.call_args_list[0].kwargs["json"]
        assert body["sort_by"] == "date_created"
        assert "minimum_modified_date" not in body

    def test_reference_endpoint_single_get(self) -> None:
        manager = _make_manager()
        logger = MagicMock()

        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.request.return_value = _make_response([{"id": 1, "name": "Won"}])

            batches = list(
                get_rows(
                    api_key="key",
                    user_email="user@example.com",
                    endpoint="loss_reasons",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert batches == [[{"id": 1, "name": "Won"}]]
        assert session.request.call_count == 1
        assert session.request.call_args_list[0].args[0] == "GET"
        # GET reference endpoints carry no request body.
        assert session.request.call_args_list[0].kwargs["json"] is None
        manager.can_resume.assert_not_called()

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_raises_then_retries(self, _name: str, status_code: int) -> None:
        manager = _make_manager()
        logger = MagicMock()

        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.request.side_effect = [
                _make_response(None, status_code=status_code),
                _make_response(_records([1])),
            ]

            batches = list(
                get_rows(
                    api_key="key",
                    user_email="user@example.com",
                    endpoint="people",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert [r["id"] for r in batches[0]] == [1]
        assert session.request.call_count == 2

    def test_redacts_api_key_and_closes_session(self) -> None:
        manager = _make_manager()
        logger = MagicMock()

        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.request.return_value = _make_response(_records([1]))

            list(
                get_rows(
                    api_key="secret-key",
                    user_email="user@example.com",
                    endpoint="people",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert session_cls.call_args.kwargs["redact_values"] == ("secret-key",)
        session.close.assert_called_once()


class TestCopperSource:
    def test_source_response_metadata_for_searchable(self) -> None:
        manager = _make_manager()
        logger = MagicMock()

        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.request.return_value = _make_response(_records([1]))

            response = copper_source(
                api_key="key",
                user_email="user@example.com",
                endpoint="opportunities",
                logger=logger,
                resumable_source_manager=manager,
            )
            batches = list(cast(Iterable[Any], response.items()))

        assert response.name == "opportunities"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date_created"]
        assert response.sort_mode == "asc"
        assert [r["id"] for r in batches[0]] == [1]

    def test_source_response_metadata_for_reference(self) -> None:
        manager = _make_manager()
        logger = MagicMock()

        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.request.return_value = _make_response([{"id": 1}])

            response = copper_source(
                api_key="key",
                user_email="user@example.com",
                endpoint="pipelines",
                logger=logger,
                resumable_source_manager=manager,
            )

        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.get.return_value = _make_response({}, status_code=status_code)

            valid, error = validate_credentials("key", "user@example.com")

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_exception_returns_error(self) -> None:
        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.get.side_effect = Exception("boom")

            valid, error = validate_credentials("key", "user@example.com")

        assert valid is False
        assert error == "boom"

    def test_redacts_api_key_and_closes_session(self) -> None:
        with _patch_session() as session_cls:
            session = session_cls.return_value
            session.get.return_value = _make_response({}, status_code=200)

            validate_credentials("secret-key", "user@example.com")

        assert session_cls.call_args.kwargs["redact_values"] == ("secret-key",)
        session.close.assert_called_once()
