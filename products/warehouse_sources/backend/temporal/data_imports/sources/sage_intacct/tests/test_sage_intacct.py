from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.sage_intacct import (
    API_BASE_URL,
    CORE_FIELDS,
    SageIntacctResumeConfig,
    SageIntacctRetryableError,
    _field_paths,
    _flatten,
    _format_datetime,
    _mint_token,
    _query_fields,
    get_rows,
    sage_intacct_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.settings import (
    ENDPOINTS,
    SAGE_INTACCT_ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.sage_intacct"


def _response(body: Any, status: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.json.return_value = body
    response.status_code = status
    response.ok = status < 400
    return response


def _manager(resume_state: SageIntacctResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _query_page(rows: list[dict[str, Any]], total_count: int | None = None) -> mock.MagicMock:
    meta: dict[str, Any] = {}
    if total_count is not None:
        meta["totalCount"] = total_count
    return _response({"ia::result": rows, "ia::meta": meta})


def _discovery_responses(sample: dict[str, Any]) -> list[mock.MagicMock]:
    return [
        _response({"ia::result": [{"key": "1", "id": "X-1", "href": "/objects/x/1"}]}),
        _response({"ia::result": sample}),
    ]


def _collect(
    session: mock.MagicMock,
    endpoint: str = "gl_accounts",
    manager: mock.MagicMock | None = None,
    **kwargs: Any,
) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
    resume_manager = manager if manager is not None else _manager()
    with (
        mock.patch(f"{_MODULE}._get_session", return_value=session),
        mock.patch(f"{_MODULE}._mint_token", return_value="tok"),
    ):
        rows: Iterator[list[dict[str, Any]]] = get_rows(
            client_id="cid",
            client_secret="sec",
            refresh_token="ref",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=resume_manager,
            **kwargs,
        )
        return list(rows), resume_manager


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_formats_cursor_values(self, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestFieldDiscoveryHelpers:
    def test_field_paths_expands_one_level_and_skips_metadata(self) -> None:
        sample = {
            "key": "1",
            "id": "ACC-1",
            "href": "/objects/general-ledger/account/1",
            "audit": {"createdDateTime": "t0", "modifiedDateTime": "t1", "href": "/audit"},
            "customer": {"key": "9", "id": "C-1", "nested": {"deeper": 1}},
            "lines": [{"a": 1}],
            "ia::meta": {"totalCount": 1},
        }

        assert _field_paths(sample) == [
            "key",
            "id",
            "audit.createdDateTime",
            "audit.modifiedDateTime",
            "customer.key",
            "customer.id",
        ]

    def test_flatten_joins_nested_blocks_with_underscores(self) -> None:
        record = {
            "key": "1",
            "href": "/objects/x/1",
            "audit": {"createdDateTime": "t0", "href": "/audit"},
            "lines": [1, 2],
            "ia::meta": {"totalCount": 1},
        }

        assert _flatten(record) == {"key": "1", "audit_createdDateTime": "t0", "lines": [1, 2]}

    def test_query_fields_keeps_core_fields_first_and_dedupes(self) -> None:
        assert _query_fields(["name", "key", "name", "audit.modifiedDateTime"]) == [
            *CORE_FIELDS,
            "name",
        ]


class TestMintToken:
    @pytest.mark.parametrize(
        "refresh_token, expected_grant",
        [
            ("ref", "refresh_token"),
            (None, "client_credentials"),
            ("", "client_credentials"),
        ],
    )
    def test_grant_type_follows_refresh_token_presence(self, refresh_token: str | None, expected_grant: str) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response({"access_token": "tok"})

        assert _mint_token(session, "cid", "sec", refresh_token) == "tok"

        payload = session.post.call_args.kwargs["data"]
        assert payload["grant_type"] == expected_grant
        assert payload["client_id"] == "cid"
        assert payload["client_secret"] == "sec"
        assert ("refresh_token" in payload) is (expected_grant == "refresh_token")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # A valid token without GL access must still let the source be created.
            (403, True),
            (401, False),
            (404, False),
        ],
    )
    def test_probe_status_mapping(self, status_code: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response({}, status=status_code)

        with (
            mock.patch(f"{_MODULE}._get_session", return_value=session),
            mock.patch(f"{_MODULE}._mint_token", return_value="tok"),
        ):
            assert validate_credentials("cid", "sec", "ref") is expected

    def test_token_failure_is_invalid(self) -> None:
        with (
            mock.patch(f"{_MODULE}._get_session", return_value=mock.MagicMock()),
            mock.patch(f"{_MODULE}._mint_token", side_effect=Exception("boom")),
        ):
            assert validate_credentials("cid", "sec", None) is False


class TestGetRows:
    def test_discovers_fields_then_queries_with_them(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = _discovery_responses(
            {"key": "1", "id": "ACC-1", "name": "Cash", "audit": {"createdDateTime": "t0"}}
        )
        session.post.side_effect = [_query_page([{"key": "1", "id": "ACC-1", "name": "Cash"}])]

        batches, _ = _collect(session)

        assert batches == [[{"key": "1", "id": "ACC-1", "name": "Cash"}]]
        body = session.post.call_args.kwargs["json"]
        assert body["object"] == "general-ledger/account"
        assert body["fields"] == [*CORE_FIELDS, "name"]
        assert body["start"] == 0
        # No incremental cursor: page ordering falls back to the primary key.
        assert body["orderBy"] == [{"key": "asc"}]
        assert "filters" not in body

    @pytest.mark.parametrize(
        "listing_body",
        [
            {"ia::result": []},
            {"ia::result": [{"href": "/objects/x/1"}]},
        ],
    )
    def test_falls_back_to_core_fields_when_no_sample_record(self, listing_body: dict[str, Any]) -> None:
        session = mock.MagicMock()
        session.get.side_effect = [_response(listing_body)]
        session.post.side_effect = [_query_page([])]

        batches, _ = _collect(session)

        assert batches == []
        assert session.post.call_args.kwargs["json"]["fields"] == list(CORE_FIELDS)

    def test_flattens_nested_response_records(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = _discovery_responses({"key": "1", "audit": {"modifiedDateTime": "t1"}})
        session.post.side_effect = [
            _query_page([{"key": "1", "href": "/objects/x/1", "audit": {"modifiedDateTime": "t1"}}])
        ]

        batches, _ = _collect(session)

        assert batches == [[{"key": "1", "audit_modifiedDateTime": "t1"}]]

    @mock.patch(f"{_MODULE}.PAGE_SIZE", 2)
    def test_pages_until_a_short_page_and_checkpoints_after_each_yield(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = _discovery_responses({"key": "1"})
        session.post.side_effect = [
            _query_page([{"key": "1"}, {"key": "2"}]),
            _query_page([{"key": "3"}]),
        ]

        batches, manager = _collect(session)

        assert batches == [[{"key": "1"}, {"key": "2"}], [{"key": "3"}]]
        assert [call.kwargs["json"]["start"] for call in session.post.call_args_list] == [0, 2]
        # Checkpointed once, after the first full page; the final short page ends the walk.
        assert manager.save_state.call_count == 1
        assert manager.save_state.call_args.args[0].offset == 2

    @mock.patch(f"{_MODULE}.PAGE_SIZE", 2)
    def test_stops_once_total_count_is_reached(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = _discovery_responses({"key": "1"})
        session.post.side_effect = [_query_page([{"key": "1"}, {"key": "2"}], total_count=2)]

        batches, _ = _collect(session)

        assert batches == [[{"key": "1"}, {"key": "2"}]]
        assert session.post.call_count == 1

    @mock.patch(f"{_MODULE}.PAGE_SIZE", 2)
    def test_resumes_from_saved_offset_without_rediscovering_fields(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = [_query_page([{"key": "3"}])]
        manager = _manager(SageIntacctResumeConfig(offset=2, fields=["key", "id"]))

        batches, _ = _collect(session, manager=manager)

        assert batches == [[{"key": "3"}]]
        assert session.get.call_count == 0
        body = session.post.call_args.kwargs["json"]
        assert body["start"] == 2
        assert body["fields"] == ["key", "id"]

    @pytest.mark.parametrize(
        "incremental_field, expected_path",
        [
            ("audit_modifiedDateTime", "audit.modifiedDateTime"),
            ("audit_createdDateTime", "audit.createdDateTime"),
            # An unmapped field still gets a server-side filter on the modified timestamp.
            ("something_else", "audit.modifiedDateTime"),
        ],
    )
    def test_incremental_filters_and_sorts_on_the_cursor_path(self, incremental_field: str, expected_path: str) -> None:
        session = mock.MagicMock()
        session.get.side_effect = _discovery_responses({"key": "1"})
        session.post.side_effect = [_query_page([])]

        _collect(
            session,
            should_use_incremental_field=True,
            incremental_field=incremental_field,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
        )

        body = session.post.call_args.kwargs["json"]
        assert body["orderBy"] == [{expected_path: "asc"}]
        assert body["filters"] == [{"$gte": {expected_path: "2024-05-01T00:00:00Z"}}]

    def test_first_incremental_sync_sends_no_filter(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = _discovery_responses({"key": "1"})
        session.post.side_effect = [_query_page([])]

        _collect(
            session,
            should_use_incremental_field=True,
            incremental_field="audit_modifiedDateTime",
            db_incremental_field_last_value=None,
        )

        body = session.post.call_args.kwargs["json"]
        assert "filters" not in body
        assert body["orderBy"] == [{"audit.modifiedDateTime": "asc"}]

    def test_expired_token_is_reminted_once(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = _discovery_responses({"key": "1"})
        session.post.side_effect = [_response({}, status=401), _query_page([{"key": "1"}])]

        with (
            mock.patch(f"{_MODULE}._get_session", return_value=session),
            mock.patch(f"{_MODULE}._mint_token", return_value="tok") as mint,
        ):
            batches = list(
                get_rows(
                    client_id="cid",
                    client_secret="sec",
                    refresh_token="ref",
                    endpoint="gl_accounts",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(),
                )
            )

        assert batches == [[{"key": "1"}]]
        # Once up front, once after the 401.
        assert mint.call_count == 2

    @pytest.mark.parametrize("status_code", [429, 500, 503])
    @mock.patch(f"{_MODULE}.MAX_RETRY_ATTEMPTS", 1)
    def test_throttling_and_server_errors_are_retryable(self, status_code: int) -> None:
        session = mock.MagicMock()
        session.get.side_effect = [_response({}, status=status_code)]

        with pytest.raises(SageIntacctRetryableError):
            _collect(session)

    @pytest.mark.parametrize("status_code", [400, 403, 404])
    def test_client_errors_raise(self, status_code: int) -> None:
        response = _response({}, status=status_code)
        response.raise_for_status.side_effect = Exception(f"{status_code} Client Error")
        session = mock.MagicMock()
        session.get.side_effect = [response]

        with pytest.raises(Exception, match="Client Error"):
            _collect(session)


class TestSageIntacctSource:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_response_shape_for_every_endpoint(self, endpoint: str) -> None:
        response = sage_intacct_source(
            client_id="cid",
            client_secret="sec",
            refresh_token=None,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == [SAGE_INTACCT_ENDPOINTS[endpoint].primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        # Creation time never moves, so partitions are not rewritten on every sync.
        assert response.partition_keys == ["audit_createdDateTime"]

    def test_items_streams_rows_lazily(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = _discovery_responses({"key": "1"})
        session.post.side_effect = [_query_page([{"key": "1"}])]

        with (
            mock.patch(f"{_MODULE}._get_session", return_value=session),
            mock.patch(f"{_MODULE}._mint_token", return_value="tok"),
        ):
            response = sage_intacct_source(
                client_id="cid",
                client_secret="sec",
                refresh_token=None,
                endpoint="customers",
                logger=mock.MagicMock(),
                resumable_source_manager=_manager(),
            )
            # Nothing is requested until the pipeline pulls on the iterator.
            assert session.post.call_count == 0
            batches = list(cast("Iterable[list[dict[str, Any]]]", response.items()))

        assert batches == [[{"key": "1"}]]
        assert session.get.call_args_list[0].args[0] == f"{API_BASE_URL}/objects/accounts-receivable/customer"
