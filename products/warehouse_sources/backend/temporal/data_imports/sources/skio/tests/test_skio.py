from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.skio.settings import SKIO_PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.skio.skio import (
    SkioAPIError,
    SkioResumeConfig,
    _build_order_by,
    _build_where,
    _format_timestamp,
    get_rows,
    validate_credentials,
)

TOKEN = "test-token"

# Verbatim message from the live API for an invalid or revoked token (Hasura returns it with
# HTTP 200 in the GraphQL errors body).
INVALID_TOKEN_BODY = {"errors": [{"message": "Invalid response from authorization hook"}]}


def _response(payload: dict[str, Any], status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Client Error", response=response)
    else:
        response.raise_for_status.return_value = None
    return response


def _rows(start: int, count: int, field: str = "updatedAt") -> list[dict[str, Any]]:
    return [
        {"id": f"id-{index:04d}", field: f"2026-01-01T00:00:{index % 60:02d}+00:00", "status": "ACTIVE"}
        for index in range(start, start + count)
    ]


def _page(rows: list[dict[str, Any]], query_name: str = "Subscriptions") -> dict[str, Any]:
    return {"data": {query_name: rows}}


def _manager(resume: SkioResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _run(
    session: MagicMock,
    endpoint: str = "subscriptions",
    manager: MagicMock | None = None,
    **kwargs: Any,
) -> tuple[list[list[dict[str, Any]]], MagicMock]:
    manager = manager if manager is not None else _manager()
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.skio.skio.make_tracked_session",
        return_value=session,
    ):
        batches = list(
            get_rows(
                api_token=TOKEN,
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
                **kwargs,
            )
        )
    return batches, manager


def _request_variables(session: MagicMock, call_index: int) -> dict[str, Any]:
    return session.post.call_args_list[call_index].kwargs["json"]["variables"]


class TestSkioTransport:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04T02:58:14+00:00", "2026-03-04T02:58:14+00:00"),
        ],
    )
    def test_format_timestamp(self, value: Any, expected: str) -> None:
        assert _format_timestamp(value) == expected

    def test_order_by_puts_cursor_field_before_id_tiebreak(self) -> None:
        assert _build_order_by("updatedAt") == [{"updatedAt": "asc"}, {"id": "asc"}]
        assert _build_order_by(None) == [{"id": "asc"}]

    @pytest.mark.parametrize(
        ("_name", "incremental_field", "last_value", "cursor", "expected"),
        [
            ("full_refresh_first_page", None, None, None, None),
            ("full_refresh_next_page", None, None, SkioResumeConfig(last_id="id-0099"), {"id": {"_gt": "id-0099"}}),
            (
                "incremental_first_page",
                "updatedAt",
                datetime(2026, 1, 1, tzinfo=UTC),
                None,
                {"updatedAt": {"_gte": "2026-01-01T00:00:00+00:00"}},
            ),
            (
                "incremental_next_page",
                "updatedAt",
                datetime(2026, 1, 1, tzinfo=UTC),
                SkioResumeConfig(last_id="id-0099", last_value="2026-01-02T00:00:00+00:00"),
                {
                    "_and": [
                        {"updatedAt": {"_gte": "2026-01-01T00:00:00+00:00"}},
                        {
                            "_or": [
                                {"updatedAt": {"_gt": "2026-01-02T00:00:00+00:00"}},
                                {
                                    "_and": [
                                        {"updatedAt": {"_eq": "2026-01-02T00:00:00+00:00"}},
                                        {"id": {"_gt": "id-0099"}},
                                    ]
                                },
                            ]
                        },
                    ]
                },
            ),
        ],
    )
    def test_build_where(
        self,
        _name: str,
        incremental_field: str | None,
        last_value: Any,
        cursor: SkioResumeConfig | None,
        expected: dict[str, Any] | None,
    ) -> None:
        assert _build_where(incremental_field, last_value, cursor) == expected

    def test_paginates_with_keyset_cursor_until_short_page(self) -> None:
        session = MagicMock()
        session.post.side_effect = [
            _response(_page(_rows(0, SKIO_PAGE_SIZE))),
            _response(_page(_rows(SKIO_PAGE_SIZE, 40))),
        ]

        batches, _ = _run(session)

        assert [len(batch) for batch in batches] == [SKIO_PAGE_SIZE, 40]
        assert session.post.call_count == 2
        # The second request continues strictly past the last row of the first page.
        assert _request_variables(session, 1)["where"] == {"id": {"_gt": f"id-{SKIO_PAGE_SIZE - 1:04d}"}}

    def test_full_refresh_first_request_has_no_watermark(self) -> None:
        session = MagicMock()
        session.post.side_effect = [_response(_page(_rows(0, 3)))]

        _run(
            session,
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        variables = _request_variables(session, 0)
        assert "where" not in variables
        assert variables["orderBy"] == [{"id": "asc"}]
        assert variables["limit"] == SKIO_PAGE_SIZE

    def test_incremental_request_filters_and_orders_on_cursor_field(self) -> None:
        session = MagicMock()
        session.post.side_effect = [_response(_page(_rows(0, 3)))]

        _run(
            session,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="updatedAt",
        )

        variables = _request_variables(session, 0)
        assert variables["where"] == {"updatedAt": {"_gte": "2026-01-01T00:00:00+00:00"}}
        assert variables["orderBy"] == [{"updatedAt": "asc"}, {"id": "asc"}]

    def test_sends_documented_authorization_header(self) -> None:
        # Skio's auth header is `authorization: API <token>`. The `API ` prefix and lowercase
        # header name are the documented, case-sensitive contract.
        session = MagicMock()
        session.post.side_effect = [_response(_page(_rows(0, 1)))]

        _run(session)

        assert session.post.call_args_list[0].kwargs["headers"] == {"authorization": f"API {TOKEN}"}

    def test_resumes_from_saved_cursor(self) -> None:
        session = MagicMock()
        session.post.side_effect = [_response(_page(_rows(0, 2)))]
        manager = _manager(resume=SkioResumeConfig(last_id="id-0042", last_value=None))

        _run(session, manager=manager)

        assert _request_variables(session, 0)["where"] == {"id": {"_gt": "id-0042"}}

    def test_saves_cursor_before_yielding_the_batch_it_covers(self) -> None:
        session = MagicMock()
        session.post.side_effect = [
            _response(_page(_rows(0, SKIO_PAGE_SIZE))),
            _response(_page(_rows(SKIO_PAGE_SIZE, 1))),
        ]
        manager = _manager()
        saved: list[str | None] = []
        manager.save_state.side_effect = lambda cursor: saved.append(cursor.last_id)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.skio.skio.make_tracked_session",
            return_value=session,
        ):
            generator = get_rows(
                api_token=TOKEN,
                endpoint="subscriptions",
                logger=MagicMock(),
                resumable_source_manager=manager,
            )
            next(generator)

        # The cursor covering page one is staged before the yield hands the page to the pipeline,
        # so the pipeline's post-write commit persists exactly the rows already written.
        assert saved == [f"id-{SKIO_PAGE_SIZE - 1:04d}"]

    def test_empty_first_page_yields_nothing(self) -> None:
        session = MagicMock()
        session.post.side_effect = [_response(_page([]))]

        batches, manager = _run(session)

        assert batches == []
        manager.save_state.assert_not_called()

    def test_graphql_errors_raise_with_verbatim_api_message(self) -> None:
        session = MagicMock()
        session.post.side_effect = [_response(INVALID_TOKEN_BODY)]

        with pytest.raises(SkioAPIError, match="Invalid response from authorization hook"):
            _run(session)

    def test_http_error_propagates_for_transport_retry_classification(self) -> None:
        session = MagicMock()
        session.post.side_effect = [_response({}, status_code=403)]

        with pytest.raises(requests.HTTPError):
            _run(session)


