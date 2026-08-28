import json
from collections.abc import Iterable
from typing import Any, Optional, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.razorpay import (
    INCREMENTAL_LOOKBACK_SECONDS,
    MIN_FROM_TIMESTAMP,
    RazorpayResumeConfig,
    build_from_param,
    get_resource,
    razorpay_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.settings import (
    ENDPOINT_CONFIGS,
    PAGE_SIZE,
)


def _collection_response(items: list[dict[str, Any]], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps({"entity": "collection", "count": len(items), "items": items}).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _items(count: int, start: int = 0) -> list[dict[str, Any]]:
    return [{"id": f"pay_{start + i}", "created_at": 1_750_000_000 + start + i} for i in range(count)]


def _drive(
    manager: MagicMock,
    responses: list[Response],
    endpoint: str = "Payments",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run ``razorpay_source`` against a mocked HTTP session.

    Returns ``(rows, sent_params)`` where ``sent_params`` are shallow copies of
    ``request.params`` captured at send-time (the Request object is mutated
    in-place by the paginator between pages).
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

        resource = razorpay_source(
            key_id="rzp_test_key",
            key_secret="secret",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
        )
        rows = [row for page in cast(Iterable[Any], resource) for row in (page if isinstance(page, list) else [page])]
        return rows, sent_params


class TestRazorpayPagination:
    def test_full_walk_uses_skip_count_and_saves_resume_state_after_each_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _collection_response(_items(PAGE_SIZE)),
            _collection_response(_items(PAGE_SIZE, start=PAGE_SIZE)),
            _collection_response(_items(3, start=2 * PAGE_SIZE)),
        ]
        rows, sent_params = _drive(manager, responses)

        assert len(rows) == 2 * PAGE_SIZE + 3
        assert [(p.get("skip"), p.get("count")) for p in sent_params] == [
            (0, PAGE_SIZE),
            (PAGE_SIZE, PAGE_SIZE),
            (2 * PAGE_SIZE, PAGE_SIZE),
        ]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            RazorpayResumeConfig(skip=PAGE_SIZE),
            RazorpayResumeConfig(skip=2 * PAGE_SIZE),
        ]

    def test_short_first_page_terminates_without_saving_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        rows, sent_params = _drive(manager, [_collection_response(_items(5))])

        assert len(rows) == 5
        assert len(sent_params) == 1
        manager.save_state.assert_not_called()

    def test_resume_seeds_skip_from_saved_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = RazorpayResumeConfig(skip=200)

        _, sent_params = _drive(manager, [_collection_response(_items(1))])

        assert [p.get("skip") for p in sent_params] == [200]
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        _drive(manager, [_collection_response(_items(1))])

        manager.load_state.assert_not_called()


class TestRazorpayIncremental:
    def test_incremental_sync_sends_lookback_adjusted_from_on_every_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        watermark = 1_750_000_000

        responses = [
            _collection_response(_items(PAGE_SIZE)),
            _collection_response(_items(2, start=PAGE_SIZE)),
        ]
        _, sent_params = _drive(
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        expected_from = watermark - INCREMENTAL_LOOKBACK_SECONDS
        assert [p.get("from") for p in sent_params] == [expected_from, expected_from]

    def test_first_incremental_sync_omits_from(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        _, sent_params = _drive(
            manager,
            [_collection_response(_items(1))],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert "from" not in sent_params[0]

    def test_full_refresh_endpoint_never_sends_from(self) -> None:
        # Disputes doesn't document `from`/`to`; sending unknown params risks a 400 from
        # Razorpay's strict param validation.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        _, sent_params = _drive(
            manager,
            [_collection_response(_items(1))],
            endpoint="Disputes",
            should_use_incremental_field=True,
            db_incremental_field_last_value=1_750_000_000,
        )

        assert "from" not in sent_params[0]

    @pytest.mark.parametrize(
        ("last_value", "expected"),
        [
            (None, None),
            (1_750_000_000, 1_750_000_000 - INCREMENTAL_LOOKBACK_SECONDS),
            ("1750000000", 1_750_000_000 - INCREMENTAL_LOOKBACK_SECONDS),
            (MIN_FROM_TIMESTAMP + 10, MIN_FROM_TIMESTAMP),
            ("not-a-timestamp", None),
        ],
    )
    def test_build_from_param(self, last_value: Any, expected: Optional[int]) -> None:
        assert build_from_param(last_value) == expected


class TestRazorpayResources:
    @pytest.mark.parametrize("endpoint", list(ENDPOINT_CONFIGS.keys()))
    def test_resource_shape_for_each_endpoint(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False, db_incremental_field_last_value=None)

        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        assert resource["name"] == endpoint
        assert endpoint_config["data_selector"] == "items"
        assert endpoint_config["path"] == ENDPOINT_CONFIGS[endpoint].path
        assert resource["write_disposition"] == "replace"

    def test_incremental_resource_uses_merge_disposition(self) -> None:
        resource = get_resource("Payments", should_use_incremental_field=True, db_incremental_field_last_value=None)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}


class TestRazorpayValidateCredentials:
    @pytest.mark.parametrize(("status_code", "expected"), [(200, True), (401, False), (500, False)])
    def test_status_code_mapping(self, status_code: int, expected: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.razorpay.make_tracked_session"
        ) as MockSession:
            response = Response()
            response.status_code = status_code
            MockSession.return_value.get.return_value = response

            assert validate_credentials("rzp_test_key", "secret") is expected
