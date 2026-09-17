import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset import apify_dataset
from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.apify_dataset import (
    ApifyResumeConfig,
    apify_dataset_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.settings import (
    ACTOR_RUNS_ENDPOINT,
    ACTORS_ENDPOINT,
    DATASETS_ENDPOINT,
    USAGE_MONTHLY_ENDPOINT,
)

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
APIFY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.apify_dataset.make_tracked_session"
)


def _response(body: Any, *, total: int | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    if total is not None:
        resp.headers["X-Apify-Pagination-Total"] = str(total)
    return resp


def _make_manager(resume_state: ApifyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    session.headers = {}
    params: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        params.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return params


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(manager, responses):
    return apify_dataset_source(
        api_token="tok",
        dataset_id="ds1",
        endpoint="dataset_items",
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


def _platform_response(items: Any, total: int | None = None) -> Response:
    """Shape of every Apify platform list endpoint: rows wrapped in a data envelope."""
    return _response({"data": {"items": items, "total": total if total is not None else len(items)}})


def _run_platform(
    endpoint: str,
    manager,
    *,
    db_incremental_field_last_value: Any = None,
    should_use_incremental_field: bool = False,
):
    return apify_dataset_source(
        api_token="tok",
        dataset_id="ds1",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        db_incremental_field_last_value=db_incremental_field_last_value,
        should_use_incremental_field=should_use_incremental_field,
    )


class TestPagination:
    @mock.patch.object(apify_dataset, "PAGE_SIZE", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_progresses_offset_and_terminates_on_header_total(self, MockSession) -> None:
        session = MockSession.return_value
        # total=3: page 1 (2 rows, full) -> continue; page 2 (offset 2, 1 row) -> offset 4 >= 3 -> stop.
        params = _wire(session, [_response([{"i": 0}, {"i": 1}], total=3), _response([{"i": 2}], total=3)])

        manager = _make_manager()
        rows = _rows(_run(manager, None))

        assert [r["i"] for r in rows] == [0, 1, 2]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 2
        assert params[0]["format"] == "json"
        assert params[1]["offset"] == 2
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ApifyResumeConfig(offset=2)

    @mock.patch.object(apify_dataset, "PAGE_SIZE", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_terminates(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"i": 0}], total=1)])

        manager = _make_manager()
        rows = _rows(_run(manager, None))

        assert [r["i"] for r in rows] == [0]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch.object(apify_dataset, "PAGE_SIZE", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"i": 200}], total=201)])

        manager = _make_manager(ApifyResumeConfig(offset=200))
        _rows(_run(manager, None))

        assert params[0]["offset"] == 200

    @mock.patch.object(apify_dataset, "PAGE_SIZE", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "wrong shape"}, total=0)])

        # A misrouted request returning an error object (not a list) must fail loud, not sync it as a row.
        with pytest.raises(ValueError, match="list response body"):
            _rows(_run(_make_manager(), None))


class TestValidateCredentials:
    @mock.patch(APIFY_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("tok", "ds1") == (True, None)

    @mock.patch(APIFY_SESSION_PATCH)
    def test_unauthorized_message(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        ok, msg = validate_credentials("tok", "ds1")
        assert ok is False
        assert "token" in (msg or "")

    @mock.patch(APIFY_SESSION_PATCH)
    def test_not_found_message(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=404)
        ok, msg = validate_credentials("tok", "ds1")
        assert ok is False
        assert "Dataset not found" in (msg or "")

    @mock.patch(APIFY_SESSION_PATCH)
    def test_network_error_message(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, msg = validate_credentials("tok", "ds1")
        assert ok is False
        assert "reach the Apify API" in (msg or "")


class TestPlatformEndpoints:
    @mock.patch.object(apify_dataset, "PAGE_SIZE", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pages_on_envelope_total_and_checkpoints_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _platform_response([{"id": "a"}, {"id": "b"}], total=3),
                _platform_response([{"id": "c"}], total=3),
            ],
        )

        manager = _make_manager()
        rows = _rows(_run_platform(ACTOR_RUNS_ENDPOINT, manager))

        assert [r["id"] for r in rows] == ["a", "b", "c"]
        assert [p["offset"] for p in params] == [0, 2]
        assert manager.save_state.call_args.args[0] == ApifyResumeConfig(offset=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sends_started_after_from_watermark(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_platform_response([])])

        _rows(
            _run_platform(
                ACTOR_RUNS_ENDPOINT,
                _make_manager(),
                db_incremental_field_last_value=datetime(2026, 3, 4, 5, 6, 7, 890000, tzinfo=UTC),
                should_use_incremental_field=True,
            )
        )

        # Truncated to whole seconds, which only ever re-fetches the boundary row.
        assert params[0]["startedAfter"] == "2026-03-04T05:06:07Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_omits_the_watermark(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_platform_response([])])

        _rows(
            _run_platform(
                ACTOR_RUNS_ENDPOINT,
                _make_manager(),
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )

        assert "startedAfter" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_datasets_asks_for_unnamed_storages(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_platform_response([])])

        _rows(_run_platform(DATASETS_ENDPOINT, _make_manager()))

        # Actor runs store their output in unnamed datasets, which the endpoint hides by default.
        assert params[0]["unnamed"] == "true"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_envelope_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": {"type": "insufficient-permissions"}})])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_run_platform(ACTORS_ENDPOINT, _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_monthly_usage_becomes_one_row_per_day(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    {
                        "data": {
                            "usageCycle": {"startAt": "2026-03-01T00:00:00.000Z", "endAt": "2026-03-31T23:59:59.999Z"},
                            "monthlyServiceUsage": {"ACTOR_COMPUTE_UNITS": {"quantity": 3}},
                            "dailyServiceUsages": [
                                {"date": "2026-03-01", "serviceUsage": {}, "totalUsageCreditsUsd": 0.5},
                                {"date": "2026-03-02", "serviceUsage": {}, "totalUsageCreditsUsd": 1.5},
                            ],
                            "totalUsageCreditsUsdBeforeVolumeDiscount": 2.5,
                            "totalUsageCreditsUsdAfterVolumeDiscount": 2.0,
                        }
                    }
                )
            ],
        )

        manager = _make_manager()
        rows = _rows(_run_platform(USAGE_MONTHLY_ENDPOINT, manager))

        assert [r["date"] for r in rows] == ["2026-03-01", "2026-03-02"]
        assert [r["totalUsageCreditsUsd"] for r in rows] == [0.5, 1.5]
        assert rows[0]["usageCycleStartAt"] == "2026-03-01T00:00:00.000Z"
        assert rows[0]["usageCycleEndAt"] == "2026-03-31T23:59:59.999Z"
        assert rows[0]["totalUsageCreditsUsdAfterVolumeDiscount"] == 2.0
        # A single object endpoint has no cursor, so nothing is checkpointed.
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown Apify endpoint"):
            _run_platform("not_a_table", _make_manager())