class TestValidateCredentials:
    def _validate(self, session: MagicMock) -> tuple[bool, str | None]:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.skio.skio.make_tracked_session",
            return_value=session,
        ):
            return validate_credentials(TOKEN)

    def test_valid_token(self) -> None:
        session = MagicMock()
        session.post.return_value = _response(_page(_rows(0, 1)))

        assert self._validate(session) == (True, None)

    def test_invalid_token_maps_to_user_message(self) -> None:
        session = MagicMock()
        session.post.return_value = _response(INVALID_TOKEN_BODY)

        assert self._validate(session) == (False, "Invalid Skio API token")

    def test_token_without_table_access_maps_to_user_message(self) -> None:
        # Verbatim live-API message when the token's role cannot see the collection.
        session = MagicMock()
        session.post.return_value = _response(
            {"errors": [{"message": "field 'Subscriptions' not found in type: 'query_root'"}]}
        )

        assert self._validate(session) == (False, "Invalid Skio API token")

    def test_connection_error_reports_unreachable(self) -> None:
        session = MagicMock()
        session.post.side_effect = requests.ConnectionError("boom")

        valid, message = self._validate(session)
        assert valid is False
        assert message == "Could not connect to the Skio API"

    def test_other_graphql_error_surfaces_message(self) -> None:
        session = MagicMock()
        session.post.return_value = _response({"errors": [{"message": "query is not in any of the allowlists"}]})

        valid, message = self._validate(session)
        assert valid is False
        assert message is not None and "query is not in any of the allowlists" in message


def test_get_rows_is_a_generator_and_defers_requests() -> None:
    # SourceResponse.items is called lazily; building the iterator must not hit the API.
    session = MagicMock()
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.skio.skio.make_tracked_session",
        return_value=session,
    ):
        generator = get_rows(
            api_token=TOKEN,
            endpoint="subscriptions",
            logger=MagicMock(),
            resumable_source_manager=_manager(),
        )
    assert isinstance(generator, Iterator)
    session.post.assert_not_called()
