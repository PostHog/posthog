import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.lambda_labs import (
    LambdaLabsResumeConfig,
    _format_iso8601,
    lambda_labs_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.settings import LAMBDA_LABS_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the lambda_labs module.
LAMBDA_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.lambda_labs.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: LambdaLabsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return lambda_labs_source(
        api_key="secret_key",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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
                {"data": [{"event_id": "e1"}], "page_token": None},
                [{"event_id": "e1"}],
            ),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_extract_records(
        self, MockSession: mock.MagicMock, endpoint: str, body: dict[str, Any], expected: list[dict[str, Any]]
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response(body)])
        rows = _rows(_source(endpoint, _make_manager()))
        assert rows == expected

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows(self, MockSession: mock.MagicMock) -> None:
        # A 200 without the `data` key is treated as an empty collection, not a hard failure.
        session = MockSession.return_value
        _wire(session, [_response({})])
        assert _rows(_source("instances", _make_manager())) == []


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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoint_yields_once_and_never_saves_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": [{"id": "i-1"}]})])

        manager = _make_manager()
        rows = _rows(_source("instances", manager))

        assert rows == [{"id": "i-1"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_saves_state_after_each_non_terminal_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"data": [{"event_id": "e1"}], "page_token": "tok-1"}),
                _response({"data": [{"event_id": "e2"}], "page_token": "tok-2"}),
                _response({"data": [{"event_id": "e3"}], "page_token": None}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("audit_events", manager))

        assert rows == [{"event_id": "e1"}, {"event_id": "e2"}, {"event_id": "e3"}]
        # First page carries no cursor; subsequent pages carry the prior page's token only.
        assert [p.get("page_token") for p in params] == [None, "tok-1", "tok-2"]
        # State is saved only for non-terminal pages, so a crash re-yields the last page.
        assert [c.args[0] for c in manager.save_state.call_args_list] == [
            LambdaLabsResumeConfig(page_token="tok-1"),
            LambdaLabsResumeConfig(page_token="tok-2"),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_first_request_with_saved_token_only(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"data": [{"event_id": "e9"}], "page_token": None})])

        manager = _make_manager(LambdaLabsResumeConfig(page_token="tok-resumed"))
        _rows(
            _source(
                "audit_events",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2025, 1, 1, tzinfo=UTC),
            )
        )

        # On resume the cursor already encodes the window, so only the token is sent — never `start`.
        assert params[0] == {"page_token": "tok-resumed"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_first_sync_sends_start_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"data": [{"event_id": "e1"}], "page_token": None})])

        manager = _make_manager()
        _rows(
            _source(
                "audit_events",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
            )
        )

        assert params[0] == {"start": "2025-06-01T12:00:00.000Z"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_incremental_endpoint_ignores_incremental_value(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"data": [{"id": "i-1"}]})])

        # `instances` has no server-side time filter, so a stray last-value must not become a `start`.
        manager = _make_manager()
        _rows(
            _source(
                "instances",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2025, 6, 1, tzinfo=UTC),
            )
        )

        assert params[0] == {}


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(LAMBDA_LABS_ENDPOINTS.keys()))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, MockSession: mock.MagicMock, endpoint: str) -> None:
        config = LAMBDA_LABS_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

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


class TestValidateCredentials:
    @pytest.mark.parametrize(("status", "expected"), [(200, True), (401, False), (403, False)])
    @mock.patch(LAMBDA_SESSION_PATCH)
    def test_status_maps_to_bool(self, mock_session: mock.MagicMock, status: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("secret_key") is expected

    @mock.patch(LAMBDA_SESSION_PATCH)
    def test_transient_error_propagates(self, mock_session: mock.MagicMock) -> None:
        # A 5xx is not a credential rejection — it must propagate so the caller reports a transient
        # failure rather than telling the user to rotate a valid key.
        resp = mock.MagicMock(status_code=503)
        resp.raise_for_status.side_effect = requests.HTTPError("503 Server Error", response=mock.MagicMock())
        mock_session.return_value.get.return_value = resp
        with pytest.raises(requests.HTTPError):
            validate_credentials("secret_key")
