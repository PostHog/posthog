import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Optional, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.courier import (
    CourierResumeConfig,
    courier_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.settings import ENDPOINTS_CONFIG

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
COURIER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.courier.courier.make_tracked_session"
)


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(endpoint: str, rows: list[dict[str, Any]], cursor: str | None) -> Response:
    """Build a page response using this endpoint's real envelope shape.

    Every endpoint but Tenants nests the cursor under `paging`; Tenants returns it at the
    response's top level.
    """
    config = ENDPOINTS_CONFIG[endpoint]
    body: dict[str, Any] = {config.data_selector: rows}
    if config.cursor_path == "cursor":
        body["cursor"] = cursor
        body["has_more"] = cursor is not None
    else:
        body["paging"] = {"more": cursor is not None, "cursor": cursor}
    return _make_http_response(body)


class TestGetResource:
    def test_incremental_uses_enqueued_after_filter(self) -> None:
        resource = get_resource("Messages", should_use_incremental_field=True)
        params = cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])
        assert params["enqueued_after"]["type"] == "incremental"
        assert params["enqueued_after"]["cursor_path"] == "enqueued"
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    @parameterized.expand([("Messages",), ("AuditEvents",), ("Audiences",), ("Brands",), ("Tenants",)])
    def test_full_refresh_sends_no_timestamp_filter(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)
        params = cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])
        assert set(params) == {"limit"}
        assert resource["write_disposition"] == "replace"

    @parameterized.expand([("AuditEvents",), ("Audiences",), ("Brands",), ("Tenants",)])
    def test_endpoints_without_a_server_filter_ignore_incremental_flag(self, endpoint: str) -> None:
        # These endpoints have no documented server-side timestamp filter, so even if asked for
        # an incremental run there is no filter param to add.
        resource = get_resource(endpoint, should_use_incremental_field=True)
        params = cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])
        assert set(params) == {"limit"}


