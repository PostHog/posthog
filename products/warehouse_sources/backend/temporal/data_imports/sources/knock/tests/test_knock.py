import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Optional, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.knock import (
    KnockResumeConfig,
    get_resource,
    knock_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.settings import ENDPOINTS_CONFIG


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(endpoint: str, rows: list[dict[str, Any]], after: str | None) -> Response:
    selector = ENDPOINTS_CONFIG[endpoint].data_selector
    return _make_http_response({selector: rows, "page_info": {"after": after, "before": None, "page_size": 50}})


class TestGetResource:
    @parameterized.expand(
        [
            ("messages", "inserted_at[gte]"),
            ("workflow_recipient_runs", "starting_at"),
        ]
    )
    def test_incremental_uses_endpoint_specific_server_filter(self, endpoint: str, expected_param: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)
        params = cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])
        assert params[expected_param]["type"] == "incremental"
        assert params[expected_param]["cursor_path"] == "inserted_at"
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    @parameterized.expand([("messages",), ("users",), ("tenants",), ("workflow_recipient_runs",)])
    def test_full_refresh_sends_no_timestamp_filter(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)
        params = cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])
        assert set(params) == {"page_size"}
        assert resource["write_disposition"] == "replace"


class TestKnockSourceTransport:
    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Optional[Any] = None,
    ) -> tuple[SourceResponse, list[dict[str, Any]], list[dict[str, Any]]]:
        # Capture shallow copies of request.params at send-time: the Request object is
        # mutated in place by the paginator between pages.
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = knock_source(
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
            # Messages and workflow recipient runs wrap rows in `items`; users and
            # tenants wrap them in `entries` — a swapped selector syncs 0 rows.
            ("messages",),
            ("users",),
        ]
    )
    def test_rows_extracted_from_endpoint_envelope(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_page(endpoint, [{"id": "a"}, {"id": "b"}], after=None)]
        _, _, rows = self._drive(endpoint, manager, responses)

        assert [row["id"] for row in rows] == ["a", "b"]

    def test_fresh_run_pages_on_after_cursor_and_saves_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _page("messages", [{"id": "m1"}], after="cursor-1"),
            _page("messages", [{"id": "m2"}], after="cursor-2"),
            _page("messages", [{"id": "m3"}], after=None),
        ]
        _, sent_params, rows = self._drive("messages", manager, responses)

        assert [p.get("after") for p in sent_params] == [None, "cursor-1", "cursor-2"]
        # page_size rides along on every request.
        assert all(p.get("page_size") == 50 for p in sent_params)
        assert [row["id"] for row in rows] == ["m1", "m2", "m3"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [KnockResumeConfig(after="cursor-1"), KnockResumeConfig(after="cursor-2")]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = KnockResumeConfig(after="cursor-resumed")

        responses = [_page("messages", [{"id": "m9"}], after=None)]
        _, sent_params, _ = self._drive("messages", manager, responses)

        assert [p.get("after") for p in sent_params] == ["cursor-resumed"]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        self._drive("messages", manager, [_page("messages", [{"id": "only"}], after=None)])

        manager.save_state.assert_not_called()

    def test_incremental_run_sends_watermark_as_iso8601(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_page("messages", [{"id": "m1", "inserted_at": "2026-06-01T00:00:00Z"}], after=None)]
        _, sent_params, _ = self._drive(
            "messages",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 5, 1, 12, 30),
        )

        assert sent_params[0]["inserted_at[gte]"] == "2026-05-01T12:30:00"

    @parameterized.expand(
        [
            ("messages", ["inserted_at"]),
            ("workflow_recipient_runs", ["inserted_at"]),
            ("users", None),
            ("tenants", None),
        ]
    )
    def test_source_response_partitioning_and_sort_mode(self, endpoint: str, partition_keys: list[str] | None) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        source_response, _, _ = self._drive(endpoint, manager, [_page(endpoint, [], after=None)])

        assert source_response.primary_keys == ["id"]
        # Knock lists return newest-first, so the pipeline must not checkpoint the
        # watermark per batch.
        assert source_response.sort_mode == "desc"
        assert source_response.partition_keys == partition_keys
        assert source_response.partition_mode == ("datetime" if partition_keys else None)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, {}, (True, None)),
            (
                "invalid_key",
                401,
                {"code": "api_key_invalid", "message": "The API key you supplied is invalid"},
                (False, "The API key you supplied is invalid"),
            ),
            ("auth_error_without_body", 401, {}, (False, "Invalid Knock API key")),
            ("server_error", 500, {}, (False, "Knock API returned an unexpected response (HTTP 500)")),
        ]
    )
    def test_status_mapping(
        self, _name: str, status_code: int, body: dict[str, Any], expected: tuple[bool, str | None]
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.knock.knock.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = _make_http_response(body, status_code)
            assert validate_credentials("sk_test") == expected
