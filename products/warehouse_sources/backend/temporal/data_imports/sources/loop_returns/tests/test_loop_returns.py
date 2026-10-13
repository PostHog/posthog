import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response
from requests.exceptions import ConnectionError as RequestsConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns import (
    LoopReturnsPaginator,
    LoopReturnsResumeConfig,
    endpoint_permissions,
    loop_returns_source,
    next_cursor,
    resolve_window_start,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.settings import (
    LOOP_RETURNS_ENDPOINTS,
    RETURN_STATES,
)

WINDOW_START = datetime(2024, 1, 1, tzinfo=UTC)
API_KEY = "loop_test_key"
API_VERSION = "v1"


class FakeResumableSourceManager(ResumableSourceManager[LoopReturnsResumeConfig]):
    def __init__(self, state: Optional[LoopReturnsResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[LoopReturnsResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[LoopReturnsResumeConfig]:
        return self.state

    def save_state(self, data: LoopReturnsResumeConfig) -> None:
        self.saved.append(data)


def _http_response(body: Any, status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _paginator(endpoint: str = "returns", *, days: int = 250) -> LoopReturnsPaginator:
    return LoopReturnsPaginator(
        config=LOOP_RETURNS_ENDPOINTS[endpoint],
        window_start=WINDOW_START,
        window_end=WINDOW_START + timedelta(days=days),
        filter_field="created_at",
    )


def _request() -> Request:
    return Request(method="GET", url="https://api.loopreturns.com/api/v1/warehouse/return/list")


def _walk(paginator: LoopReturnsPaginator, responses: list[Any], max_pages: int = 40) -> list[dict[str, Any]]:
    """Drive the paginator through `responses` and return the params of each request it built."""
    request = _request()
    paginator.init_request(request)
    sent = [dict(request.params or {})]

    for body in responses:
        if len(sent) >= max_pages:
            break
        paginator.update_state(_http_response(body))
        paginator.update_request(request)
        if not paginator.has_next_page:
            break
        sent.append(dict(request.params or {}))

    return sent


class TestLoopReturnsPaginator:
    @pytest.mark.parametrize(
        ("label", "second_body"),
        [
            ("next_link_without_a_cursor", {"returns": [], "nextPageUrl": "https://api.loopreturns.com/next"}),
            (
                "repeated_cursor",
                {"returns": [], "nextPageUrl": "https://api.loopreturns.com/api/v1/warehouse/return/list?cursor=abc"},
            ),
        ],
    )
    def test_pagination_that_cannot_advance_moves_on_instead_of_looping(self, label: str, second_body: Any) -> None:
        first_body = {
            "returns": [],
            "nextPageUrl": "https://api.loopreturns.com/api/v1/warehouse/return/list?cursor=abc",
        }
        sent = _walk(_paginator(days=10), [first_body, second_body, {"returns": [], "nextPageUrl": None}])

        # Page three is the next state's pass over the same window, not a third fetch of the cursor.
        assert [params["state"] for params in sent[:3]] == ["open", "open", "closed"]
        assert sent[2].get("cursor") is None

    @pytest.mark.parametrize(
        ("label", "state"),
        [
            ("missing_window_start", {}),
            ("null_window_start", {"window_start": None}),
        ],
    )
    def test_unusable_resume_state_is_ignored(self, label: str, state: dict[str, Any]) -> None:
        paginator = _paginator(days=10)
        paginator.set_resume_state(state)
        request = _request()
        paginator.init_request(request)

        assert request.params is not None
        assert request.params["from"] == "2024-01-01T00:00:00.000Z"

    def test_a_watermark_after_the_window_end_never_inverts_the_range(self) -> None:
        # A watermark at (or past) "now" must not produce `to` before `from`, which Loop rejects.
        paginator = LoopReturnsPaginator(
            config=LOOP_RETURNS_ENDPOINTS["returns"],
            window_start=WINDOW_START,
            window_end=WINDOW_START - timedelta(days=1),
            filter_field="created_at",
        )
        request = _request()
        paginator.init_request(request)

        assert request.params is not None
        assert request.params["to"] == request.params["from"]

    def test_endpoint_without_pagination_or_states_only_windows(self) -> None:
        sent = _walk(_paginator("advanced_shipping_notices", days=200), [[], [], []])

        assert [(params["from"], params["to"]) for params in sent] == [
            ("2024-01-01T00:00:00.000Z", "2024-03-31T00:00:00.000Z"),
            ("2024-03-31T00:00:00.000Z", "2024-06-29T00:00:00.000Z"),
            ("2024-06-29T00:00:00.000Z", "2024-07-19T00:00:00.000Z"),
        ]
        assert all("state" not in params and "cursor" not in params for params in sent)
        # The ASN report doesn't accept the `filter` param, so it must not be sent.
        assert all("filter" not in params for params in sent)


class TestNextCursor:
    @pytest.mark.parametrize(
        ("label", "body", "expected"),
        [
            ("cursor_in_next_link", {"nextPageUrl": "https://api.loopreturns.com/x?cursor=c1&pageSize=250"}, "c1"),
            ("last_page", {"nextPageUrl": None}, None),
            ("no_next_link", {"returns": []}, None),
            ("next_link_without_cursor", {"nextPageUrl": "https://api.loopreturns.com/x?pageSize=250"}, None),
            ("bare_array_body", [{"id": "1"}], None),
        ],
    )
    def test_next_cursor(self, label: str, body: Any, expected: Optional[str]) -> None:
        assert next_cursor(_http_response(body)) == expected

    def test_non_json_body_has_no_cursor(self) -> None:
        response = Response()
        response.status_code = 200
        response._content = b"<html>error</html>"

        assert next_cursor(response) is None


class TestResolveWindowStart:
    def test_a_naive_watermark_is_treated_as_utc(self) -> None:
        assert resolve_window_start(
            now=WINDOW_START,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 3, 4, 5, 6, 7),
        ) == datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)


class TestLoopReturnsSource:
    def _drive(
        self,
        endpoint: str,
        responses: list[Response],
        manager: Optional[FakeResumableSourceManager] = None,
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], list[Any], FakeResumableSourceManager]:
        manager = manager or FakeResumableSourceManager()
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

            source_response = loop_returns_source(
                api_key=API_KEY,
                endpoint=endpoint,
                team_id=1,
                job_id="job-1",
                api_version=API_VERSION,
                resumable_source_manager=manager,
                now=WINDOW_START,
                **kwargs,
            )
            rows = [row for batch in cast(Iterable[Any], source_response.items()) for row in batch]

        return sent_params, rows, manager

    def test_an_incremental_run_starts_at_the_watermark_and_windows_on_the_chosen_field(self) -> None:
        sent_params, _, _ = self._drive(
            "returns",
            [_http_response({"returns": [], "nextPageUrl": None}) for _ in RETURN_STATES],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2023-12-25T00:00:00Z",
            incremental_field="updated_at",
        )

        assert sent_params[0]["from"] == "2023-12-25T00:00:00.000Z"
        assert sent_params[0]["filter"] == "updated_at"

    def test_a_resumed_run_picks_up_at_the_saved_state_pass(self) -> None:
        manager = FakeResumableSourceManager(
            LoopReturnsResumeConfig(window_start="2023-12-31T12:00:00.000Z", state_index=3, cursor="c9")
        )
        sent_params, _, _ = self._drive(
            "returns",
            [_http_response({"returns": [], "nextPageUrl": None}) for _ in range(2)],
            manager=manager,
            start_date="2023-12-31T00:00:00Z",
        )

        assert sent_params[0]["state"] == RETURN_STATES[3]
        assert sent_params[0]["cursor"] == "c9"
        assert sent_params[0]["from"] == "2023-12-31T12:00:00.000Z"
        # The next pass restarts at the configured start date, not the resumed window.
        assert sent_params[1]["from"] == "2023-12-31T00:00:00.000Z"

    def test_destinations_are_not_resumed_or_windowed(self) -> None:
        manager = FakeResumableSourceManager(
            LoopReturnsResumeConfig(window_start="2023-12-31T00:00:00.000Z", state_index=2, cursor="c9")
        )
        sent_params, _, _ = self._drive("destinations", [_http_response({"destinations": []})], manager=manager)

        assert sent_params == [{}]
        assert manager.saved == []


class TestCredentialValidation:
    def _session(self, responses: list[Response]) -> MagicMock:
        session = MagicMock()
        session.get.side_effect = responses
        return session

    @pytest.mark.parametrize(
        ("label", "status_codes", "expected_valid"),
        [
            ("returns_readable", [200], True),
            # A key scoped only for destinations still works, just for fewer tables.
            ("returns_denied_destinations_readable", [401, 200], True),
            ("everything_denied", [401, 401], False),
            ("forbidden", [403, 403], False),
            ("server_error", [500, 500], False),
        ],
    )
    def test_validate_credentials(self, label: str, status_codes: list[int], expected_valid: bool) -> None:
        responses = [_http_response({}, status_code=code) for code in status_codes]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns.make_tracked_session",
            return_value=self._session(responses),
        ):
            is_valid, error = validate_credentials(API_KEY, API_VERSION)

        assert is_valid is expected_valid
        assert (error is None) is expected_valid

    def test_a_denied_key_names_the_scope_to_add(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns.make_tracked_session",
            return_value=self._session([_http_response({}, status_code=401) for _ in range(2)]),
        ):
            _, error = validate_credentials(API_KEY, API_VERSION)

        assert error is not None
        assert "Returns" in error

    def test_validating_one_schema_probes_only_that_endpoint(self) -> None:
        session = self._session([_http_response({"destinations": []})])
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns.make_tracked_session",
            return_value=session,
        ):
            is_valid, error = validate_credentials(API_KEY, API_VERSION, schema_name="destinations")

        assert (is_valid, error) == (True, None)
        assert session.get.call_args.args[0] == "https://api.loopreturns.com/api/v1/destinations"

    def test_a_network_failure_is_reported_not_raised(self) -> None:
        session = MagicMock()
        session.get.side_effect = RequestsConnectionError("no route to host")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns.make_tracked_session",
            return_value=session,
        ):
            is_valid, error = validate_credentials(API_KEY, API_VERSION)

        assert is_valid is False
        assert error is not None and "no route to host" in error

    def test_endpoint_permissions_reports_each_table_separately(self) -> None:
        responses = [_http_response({}, status_code=200), _http_response({}, status_code=401)]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns.make_tracked_session",
            return_value=self._session(responses),
        ):
            permissions = endpoint_permissions(API_KEY, API_VERSION, ["returns", "destinations"])

        assert permissions["returns"] is None
        assert permissions["destinations"] is not None
        assert "Destinations (Read)" in cast(str, permissions["destinations"])
