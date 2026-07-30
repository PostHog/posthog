import json
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.lambda_labs import (
    LambdaLabsResumeConfig,
    _extract_records,
    _format_iso8601,
    get_rows,
    lambda_labs_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.settings import LAMBDA_LABS_ENDPOINTS

_TRANSPORT = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.lambda_labs.make_tracked_session"
)


class _FakeResponse:
    def __init__(self, body: dict[str, Any], status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.text = json.dumps(body)

    def json(self) -> dict[str, Any]:
        return self._body

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=cast("requests.Response", self))


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, headers: Any = None, params: Any = None, timeout: Any = None) -> _FakeResponse:
        self.calls.append({"url": url, "params": dict(params or {})})
        return next(self._responses)


def _drive(
    endpoint: str, manager: Any, responses: list[_FakeResponse], **kwargs: Any
) -> tuple[_FakeSession, list[Any]]:
    session = _FakeSession(responses)
    with patch(_TRANSPORT, return_value=session):
        rows = list(
            get_rows(
                api_key="secret_key",
                endpoint=endpoint,
                logger=structlog.get_logger(),
                resumable_source_manager=manager,
                **kwargs,
            )
        )
    return session, rows


class TestExtractRecords:
    @pytest.mark.parametrize(
        ("endpoint", "body", "expected"),
        [
            (
                "instances",
                {"data": [{"id": "i-1"}, {"id": "i-2"}]},
                [{"id": "i-1"}, {"id": "i-2"}],
            ),
            (
                # A live JupyterLab access token (and the URL embedding it) must be stripped so it
                # never lands in the warehouse where a project member could retrieve it.
                "instances",
                {
                    "data": [
                        {
                            "id": "i-1",
                            "jupyter_token": "secret-token",
                            "jupyter_url": "https://jupyter.lambda.ai/?token=secret-token",
                            "name": "gpu-box",
                        }
                    ]
                },
                [{"id": "i-1", "name": "gpu-box"}],
            ),
            (
                # The map endpoint hoists `instance_type` fields to the top level (including `name`,
                # the primary key) and keeps regional availability alongside them.
                "instance_types",
                {
                    "data": {
                        "gpu_1x_a100": {
                            "instance_type": {"name": "gpu_1x_a100", "price_cents_per_hour": 110},
                            "regions_with_capacity_available": [{"name": "us-west-1"}],
                        }
                    }
                },
                [
                    {
                        "name": "gpu_1x_a100",
                        "price_cents_per_hour": 110,
                        "regions_with_capacity_available": [{"name": "us-west-1"}],
                    }
                ],
            ),
            (
                # tickets nests its list one level deeper under `data.tickets`.
                "tickets",
                {"data": {"tickets": [{"id": "t1"}], "page_token": None}},
                [{"id": "t1"}],
            ),
            (
                "audit_events",
                {"data": [{"event_id": "e1"}], "page_token": "next"},
                [{"event_id": "e1"}],
            ),
        ],
    )
    def test_extract_records(self, endpoint: str, body: dict[str, Any], expected: list[dict[str, Any]]) -> None:
        assert _extract_records(body, LAMBDA_LABS_ENDPOINTS[endpoint]) == expected


class TestFormatIso8601:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2025, 9, 15, 10, 30, 45, 123456, tzinfo=UTC), "2025-09-15T10:30:45.123Z"),
            # A naive datetime is treated as UTC rather than shifted by the machine's local zone.
            (datetime(2025, 1, 1, 0, 0, 0), "2025-01-01T00:00:00.000Z"),
            (date(2025, 3, 4), "2025-03-04T00:00:00.000Z"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_iso8601(value) == expected


class TestPaginationAndResume:
    def test_unpaginated_endpoint_yields_once_and_never_saves_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        session, rows = _drive("instances", manager, [_FakeResponse({"data": [{"id": "i-1"}]})])

        assert rows == [[{"id": "i-1"}]]
        assert len(session.calls) == 1
        manager.save_state.assert_not_called()

    def test_paginates_and_saves_state_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _FakeResponse({"data": [{"event_id": "e1"}], "page_token": "tok-1"}),
            _FakeResponse({"data": [{"event_id": "e2"}], "page_token": "tok-2"}),
            _FakeResponse({"data": [{"event_id": "e3"}], "page_token": None}),
        ]
        session, rows = _drive("audit_events", manager, responses)

        assert rows == [[{"event_id": "e1"}], [{"event_id": "e2"}], [{"event_id": "e3"}]]
        # First page carries no cursor; subsequent pages carry the prior page's token only.
        assert [c["params"].get("page_token") for c in session.calls] == [None, "tok-1", "tok-2"]
        # State is saved only for non-terminal pages, so a crash re-yields the last page.
        assert [c.args[0] for c in manager.save_state.call_args_list] == [
            LambdaLabsResumeConfig(page_token="tok-1"),
            LambdaLabsResumeConfig(page_token="tok-2"),
        ]

    def test_resume_seeds_first_request_with_saved_token_only(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = LambdaLabsResumeConfig(page_token="tok-resumed")

        session, _ = _drive(
            "audit_events",
            manager,
            [_FakeResponse({"data": [{"event_id": "e9"}], "page_token": None})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 1, 1, tzinfo=UTC),
        )

        # On resume the cursor already encodes the window, so only the token is sent — never `start`.
        assert session.calls[0]["params"] == {"page_token": "tok-resumed"}

    def test_incremental_first_sync_sends_start_filter(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        session, _ = _drive(
            "audit_events",
            manager,
            [_FakeResponse({"data": [{"event_id": "e1"}], "page_token": None})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        )

        assert session.calls[0]["params"] == {"start": "2025-06-01T12:00:00.000Z"}

    def test_non_incremental_endpoint_ignores_incremental_value(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        # `instances` has no server-side time filter, so a stray last-value must not become a `start`.
        session, _ = _drive(
            "instances",
            manager,
            [_FakeResponse({"data": [{"id": "i-1"}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 6, 1, tzinfo=UTC),
        )

        assert session.calls[0]["params"] == {}


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(LAMBDA_LABS_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        config = LAMBDA_LABS_ENDPOINTS[endpoint]
        response = lambda_labs_source(
            api_key="secret_key",
            endpoint=endpoint,
            logger=structlog.get_logger(),
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Ascending is required for the audit-events incremental watermark to advance correctly.
        assert response.sort_mode == "asc"

        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
