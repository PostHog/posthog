from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.bill_com import (
    PAGE_SIZE,
    BillComAuthError,
    BillComClient,
    BillComResumeConfig,
    base_url,
    bill_com_source,
    build_params,
    error_message,
    format_incremental_value,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.settings import BILL_COM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.bill_com"


class _FakeManager(ResumableSourceManager[BillComResumeConfig]):
    def __init__(self, state: Optional[BillComResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[BillComResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[BillComResumeConfig]:
        return self.state

    def save_state(self, data: BillComResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def _response(status: int = 200, body: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status
    response.text = text
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = body
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=response)
    return response


def _client(session: mock.MagicMock, environment: str = "production") -> BillComClient:
    with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
        return BillComClient(
            username="finance@acme.com",
            password="pw",
            organization_id="org-1",
            dev_key="dev-key",
            environment=environment,
            api_version="v3",
        )


class TestBillCom:
    @pytest.mark.parametrize(
        "environment, expected",
        [
            ("production", "https://gateway.prod.bill.com/connect"),
            ("sandbox", "https://gateway.stage.bill.com/connect"),
        ],
    )
    def test_base_url_per_environment(self, environment: str, expected: str) -> None:
        assert base_url(environment) == expected

    def test_base_url_rejects_unknown_environment(self) -> None:
        with pytest.raises(ValueError):
            base_url("evil")

    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 1, 12, 30, 15, 250000, tzinfo=UTC), "2026-03-01T12:30:15.250Z"),
            (datetime(2026, 3, 1, 12, 30, 15), "2026-03-01T12:30:15.000Z"),
            (date(2026, 3, 1), "2026-03-01T00:00:00.000Z"),
            ("2026-03-01T00:00:00.000Z", "2026-03-01T00:00:00.000Z"),
        ],
    )
    def test_format_incremental_value(self, value: Any, expected: str) -> None:
        assert format_incremental_value(value) == expected

    @pytest.mark.parametrize(
        "body, text, expected",
        [
            ([{"message": "Invalid credentials", "code": "BDC_1105"}], "", "Invalid credentials"),
            ({"message": "Unauthorized"}, "", "Unauthorized"),
            (ValueError("not json"), "<html>502</html>", "<html>502</html>"),
        ],
    )
    def test_error_message_reads_both_error_envelopes(self, body: Any, text: str, expected: str) -> None:
        assert error_message(_response(body=body, text=text)) == expected

    @pytest.mark.parametrize(
        "should_use_incremental_field, last_value, incremental_field, expected_sort, expected_filters",
        [
            (False, None, None, "createdTime:asc", None),
            # A last value only filters when the sync is actually incremental.
            (False, datetime(2026, 3, 1, tzinfo=UTC), "updatedTime", "createdTime:asc", None),
            (True, None, "updatedTime", "updatedTime:asc", None),
            (
                True,
                datetime(2026, 3, 1, tzinfo=UTC),
                "updatedTime",
                "updatedTime:asc",
                "updatedTime:gte:2026-03-01T00:00:00.000Z",
            ),
            (
                True,
                datetime(2026, 3, 1, tzinfo=UTC),
                "createdTime",
                "createdTime:asc",
                "createdTime:gte:2026-03-01T00:00:00.000Z",
            ),
            # An unsupported cursor field falls back to the one BILL can filter on.
            (
                True,
                datetime(2026, 3, 1, tzinfo=UTC),
                "id",
                "updatedTime:asc",
                "updatedTime:gte:2026-03-01T00:00:00.000Z",
            ),
        ],
    )
    def test_build_params(
        self,
        should_use_incremental_field: bool,
        last_value: Any,
        incremental_field: Optional[str],
        expected_sort: str,
        expected_filters: Optional[str],
    ) -> None:
        params = build_params(should_use_incremental_field, last_value, incremental_field)

        assert params["max"] == PAGE_SIZE
        assert params["sort"] == expected_sort
        assert params.get("filters") == expected_filters

    def test_login_posts_credentials_and_stores_session_id(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(body={"sessionId": "sess-1", "organizationId": "org-1"})
        client = _client(session)

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            assert client.login() == "sess-1"

        assert client.session_id == "sess-1"
        assert session.post.call_args.args[0] == "https://gateway.prod.bill.com/connect/v3/login"
        assert session.post.call_args.kwargs["json"] == {
            "username": "finance@acme.com",
            "password": "pw",
            "organizationId": "org-1",
            "devKey": "dev-key",
        }

    @pytest.mark.parametrize("status", [400, 401, 403])
    def test_login_rejects_bad_credentials_without_retrying(self, status: int) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(status=status, body=[{"message": "Invalid credentials"}])
        client = _client(session)

        with pytest.raises(BillComAuthError, match="Invalid credentials"):
            client.login()

    def test_login_without_session_id_raises(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(body={"organizationId": "org-1"})
        client = _client(session)

        with pytest.raises(BillComAuthError, match="did not return a session ID"):
            client.login()

    def test_no_bill_traffic_is_ever_sample_captured(self) -> None:
        # Track every tracked session built during a sign-in + data request, tagging each with the
        # kwargs it was created with, so we can prove no BILL traffic ever feeds HTTP sample capture.
        created: list[tuple[dict[str, Any], mock.MagicMock]] = []

        def _make(**kwargs: Any) -> mock.MagicMock:
            session = mock.MagicMock()
            session.post.return_value = _response(body={"sessionId": "sess-secret"})
            session.get.return_value = _response(body={"results": [{"id": "00n1"}]})
            created.append((kwargs, session))
            return session

        with mock.patch(f"{_MODULE}.make_tracked_session", side_effect=_make):
            client = BillComClient(
                username="finance@acme.com",
                password="pw",
                organization_id="org-1",
                dev_key="dev-key",
                environment="production",
                api_version="v3",
            )
            client.login()
            client.list_page("/invoices", {})

        # BILL responses carry the freshly minted session ID and raw financial records that no
        # name-based scrubber would recognise, so every session used for BILL traffic must be
        # excluded from capture.
        assert created, "no tracked session was built"
        assert all(kwargs.get("capture", True) is False for kwargs, _ in created)

    def test_list_page_signs_in_lazily_and_sends_session_headers(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(body={"sessionId": "sess-1"})
        session.get.return_value = _response(body={"results": [{"id": "00n1"}]})
        client = _client(session)

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            body = client.list_page("/bills", {"max": PAGE_SIZE})

        assert body == {"results": [{"id": "00n1"}]}
        assert session.post.call_count == 1
        assert session.get.call_args.args[0] == "https://gateway.prod.bill.com/connect/v3/bills"
        assert session.get.call_args.kwargs["headers"] == {"sessionId": "sess-1", "devKey": "dev-key"}

    def test_list_page_signs_in_again_when_the_session_expires(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(body={"sessionId": "sess-2"})
        session.get.side_effect = [_response(status=401, body={"message": "Unauthorized"}), _response(body={})]
        client = _client(session)

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            client.list_page("/bills", {})

        # One sign-in to start the session, one to replace the expired one.
        assert session.post.call_count == 2
        assert session.get.call_count == 2

    def test_list_page_raises_on_other_errors(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(body={"sessionId": "sess-1"})
        session.get.return_value = _response(status=403, body=[{"message": "Forbidden"}])
        client = _client(session)

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            with pytest.raises(requests.HTTPError):
                client.list_page("/bills", {})

        assert session.post.call_count == 1

    def test_get_rows_paginates_and_checkpoints_after_each_page(self) -> None:
        client = mock.MagicMock(spec=BillComClient)
        client.list_page.side_effect = [
            {"results": [{"id": "00n1"}], "nextPage": "cursor-2"},
            {"results": [{"id": "00n2"}], "nextPage": "cursor-3"},
            {"results": [{"id": "00n3"}]},
        ]
        manager = _FakeManager()

        pages = list(get_rows(client, "bills", {"max": PAGE_SIZE}, manager, mock.MagicMock()))

        assert pages == [[{"id": "00n1"}], [{"id": "00n2"}], [{"id": "00n3"}]]
        assert [call.args[1].get("page") for call in client.list_page.call_args_list] == [None, "cursor-2", "cursor-3"]
        assert [state.next_page for state in manager.saved] == ["cursor-2", "cursor-3"]
        assert manager.cleared is True

    def test_get_rows_resumes_from_saved_cursor(self) -> None:
        client = mock.MagicMock(spec=BillComClient)
        client.list_page.return_value = {"results": [{"id": "00n9"}]}
        manager = _FakeManager(BillComResumeConfig(next_page="cursor-7"))

        pages = list(get_rows(client, "bills", {"max": PAGE_SIZE}, manager, mock.MagicMock()))

        assert pages == [[{"id": "00n9"}]]
        assert client.list_page.call_args.args[1]["page"] == "cursor-7"

    def test_get_rows_stops_on_a_repeated_cursor(self) -> None:
        client = mock.MagicMock(spec=BillComClient)
        client.list_page.side_effect = [
            {"results": [{"id": "00n1"}], "nextPage": "cursor-2"},
            {"results": [{"id": "00n2"}], "nextPage": "cursor-2"},
        ]
        manager = _FakeManager()

        pages = list(get_rows(client, "bills", {}, manager, mock.MagicMock()))

        assert pages == [[{"id": "00n1"}], [{"id": "00n2"}]]
        assert client.list_page.call_count == 2

    def test_get_rows_yields_nothing_for_an_empty_endpoint(self) -> None:
        client = mock.MagicMock(spec=BillComClient)
        client.list_page.return_value = {"results": [], "nextPage": None}
        manager = _FakeManager()

        assert list(get_rows(client, "vendors", {}, manager, mock.MagicMock())) == []
        assert manager.saved == []
        assert manager.cleared is True

    @pytest.mark.parametrize("endpoint", sorted(BILL_COM_ENDPOINTS))
    def test_get_rows_requests_each_endpoints_documented_path(self, endpoint: str) -> None:
        client = mock.MagicMock(spec=BillComClient)
        client.list_page.return_value = {"results": []}

        list(get_rows(client, endpoint, {}, _FakeManager(), mock.MagicMock()))

        assert client.list_page.call_args.args[0] == BILL_COM_ENDPOINTS[endpoint].path

    @pytest.mark.parametrize(
        "login_response, expected",
        [
            (_response(body={"sessionId": "sess-1"}), (True, None)),
            (
                _response(status=401, body=[{"message": "Invalid credentials"}]),
                (False, "BILL sign-in failed: Invalid credentials"),
            ),
        ],
    )
    def test_validate_credentials(self, login_response: mock.MagicMock, expected: tuple[bool, Optional[str]]) -> None:
        session = mock.MagicMock()
        session.post.return_value = login_response

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("finance@acme.com", "pw", "org-1", "dev-key", "production", "v3") == expected

    def test_validate_credentials_rejects_an_unknown_environment_without_a_request(self) -> None:
        session = mock.MagicMock()

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("finance@acme.com", "pw", "org-1", "dev-key", "evil", "v3")

        assert is_valid is False
        assert message is not None and "Invalid BILL environment" in message
        session.post.assert_not_called()

    def test_validate_credentials_maps_transport_failures_to_a_friendly_message(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = requests.ConnectionError("boom")

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("finance@acme.com", "pw", "org-1", "dev-key", "production", "v3")

        assert is_valid is False
        assert message == "Could not reach BILL. Please check your credentials and try again."

    def test_bill_com_source_response_shape(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(body={"sessionId": "sess-1"})
        session.get.return_value = _response(body={"results": [{"id": "00n1", "createdTime": "2026-03-01T00:00:00Z"}]})
        manager = _FakeManager()

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            response = bill_com_source(
                username="finance@acme.com",
                password="pw",
                organization_id="org-1",
                dev_key="dev-key",
                environment="production",
                api_version="v3",
                endpoint="bills",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
                incremental_field="updatedTime",
            )

            assert response.name == "bills"
            assert response.primary_keys == ["id"]
            assert response.sort_mode == "asc"
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["createdTime"]

            pages = list(cast("Iterable[Any]", response.items()))

        assert pages == [[{"id": "00n1", "createdTime": "2026-03-01T00:00:00Z"}]]
        assert session.get.call_args.kwargs["params"]["filters"] == "updatedTime:gte:2026-03-01T00:00:00.000Z"
