import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.mercury import (
    MercuryResumeConfig,
    format_incremental_value,
    get_resource,
    mercury_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.settings import ENDPOINTS


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02"),
            (datetime(2026, 1, 2, 3, 4, 5), "2026-01-02"),
            (date(2026, 1, 2), "2026-01-02"),
            ("2026-01-02T03:04:05Z", "2026-01-02"),
        ],
    )
    def test_formats_watermark_for_the_api(self, value: Any, expected: str | None) -> None:
        assert format_incremental_value(value) == expected


class TestGetResource:
    @pytest.mark.parametrize("endpoint", [name for name in ENDPOINTS if name != "Transactions"])
    def test_full_refresh_endpoints_never_get_incremental_params(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)

        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        assert not any(
            isinstance(value, dict) and value.get("type") == "incremental"
            for value in endpoint_config["params"].values()
        )


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestMercurySourceResumeBehavior:
    """End-to-end pagination and resume behaviour of ``mercury_source`` via ``rest_api_resource``."""

    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict[str, Any]], list[Any]]:
        """Drive ``mercury_source`` with a mocked HTTP session.

        Returns ``(sent_params, rows)`` where ``sent_params`` are shallow copies of
        ``request.params`` captured at send-time — the Request object is mutated in place
        by the paginator between pages.
        """
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

            resource = mercury_source(
                api_key="test-token",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
            )
            pages = list(cast(Iterable[Any], resource))
            rows = [row for page in pages for row in page]
            return sent_params, rows

    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"transactions": [{"id": "t1"}], "page": {"nextPage": "t1"}}),
            _make_http_response({"transactions": [{"id": "t2"}], "page": {"nextPage": "t2"}}),
            _make_http_response({"transactions": [{"id": "t3"}], "page": {"nextPage": None}}),
        ]
        sent_params, rows = self._drive("Transactions", manager, responses)

        assert [p.get("start_after") for p in sent_params] == [None, "t1", "t2"]
        assert [row["id"] for row in rows] == ["t1", "t2", "t3"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            MercuryResumeConfig(cursor="t1"),
            MercuryResumeConfig(cursor="t2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = MercuryResumeConfig(cursor="t42")

        responses = [
            _make_http_response({"transactions": [{"id": "t43"}], "page": {"nextPage": None}}),
        ]
        sent_params, _ = self._drive("Transactions", manager, responses)

        assert [p.get("start_after") for p in sent_params] == ["t42"]
        manager.load_state.assert_called_once()

    def test_incremental_sync_sends_date_only_start_watermark(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"transactions": [{"id": "t1"}], "page": {"nextPage": None}}),
        ]
        sent_params, _ = self._drive(
            "Transactions",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert sent_params[0]["start"] == "2026-01-02"
        assert sent_params[0]["order"] == "asc"