class TestCourierSourceTransport:
    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Optional[Any] = None,
    ) -> tuple[SourceResponse, list[dict[str, Any]], list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(CLIENT_SESSION_PATCH) as mock_session_factory:
            mock_session = mock_session_factory.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = courier_source(
                api_key="sk_test",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
            )
            rows = [row for chunk in cast(Iterable[Any], source_response.items()) for row in chunk]
            return source_response, sent_params, rows

    @parameterized.expand(
        [
            ("Messages",),
            ("AuditEvents",),
            ("Audiences",),
            ("Brands",),
            ("Tenants",),
        ]
    )
    def test_rows_extracted_from_endpoint_envelope(self, endpoint: str) -> None:
        # A swapped `data_selector` ("results" vs "items", or the wrong top-level cursor key for
        # Tenants) silently syncs 0 rows instead of raising, so this locks the real shape in.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_page(endpoint, [{"id": "a"}, {"id": "b"}], cursor=None)]
        _, _, rows = self._drive(endpoint, manager, responses)

        assert [row["id"] for row in rows] == ["a", "b"]

    def test_fresh_run_pages_on_cursor_and_saves_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _page("Messages", [{"id": "m1"}], cursor="cursor-1"),
            _page("Messages", [{"id": "m2"}], cursor="cursor-2"),
            _page("Messages", [{"id": "m3"}], cursor=None),
        ]
        _, sent_params, rows = self._drive("Messages", manager, responses)

        assert [p.get("cursor") for p in sent_params] == [None, "cursor-1", "cursor-2"]
        assert all(p.get("limit") == 100 for p in sent_params)
        assert [row["id"] for row in rows] == ["m1", "m2", "m3"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [CourierResumeConfig(cursor="cursor-1"), CourierResumeConfig(cursor="cursor-2")]

    def test_tenants_pages_on_top_level_cursor(self) -> None:
        # Tenants is the one endpoint whose cursor lives at the response's top level rather than
        # nested under `paging` — a regression here silently disables pagination.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _page("Tenants", [{"id": "t1"}], cursor="cursor-1"),
            _page("Tenants", [{"id": "t2"}], cursor=None),
        ]
        _, sent_params, rows = self._drive("Tenants", manager, responses)

        assert [p.get("cursor") for p in sent_params] == [None, "cursor-1"]
        assert [row["id"] for row in rows] == ["t1", "t2"]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CourierResumeConfig(cursor="cursor-resumed")

        responses = [_page("Messages", [{"id": "m9"}], cursor=None)]
        _, sent_params, _ = self._drive("Messages", manager, responses)

        assert [p.get("cursor") for p in sent_params] == ["cursor-resumed"]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        self._drive("Messages", manager, [_page("Messages", [{"id": "only"}], cursor=None)])

        manager.save_state.assert_not_called()

    def test_incremental_run_sends_watermark_as_iso8601(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_page("Messages", [{"id": "m1"}], cursor=None)]
        _, sent_params, _ = self._drive(
            "Messages",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 5, 1, 12, 30),
        )

        assert sent_params[0]["enqueued_after"] == "2026-05-01T12:30:00"

    def test_incremental_first_sync_defaults_to_epoch_start(self) -> None:
        # No prior watermark (first incremental sync): must fall back to a real ISO-8601 value,
        # not stringify `None` into the literal "enqueued_after=None".
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_page("Messages", [{"id": "m1"}], cursor=None)]
        _, sent_params, _ = self._drive(
            "Messages",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert sent_params[0]["enqueued_after"] == "1970-01-01T00:00:00Z"

    def test_epoch_millis_fields_are_converted_to_datetime(self) -> None:
        # `enqueued`/`sent`/etc. arrive as epoch-millisecond ints; left unconverted, the
        # partitioner would misread them as epoch seconds and bucket everything into the wrong
        # decade.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_page("Messages", [{"id": "m1", "enqueued": 1_700_000_000_000, "sent": None}], cursor=None)]
        _, _, rows = self._drive("Messages", manager, responses)

        assert rows[0]["enqueued"] == datetime.fromtimestamp(1_700_000_000_000 / 1000, tz=UTC)
        assert rows[0]["sent"] is None

    def test_iso_string_fields_are_converted_to_datetime(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_page("Audiences", [{"id": "a1", "created_at": "2026-01-15T10:30:00Z"}], cursor=None)]
        _, _, rows = self._drive("Audiences", manager, responses)

        assert rows[0]["created_at"] == datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)

    @parameterized.expand(
        [
            ("Messages", ["enqueued"], "desc"),
            ("AuditEvents", ["timestamp"], "asc"),
            ("Audiences", ["created_at"], "asc"),
            ("Brands", None, "asc"),
            ("Tenants", None, "asc"),
        ]
    )
    def test_source_response_partitioning_and_sort_mode(
        self, endpoint: str, partition_keys: list[str] | None, sort_mode: str
    ) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        source_response, _, _ = self._drive(endpoint, manager, [_page(endpoint, [], cursor=None)])

        assert source_response.primary_keys == list(ENDPOINTS_CONFIG[endpoint].primary_keys)
        assert source_response.sort_mode == sort_mode
        assert source_response.partition_keys == partition_keys
        assert source_response.partition_mode == ("datetime" if partition_keys else None)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, (True, None)),
            (
                "invalid_key",
                403,
                (
                    False,
                    "Courier authentication failed: Invalid or missing authentication credentials. Please check your API key.",
                ),
            ),
            ("server_error", 500, (False, "Courier API returned an unexpected response (HTTP 500)")),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: tuple[bool, str | None]) -> None:
        with patch(COURIER_SESSION_PATCH) as mock_make_session:
            mock_make_session.return_value.get.return_value = _make_http_response({}, status_code)
            assert validate_credentials("sk_test") == expected

    def test_network_error_is_false(self) -> None:
        with patch(COURIER_SESSION_PATCH) as mock_make_session:
            mock_make_session.return_value.get.side_effect = Exception("boom")
            ok, message = validate_credentials("sk_test")
            assert ok is False
