import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.housecall_pro import (
    HousecallProResumeConfig,
    _format_created_at_min,
    get_rows,
    housecall_pro_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.settings import (
    ENDPOINTS,
    HOUSECALL_PRO_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the housecall_pro module.
HOUSECALL_PRO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.housecall_pro.make_tracked_session"
)


def _response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _page(response_key: str, items: list[dict[str, Any]], total_pages: int) -> Response:
    return _response({response_key: items, "page": 1, "page_size": 100, "total_pages": total_pages})


def _make_manager(resume_state: HousecallProResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return snapshots of each request AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _collect(
    endpoint: str,
    responses: list[Response],
    MockSession: mock.MagicMock,
    manager: mock.MagicMock | None = None,
    **kwargs: Any,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]], mock.MagicMock]:
    session = MockSession.return_value
    snapshots = _wire(session, responses)
    manager = manager if manager is not None else _make_manager()
    batches = list(get_rows("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs))
    return batches, snapshots, manager


class TestFormatCreatedAtMin:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2026, 3, 4, 22, 13, 20, tzinfo=UTC), "2026-03-04T22:13:20Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("2026-03-04T22:13:20Z", "2026-03-04T22:13:20Z"),
            ("", None),
        ],
    )
    def test_format_created_at_min(self, value: Any, expected: str | None) -> None:
        assert _format_created_at_min(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(HOUSECALL_PRO_SESSION_PATCH)
    def test_validate_credentials_status_mapping(
        self, mock_session: mock.MagicMock, status_code: int, expected: bool
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key") is expected


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_by_page_number(self, MockSession: mock.MagicMock) -> None:
        batches, snapshots, manager = _collect(
            "customers",
            [
                _page("customers", [{"id": "1"}, {"id": "2"}], total_pages=2),
                _page("customers", [{"id": "3"}], total_pages=2),
            ],
            MockSession,
        )

        assert [item["id"] for batch in batches for item in batch] == ["1", "2", "3"]
        assert snapshots[0]["params"]["page"] == 1
        assert snapshots[0]["params"]["page_size"] == 100
        assert snapshots[1]["params"]["page"] == 2
        # State saved once (after page 1, pointing at page 2); page 2 is the last so no save after it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == HousecallProResumeConfig(page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_created_at_min_omitted_when_last_value_missing(self, MockSession: mock.MagicMock) -> None:
        _, snapshots, _ = _collect(
            "invoices",
            [_page("invoices", [{"id": "1"}], total_pages=1)],
            MockSession,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert "created_at_min" not in snapshots[0]["params"]


class TestHousecallProSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = HOUSECALL_PRO_ENDPOINTS[endpoint]
        response = housecall_pro_source(
            "key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(HOUSECALL_PRO_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config: Any) -> None:
        # Never partition on a mutable field; only stable creation timestamps are allowed.
        if config.partition_key:
            assert config.partition_key == "created_at"

    @pytest.mark.parametrize("config", list(HOUSECALL_PRO_ENDPOINTS.values()))
    def test_incremental_endpoints_have_a_sort_field(self, config: Any) -> None:
        # An incremental endpoint must sort ascending on its cursor so the watermark advances.
        if config.supports_incremental:
            assert config.sort_field is not None
            assert config.incremental_param is not None
            assert config.incremental_fields
