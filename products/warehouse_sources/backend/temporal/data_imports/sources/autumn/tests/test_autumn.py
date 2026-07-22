import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Optional, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.autumn import (
    AutumnResumeConfig,
    _build_request_body,
    autumn_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.settings import (
    AUTUMN_ENDPOINTS,
    PARTITION_BUCKET_MILLISECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

WATERMARK_MS = 1704067200000


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestBuildRequestBody:
    @pytest.mark.parametrize(
        ("endpoint", "should_use_incremental_field", "incremental_field", "last_value", "expected"),
        [
            ("Customers", False, None, None, {"limit": 100}),
            ("Events", False, None, None, {"limit": 1000}),
            # First incremental sync has no watermark yet — no custom_range.
            ("Events", True, "timestamp", None, {"limit": 1000}),
            (
                "Events",
                True,
                "timestamp",
                WATERMARK_MS,
                {"limit": 1000, "custom_range": {"start": WATERMARK_MS}},
            ),
            # The user's chosen incremental field is honored — an unknown field is not
            # silently mapped onto the timestamp filter.
            ("Events", True, "created_at", WATERMARK_MS, {"limit": 1000}),
            # Only events.list supports the server-side time filter.
            ("Customers", True, "created_at", WATERMARK_MS, {"limit": 100}),
            ("Coupons", False, None, None, {}),
        ],
    )
    def test_body_shape(
        self,
        endpoint: str,
        should_use_incremental_field: bool,
        incremental_field: Optional[str],
        last_value: Optional[Any],
        expected: dict[str, Any],
    ) -> None:
        body = _build_request_body(
            AUTUMN_ENDPOINTS[endpoint],
            should_use_incremental_field,
            incremental_field,
            last_value,
        )
        assert body == expected

    def test_datetime_watermark_is_coerced_to_epoch_ms(self) -> None:
        body = _build_request_body(
            AUTUMN_ENDPOINTS["Events"],
            True,
            "timestamp",
            datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert body["custom_range"] == {"start": WATERMARK_MS}


class TestAutumnSourceBehavior:
    """End-to-end behavior of ``autumn_source`` via ``rest_api_resource`` with a mocked session."""

    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Optional[Any] = None,
        incremental_field: Optional[str] = None,
    ) -> tuple[MagicMock, list[dict[str, Any]], list[dict[str, Any]]]:
        """Returns ``(mock_session, sent_bodies, rows)``. ``sent_bodies`` are shallow copies of
        ``request.json`` captured at send-time — the Request object is mutated in place by the
        paginator between pages."""
        sent_bodies: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_bodies.append(dict(request.json or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = autumn_source(
                api_key="am_sk_test",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                api_version="2.3.0",
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
                incremental_field=incremental_field,
            )
            rows = [row for page in cast(Iterable[Any], source_response.items()) for row in page]
            return mock_session, sent_bodies, rows

    def test_fresh_run_pages_with_body_cursor_and_saves_state_after_each_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"list": [{"id": "cus_1"}], "next_cursor": "cursor-1"}),
            _make_http_response({"list": [{"id": "cus_2"}], "next_cursor": "cursor-2"}),
            _make_http_response({"list": [{"id": "cus_3"}], "next_cursor": None}),
        ]
        _, sent_bodies, rows = self._drive("Customers", manager, responses)

        assert [body.get("start_cursor") for body in sent_bodies] == [None, "cursor-1", "cursor-2"]
        assert all(body["limit"] == 100 for body in sent_bodies)
        assert [row["id"] for row in rows] == ["cus_1", "cus_2", "cus_3"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            AutumnResumeConfig(next_cursor="cursor-1"),
            AutumnResumeConfig(next_cursor="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = AutumnResumeConfig(next_cursor="cursor-resumed")

        responses = [
            _make_http_response({"list": [{"id": "cus_4"}], "next_cursor": None}),
        ]
        _, sent_bodies, _ = self._drive("Customers", manager, responses)

        assert [body.get("start_cursor") for body in sent_bodies] == ["cursor-resumed"]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"list": [{"id": "only"}], "next_cursor": None}),
        ]
        self._drive("Customers", manager, responses)

        manager.save_state.assert_not_called()

    def test_incremental_events_run_carries_custom_range_on_every_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"list": [{"id": "evt_1", "timestamp": 1}], "next_cursor": "cursor-1"}),
            _make_http_response({"list": [{"id": "evt_2", "timestamp": 2}], "next_cursor": None}),
        ]
        _, sent_bodies, _ = self._drive(
            "Events",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=WATERMARK_MS,
            incremental_field="timestamp",
        )

        assert all(body["custom_range"] == {"start": WATERMARK_MS} for body in sent_bodies)

    @pytest.mark.parametrize(
        ("endpoint", "selector", "row_id"),
        [
            ("Coupons", "coupons", "coupon_1"),
            ("FeatureGrants", "feature_grants", "grant_1"),
        ],
    )
    def test_single_page_endpoints_issue_one_request_and_select_their_root_array(
        self, endpoint: str, selector: str, row_id: str
    ) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"coupons": [{"id": "coupon_1"}], "feature_grants": [{"id": "grant_1"}]}),
        ]
        _, sent_bodies, rows = self._drive(endpoint, manager, responses)

        assert len(sent_bodies) == 1
        assert [row["id"] for row in rows] == [row_id]
        manager.save_state.assert_not_called()
        manager.load_state.assert_not_called()

    def test_required_api_version_header_is_set_on_the_session(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"list": [], "next_cursor": None}),
        ]
        mock_session, _, _ = self._drive("Customers", manager, responses)

        assert mock_session.headers.get("x-api-version") == "2.3.0"

    @pytest.mark.parametrize(
        ("endpoint", "expected_primary_keys", "expected_sort_mode"),
        [
            ("Customers", ["id"], "asc"),
            ("Events", ["id"], "desc"),
            # Entity ids are only unique within their parent customer.
            ("Entities", ["customer_id", "id"], "asc"),
        ],
    )
    def test_source_response_keys_and_sort_mode(
        self, endpoint: str, expected_primary_keys: list[str], expected_sort_mode: str
    ) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch("products.warehouse_sources.backend.temporal.data_imports.sources.autumn.autumn.rest_api_resource"):
            source_response = autumn_source(
                api_key="am_sk_test",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                api_version="2.3.0",
                resumable_source_manager=manager,
            )

        assert source_response.primary_keys == expected_primary_keys
        assert source_response.sort_mode == expected_sort_mode

    def test_events_partitioning_uses_numerical_buckets_for_epoch_ms(self) -> None:
        # "datetime" partition mode interprets integer values as epoch seconds; Autumn returns
        # epoch milliseconds, which would crash the partitioner.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch("products.warehouse_sources.backend.temporal.data_imports.sources.autumn.autumn.rest_api_resource"):
            source_response = autumn_source(
                api_key="am_sk_test",
                endpoint="Events",
                team_id=123,
                job_id="test_job",
                api_version="2.3.0",
                resumable_source_manager=manager,
            )

        assert source_response.partition_mode == "numerical"
        assert source_response.partition_keys == ["timestamp"]
        assert source_response.partition_size == PARTITION_BUCKET_MILLISECONDS


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.autumn.autumn.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.post.return_value = _make_http_response({}, status_code=status_code)

            valid, error = validate_credentials("am_sk_test", "2.3.0")

        assert valid is expected_valid
        assert (error is None) is expected_valid

        _, kwargs = mock_session.post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer am_sk_test"
        assert kwargs["headers"]["x-api-version"] == "2.3.0"
