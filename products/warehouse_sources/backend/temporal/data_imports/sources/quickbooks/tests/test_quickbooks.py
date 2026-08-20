from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.quickbooks.quickbooks import (
    PAGE_SIZE,
    QUICKBOOKS_MINOR_VERSION,
    QuickBooksResumeConfig,
    build_query,
    company_url,
    escape_query_literal,
    extract_rows,
    format_query_timestamp,
    get_rows,
    normalize_row,
    quickbooks_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.quickbooks.settings import (
    ENDPOINTS,
    QUICKBOOKS_ENTITIES,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.quickbooks.quickbooks"

_REALM_ID = "123456789"
_ACCESS_TOKEN = "access-token"
_API_VERSION = "v3"


def _manager(resume_state: QuickBooksResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _run_validate(environment: str = "production") -> bool:
    return validate_credentials(
        environment=environment,
        realm_id=_REALM_ID,
        access_token=_ACCESS_TOKEN,
        api_version=_API_VERSION,
    )


def _run_get_rows(
    entity_name: str,
    resumable_source_manager: mock.MagicMock,
    logger: Optional[mock.MagicMock] = None,
    environment: str = "production",
    refresh_access_token: Optional[Callable[[], str]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    return get_rows(
        environment=environment,
        realm_id=_REALM_ID,
        access_token=_ACCESS_TOKEN,
        entity_name=entity_name,
        api_version=_API_VERSION,
        logger=logger or mock.MagicMock(),
        resumable_source_manager=cast(ResumableSourceManager[QuickBooksResumeConfig], resumable_source_manager),
        refresh_access_token=refresh_access_token,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


def _build_source(entity_name: str, resumable_source_manager: mock.MagicMock) -> SourceResponse:
    return quickbooks_source(
        environment="production",
        realm_id=_REALM_ID,
        access_token=_ACCESS_TOKEN,
        entity_name=entity_name,
        api_version=_API_VERSION,
        logger=mock.MagicMock(),
        resumable_source_manager=cast(ResumableSourceManager[QuickBooksResumeConfig], resumable_source_manager),
    )


def _row(row_id: str, last_updated: str = "2024-01-02T03:04:05-08:00") -> dict[str, Any]:
    return {
        "Id": row_id,
        "MetaData": {"CreateTime": "2023-05-06T07:08:09-08:00", "LastUpdatedTime": last_updated},
    }


def _query_response(entity: str, rows: list[dict[str, Any]]) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = {"QueryResponse": {entity: rows} if rows else {}, "time": "2024-01-01T00:00:00Z"}
    return response


def _error_response(status_code: int, message: Optional[str] = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = False
    if message is not None:
        response.raise_for_status.side_effect = Exception(message)
    return response


def _urls_requested(session: mock.MagicMock) -> list[str]:
    return [call.args[0] for call in session.get.call_args_list]


def _queries_sent(session: mock.MagicMock) -> list[str]:
    return [parse_qs(urlparse(url).query)["query"][0] for url in _urls_requested(session)]


def _collect(batches: Iterable[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [row for batch in batches for row in batch]


class TestFormatQueryTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05+00:00"),
            # A naive datetime is read as UTC rather than dropped.
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05+00:00"),
            (date(2024, 1, 2), "2024-01-02T00:00:00+00:00"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05+00:00"),
            # QuickBooks returns Pacific offsets; the filter has to be normalized to UTC.
            ("2024-01-02T03:04:05-08:00", "2024-01-02T11:04:05+00:00"),
            ("2024-01-02", "2024-01-02T00:00:00+00:00"),
            ("not-a-date", None),
            (None, None),
            (12345, None),
        ],
    )
    def test_formats_watermarks(self, value: Any, expected: Optional[str]) -> None:
        assert format_query_timestamp(value) == expected


class TestEscapeQueryLiteral:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("plain", "plain"),
            ("O'Brien", "O\\'Brien"),
            ("back\\slash", "back\\\\slash"),
        ],
    )
    def test_escapes_literals(self, value: str, expected: str) -> None:
        assert escape_query_literal(value) == expected


class TestBuildQuery:
    def test_full_refresh_page_has_no_where_clause(self) -> None:
        query = build_query(QUICKBOOKS_ENTITIES["Invoice"], since=None, start_position=1, page_size=100)

        assert query == "SELECT * FROM Invoice ORDERBY Metadata.LastUpdatedTime STARTPOSITION 1 MAXRESULTS 100"

    def test_incremental_page_filters_server_side(self) -> None:
        query = build_query(
            QUICKBOOKS_ENTITIES["Invoice"],
            since="2024-01-02T03:04:05+00:00",
            start_position=501,
            page_size=500,
        )

        assert query == (
            "SELECT * FROM Invoice WHERE Metadata.LastUpdatedTime > '2024-01-02T03:04:05+00:00' "
            "ORDERBY Metadata.LastUpdatedTime STARTPOSITION 501 MAXRESULTS 500"
        )

    @pytest.mark.parametrize("entity_name", ["CompanyInfo", "Preferences"])
    def test_singletons_take_no_clauses(self, entity_name: str) -> None:
        # Pagination and ordering clauses on a one-row entity are pure risk with no benefit.
        query = build_query(QUICKBOOKS_ENTITIES[entity_name], since="2024-01-02T03:04:05+00:00", start_position=7)

        assert query == f"SELECT * FROM {entity_name}"


class TestExtractRows:
    def test_reads_rows_under_the_entity_key(self) -> None:
        body = {"QueryResponse": {"Customer": [{"Id": "1"}, {"Id": "2"}]}}

        assert extract_rows(body, "Customer") == [{"Id": "1"}, {"Id": "2"}]

    @pytest.mark.parametrize(
        "body",
        [
            # An exhausted result set comes back as an empty QueryResponse, not an empty list.
            {"QueryResponse": {}, "time": "2024-01-01T00:00:00Z"},
            {"QueryResponse": {"Invoice": []}},
            {"QueryResponse": None},
            {},
        ],
    )
    def test_empty_bodies_yield_no_rows(self, body: dict[str, Any]) -> None:
        assert extract_rows(body, "Invoice") == []

    def test_bare_object_is_wrapped(self) -> None:
        assert extract_rows({"QueryResponse": {"CompanyInfo": {"Id": "1"}}}, "CompanyInfo") == [{"Id": "1"}]

    def test_other_entities_are_ignored(self) -> None:
        assert extract_rows({"QueryResponse": {"Customer": [{"Id": "1"}]}}, "Invoice") == []


class TestNormalizeRow:
    def test_hoists_metadata_timestamps(self) -> None:
        normalized = normalize_row(_row("1"))

        assert normalized["CreateTime"] == "2023-05-06T07:08:09-08:00"
        assert normalized["LastUpdatedTime"] == "2024-01-02T03:04:05-08:00"
        # The nested block is left in place alongside the hoisted copies.
        assert normalized["MetaData"]["LastUpdatedTime"] == "2024-01-02T03:04:05-08:00"

    def test_row_without_metadata_is_untouched(self) -> None:
        row = {"Id": "1"}

        assert normalize_row(row) is row

    def test_existing_top_level_field_wins(self) -> None:
        row = {"Id": "1", "CreateTime": "own", "MetaData": {"CreateTime": "meta"}}

        assert normalize_row(row)["CreateTime"] == "own"


class TestCompanyUrl:
    @pytest.mark.parametrize(
        "environment, expected",
        [
            ("production", "https://quickbooks.api.intuit.com/v3/company/42"),
            ("sandbox", "https://sandbox-quickbooks.api.intuit.com/v3/company/42"),
        ],
    )
    def test_environment_selects_host(self, environment: str, expected: str) -> None:
        assert company_url(environment, "42", "v3") == expected

    def test_unknown_environment_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid QuickBooks environment"):
            company_url("staging", "42", "v3")


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_when_company_query_succeeds(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _query_response("CompanyInfo", [{"Id": "1"}])

        assert _run_validate() is True
        assert session.get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {_ACCESS_TOKEN}"

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 500])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_error_status(self, mock_session: mock.MagicMock, status_code: int) -> None:
        session = mock_session.return_value
        session.get.return_value = _error_response(status_code)

        assert _run_validate() is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_the_request_fails(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("connection reset")

        assert _run_validate() is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_environment_is_rejected_without_a_request(self, mock_session: mock.MagicMock) -> None:
        assert _run_validate(environment="staging") is False
        mock_session.return_value.get.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_secrets_are_redacted_from_the_tracked_session(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _query_response("CompanyInfo", [])

        _run_validate()

        assert set(mock_session.call_args.kwargs["redact_values"]) == {_ACCESS_TOKEN}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_response_bodies_are_not_captured(self, mock_session: mock.MagicMock) -> None:
        # Every row this session carries is accounting data, so the bodies must stay out of the
        # shared HTTP sample store — the generic scrubber can't recognize amounts, memos or tax ids.
        mock_session.return_value.get.return_value = _query_response("CompanyInfo", [])

        _run_validate()

        assert mock_session.call_args.kwargs["capture"] is False


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_single_short_page_ends_the_walk(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _query_response("Customer", [_row("1"), _row("2")])

        manager = _manager()
        rows = _collect(_run_get_rows("Customer", manager))

        assert [row["Id"] for row in rows] == ["1", "2"]
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_offset_advances_until_a_short_page(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.side_effect = [
            _query_response("Customer", [_row(str(index)) for index in range(PAGE_SIZE)]),
            _query_response("Customer", [_row("last")]),
        ]

        manager = _manager()
        rows = _collect(_run_get_rows("Customer", manager))

        assert len(rows) == PAGE_SIZE + 1
        queries = _queries_sent(session)
        assert "STARTPOSITION 1 " in queries[0]
        assert f"STARTPOSITION {1 + PAGE_SIZE} " in queries[1]
        # State is saved once, only after the full page was yielded.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].start_position == 1 + PAGE_SIZE

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_first_page_yields_nothing(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _query_response("Invoice", [])

        manager = _manager()
        batches = list(_run_get_rows("Invoice", manager))

        assert batches == []
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_pushes_the_watermark_into_the_query(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _query_response("Invoice", [_row("1")])

        _collect(
            _run_get_rows(
                "Invoice",
                _manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
            )
        )

        assert "WHERE Metadata.LastUpdatedTime > '2024-03-01T00:00:00+00:00'" in _queries_sent(session)[0]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_ignores_a_stored_watermark(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _query_response("Invoice", [_row("1")])

        _collect(
            _run_get_rows(
                "Invoice",
                _manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
            )
        )

        assert "WHERE" not in _queries_sent(session)[0]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_restores_offset_and_its_original_filter(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _query_response("Invoice", [_row("1")])

        # A saved offset only identifies a row inside the result set of the query that produced
        # it, so the saved bound has to win over a watermark that moved on since.
        manager = _manager(QuickBooksResumeConfig(start_position=1001, since="2024-01-01T00:00:00+00:00"))
        _collect(
            _run_get_rows(
                "Invoice",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 6, 1, tzinfo=UTC),
            )
        )

        query = _queries_sent(session)[0]
        assert "STARTPOSITION 1001" in query
        assert "WHERE Metadata.LastUpdatedTime > '2024-01-01T00:00:00+00:00'" in query

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_singleton_never_paginates(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _query_response("CompanyInfo", [_row("1")])

        manager = _manager()
        rows = _collect(_run_get_rows("CompanyInfo", manager))

        assert [row["Id"] for row in rows] == ["1"]
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rejected_token_is_renewed_once(self, mock_session: mock.MagicMock) -> None:
        # Intuit access tokens last an hour, which a large company's sync can outlive.
        session = mock_session.return_value
        session.get.side_effect = [_error_response(401), _query_response("Invoice", [_row("1")])]
        renew = mock.MagicMock(return_value="renewed")

        rows = _collect(_run_get_rows("Invoice", _manager(), refresh_access_token=renew))

        assert [row["Id"] for row in rows] == ["1"]
        renew.assert_called_once_with()
        tokens = [call.kwargs["headers"]["Authorization"] for call in session.get.call_args_list]
        assert tokens == [f"Bearer {_ACCESS_TOKEN}", "Bearer renewed"]
        # The renewed token is redacted from the tracked transport too.
        assert set(mock_session.call_args.kwargs["redact_values"]) == {"renewed"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_persistent_401_is_raised(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _error_response(
            401, "401 Client Error: Unauthorized for url: https://quickbooks.api.intuit.com"
        )

        with pytest.raises(Exception, match="401 Client Error"):
            _collect(_run_get_rows("Invoice", _manager(), refresh_access_token=lambda: "renewed"))

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_401_without_a_renewer_is_raised(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _error_response(401, "401 Client Error: Unauthorized")

        with pytest.raises(Exception, match="401 Client Error"):
            _collect(_run_get_rows("Invoice", _manager()))

        assert session.get.call_count == 1

    @pytest.mark.parametrize("status_code", [400, 403])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_error_statuses_are_logged_and_raised(self, mock_session: mock.MagicMock, status_code: int) -> None:
        session = mock_session.return_value
        session.get.return_value = _error_response(status_code, f"{status_code} error")

        logger = mock.MagicMock()
        with pytest.raises(Exception, match=f"{status_code} error"):
            _collect(_run_get_rows("Invoice", _manager(), logger=logger))

        logger.error.assert_called_once()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_minor_version_is_pinned_on_every_request(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _query_response("Invoice", [_row("1")])

        _collect(_run_get_rows("Invoice", _manager()))

        query_string = parse_qs(urlparse(_urls_requested(session)[0]).query)
        assert query_string["minorversion"] == [QUICKBOOKS_MINOR_VERSION]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rows_are_normalized_before_yielding(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _query_response("Invoice", [_row("1")])

        rows = _collect(_run_get_rows("Invoice", _manager()))

        assert rows[0]["LastUpdatedTime"] == "2024-01-02T03:04:05-08:00"
        assert rows[0]["CreateTime"] == "2023-05-06T07:08:09-08:00"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_sandbox_environment_targets_the_sandbox_host(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _query_response("Invoice", [])

        list(_run_get_rows("Invoice", _manager(), environment="sandbox"))

        assert _urls_requested(session)[0].startswith(
            f"https://sandbox-quickbooks.api.intuit.com/v3/company/{_REALM_ID}/query"
        )


class TestQuickBooksSourceResponse:
    @pytest.mark.parametrize("entity_name", list(ENDPOINTS))
    def test_response_metadata_per_entity(self, entity_name: str) -> None:
        entity = QUICKBOOKS_ENTITIES[entity_name]
        response = _build_source(entity_name, _manager())

        assert response.name == entity_name
        assert response.primary_keys == ["Id"]
        # Ascending ORDERBY is what the pipeline's watermark checkpointing assumes.
        assert response.sort_mode == "asc"
        if entity.singleton:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["CreateTime"]

    @pytest.mark.parametrize("entity_name", list(ENDPOINTS))
    def test_partition_key_is_a_stable_creation_field(self, entity_name: str) -> None:
        # Partitioning on LastUpdatedTime would rewrite partitions on every sync.
        assert QUICKBOOKS_ENTITIES[entity_name].partition_key in (None, "CreateTime")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_items_is_lazy(self, mock_session: mock.MagicMock) -> None:
        response = _build_source("Invoice", _manager())

        # Nothing is requested until the pipeline pulls the first batch.
        mock_session.return_value.get.assert_not_called()

        session = mock_session.return_value
        session.get.return_value = _query_response("Invoice", [_row("1")])
        rows = _collect(cast("Iterable[Any]", response.items()))

        assert [row["Id"] for row in rows] == ["1"]
