import json
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.iterable import (
    IterableResumeConfig,
    _parse_iterable_datetime,
    _resolve_next_url,
    base_url_for_region,
    iterable_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.settings import ITERABLE_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.iterable.iterable"
# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _text_response(text: str) -> Response:
    resp = Response()
    resp.status_code = 200
    resp.encoding = "utf-8"
    resp._content = text.encode()
    resp._content_consumed = True  # type: ignore[attr-defined]
    return resp


def _ndjson(rows: list[dict[str, Any]]) -> Response:
    return _text_response("\n".join(json.dumps(row) for row in rows))


def _make_manager(resume_state: IterableResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[str], list[Any]]:
    """Wire a mock session; capture each request's URL and auth AT PREPARE TIME.

    The paginator retargets a single ``Request`` object in place across pages, so inspecting it after
    the run shows only the final URL — snapshot each request as it is prepared instead.
    """
    session.headers = {}
    url_snapshots: list[str] = []
    auth_snapshots: list[Any] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        auth_snapshots.append(request.auth)
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots, auth_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(session: mock.MagicMock, api_key: str, region: str, endpoint: str, manager: mock.MagicMock) -> list[dict]:
    return _rows(iterable_source(api_key, region, endpoint, team_id=1, job_id="j", resumable_source_manager=manager))


class TestBaseUrlForRegion:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://api.iterable.com"),
            ("US", "https://api.iterable.com"),
            ("eu", "https://api.eu.iterable.com"),
            ("EU", "https://api.eu.iterable.com"),
            (None, "https://api.iterable.com"),
            ("unknown", "https://api.iterable.com"),
        ],
    )
    def test_base_url_for_region(self, region: str | None, expected: str) -> None:
        assert base_url_for_region(region) == expected


class TestResolveNextUrl:
    @pytest.mark.parametrize(
        "next_page, expected",
        [
            ("https://api.iterable.com/api/campaigns?page=2", "https://api.iterable.com/api/campaigns?page=2"),
            ("/api/campaigns?page=2", "https://api.iterable.com/api/campaigns?page=2"),
            ("api/campaigns?page=2", "https://api.iterable.com/api/campaigns?page=2"),
            (None, None),
            ("", None),
            (123, None),
            # Off-host absolute URLs must not be followed — the session carries the Api-Key header.
            ("https://evil.com/api/campaigns?page=2", None),
            ("http://api.iterable.com/api/campaigns?page=2", None),
            ("https://api.iterable.com.evil.com/api/campaigns", None),
        ],
    )
    def test_resolve_next_url(self, next_page: Any, expected: str | None) -> None:
        assert _resolve_next_url("https://api.iterable.com", next_page) == expected


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
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_status_code_mapping(self, mock_session, status_code: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("key", "us") is expected

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_network_error_is_invalid(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "us") is False

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_uses_region_base_url(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key", "eu")
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == "https://api.eu.iterable.com/api/channels"

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_sends_api_key_header(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret-key", "us")
        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        # Iterable authenticates with the `Api-Key` header, not `Authorization`.
        assert headers["Api-Key"] == "secret-key"
        assert "Authorization" not in headers


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_api_key_header_auth(self, MockSession) -> None:
        session = MockSession.return_value
        _, auth_snapshots = _wire(session, [_response({"campaigns": [{"id": 1}]})])

        _run(session, "secret-key", "us", "campaigns", _make_manager())

        auth = auth_snapshots[0]
        assert isinstance(auth, APIKeyAuth)
        assert auth.name == "Api-Key"
        assert auth.location == "header"
        assert auth.api_key == "secret-key"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_items_without_saving_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"campaigns": [{"id": 1}, {"id": 2}]})])
        manager = _make_manager()

        rows = _run(session, "key", "us", "campaigns", manager)

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"campaigns": []})])
        manager = _make_manager()

        rows = _run(session, "key", "us", "campaigns", manager)

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_page_url_and_saves_state_after_yield(self, MockSession) -> None:
        session = MockSession.return_value
        urls, _ = _wire(
            session,
            [
                _response({"campaigns": [{"id": 1}], "nextPageUrl": "/api/campaigns?page=2"}),
                _response({"campaigns": [{"id": 2}]}),
            ],
        )
        manager = _make_manager()

        rows = _run(session, "key", "us", "campaigns", manager)

        assert rows == [{"id": 1}, {"id": 2}]
        # Second request follows the resolved (relative -> absolute) next URL.
        assert urls == ["https://api.iterable.com/api/campaigns", "https://api.iterable.com/api/campaigns?page=2"]
        # State is saved once — after the first page yields, pointing at the resolved next URL.
        manager.save_state.assert_called_once_with(
            IterableResumeConfig(next_url="https://api.iterable.com/api/campaigns?page=2")
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession) -> None:
        session = MockSession.return_value
        urls, _ = _wire(session, [_response({"campaigns": [{"id": 9}]})])
        manager = _make_manager(
            resume_state=IterableResumeConfig(next_url="https://api.iterable.com/api/campaigns?page=5")
        )

        _run(session, "key", "us", "campaigns", manager)

        assert urls[0] == "https://api.iterable.com/api/campaigns?page=5"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_resume_state_restarts_from_top(self, MockSession) -> None:
        # A resume URL pointing at another host (corrupted/poisoned state) must not be requested
        # with the Api-Key header — pagination restarts from the endpoint's base URL instead.
        session = MockSession.return_value
        urls, _ = _wire(session, [_response({"campaigns": [{"id": 9}]})])
        manager = _make_manager(resume_state=IterableResumeConfig(next_url="https://evil.com/api/campaigns?page=5"))

        _run(session, "key", "us", "campaigns", manager)

        assert urls[0] == "https://api.iterable.com/api/campaigns"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_next_page_url_stops_pagination(self, MockSession) -> None:
        # An off-host absolute `nextPageUrl` (attacker-echoed) is not followed — pagination stops
        # cleanly after the first page rather than sending the Api-Key header off-host.
        session = MockSession.return_value
        _wire(session, [_response({"campaigns": [{"id": 1}], "nextPageUrl": "https://evil.com/api/campaigns?page=2"})])
        manager = _make_manager()

        rows = _run(session, "key", "us", "campaigns", manager)

        assert rows == [{"id": 1}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_endpoint_data_key(self, MockSession) -> None:
        session = MockSession.return_value
        urls, _ = _wire(session, [_response({"templates": [{"templateId": 7}]})])
        manager = _make_manager()

        rows = _run(session, "key", "us", "templates", manager)

        assert rows == [{"templateId": 7}]
        assert urls[0] == "https://api.iterable.com/api/templates"


class TestIterableSource:
    @pytest.mark.parametrize(
        "endpoint, expected_pk",
        [
            ("campaigns", "id"),
            ("channels", "id"),
            ("lists", "id"),
            ("message_types", "id"),
            ("templates", "templateId"),
        ],
    )
    def test_source_response_primary_keys(self, endpoint: str, expected_pk: str) -> None:
        response = iterable_source(
            "key", "us", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        assert response.name == endpoint
        assert response.primary_keys == [expected_pk]
        assert response.primary_keys == [ITERABLE_ENDPOINTS[endpoint].primary_key]


class TestParseIterableDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2024-01-31 18:04:05 +00:00", datetime(2024, 1, 31, 18, 4, 5, tzinfo=UTC)),
            ("2024-01-31 18:04:05.250 +00:00", datetime(2024, 1, 31, 18, 4, 5, 250000, tzinfo=UTC)),
            ("2024-01-31 20:04:05 +02:00", datetime(2024, 1, 31, 18, 4, 5, tzinfo=UTC)),
            ("2024-01-31 18:04:05", datetime(2024, 1, 31, 18, 4, 5, tzinfo=UTC)),
            ("not a date", "not a date"),
            (1706724245000, 1706724245000),
            (None, None),
        ],
    )
    def test_parse(self, value: Any, expected: Any) -> None:
        assert _parse_iterable_datetime(value) == expected


@mock.patch(f"{MODULE}.time.sleep")
@mock.patch(f"{MODULE}.make_tracked_session")
class TestExport:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel(datetime(2024, 3, 1, tzinfo=UTC), tick=False):
            yield

    def test_walks_windows_from_watermark_and_stages_next_window_before_its_last_batch(
        self, mock_session, mock_sleep
    ) -> None:
        session = mock_session.return_value
        session.get.side_effect = [
            _ndjson([{"email": "a@example.com", "createdAt": "2024-01-20 10:00:00 +00:00"}]),
            _ndjson([{"email": "b@example.com", "createdAt": "2024-02-25 09:30:00 +00:00"}]),
        ]
        manager = _make_manager()
        response = iterable_source(
            "key",
            "eu",
            "email_send",
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
            db_incremental_field_last_value=datetime(2024, 1, 15, tzinfo=UTC),
        )
        events: list[str] = []
        manager.save_state.side_effect = lambda state: events.append(f"save {state.export_window_start}")
        batches: Any = response.items()
        for batch in batches:
            events.append(f"yield {batch[0]['email']}")

        assert [call.args[0] for call in session.get.call_args_list] == [
            "https://api.eu.iterable.com/api/export/data.json"
        ] * 2
        assert [call.kwargs["params"] for call in session.get.call_args_list] == [
            {
                "dataTypeName": "emailSend",
                "startDateTime": "2024-01-15 00:00:00 +00:00",
                "endDateTime": "2024-02-14 00:00:00 +00:00",
            },
            {
                "dataTypeName": "emailSend",
                "startDateTime": "2024-02-14 00:00:00 +00:00",
                "endDateTime": "2024-03-01 00:00:00 +00:00",
            },
        ]
        assert events == ["save 2024-02-14T00:00:00+00:00", "yield a@example.com", "yield b@example.com"]
        mock_sleep.assert_called_once()

    def test_parses_cursor_field_into_datetime(self, mock_session, mock_sleep) -> None:
        mock_session.return_value.get.side_effect = [
            _ndjson([{"email": "a@example.com", "profileUpdatedAt": "2024-02-20 10:00:00 +00:00"}])
        ]
        response = iterable_source(
            "key",
            "us",
            "users",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
            db_incremental_field_last_value=datetime(2024, 2, 10, tzinfo=UTC),
        )

        assert _rows(response) == [
            {"email": "a@example.com", "profileUpdatedAt": datetime(2024, 2, 20, 10, tzinfo=UTC)}
        ]

    @pytest.mark.parametrize(
        "last_value, resume_state, expected_start",
        [
            (None, None, "2023-03-02 00:00:00 +00:00"),
            ("2024-02-20 12:00:00 +00:00", None, "2024-02-20 12:00:00 +00:00"),
            (
                datetime(2024, 2, 20, tzinfo=UTC),
                IterableResumeConfig(export_window_start="2024-02-10T00:00:00+00:00"),
                "2024-02-10 00:00:00 +00:00",
            ),
        ],
    )
    def test_first_window_start(
        self, mock_session, mock_sleep, last_value: Any, resume_state: Any, expected_start: str
    ) -> None:
        session = mock_session.return_value
        session.get.side_effect = lambda *args, **kwargs: _ndjson([])

        _run_rows = _rows(
            iterable_source(
                "key",
                "us",
                "purchase",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(resume_state),
                db_incremental_field_last_value=last_value,
            )
        )

        assert _run_rows == []
        assert session.get.call_args_list[0].kwargs["params"]["startDateTime"] == expected_start

    def test_empty_window_reaches_safe_point(self, mock_session, mock_sleep) -> None:
        mock_session.return_value.get.side_effect = [_ndjson([])]
        manager = _make_manager()

        rows = _rows(
            iterable_source(
                "key",
                "us",
                "email_open",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
                db_incremental_field_last_value=datetime(2024, 2, 20, tzinfo=UTC),
            )
        )

        assert rows == []
        manager.safe_point.assert_called_once()
        manager.save_state.assert_not_called()


@mock.patch(f"{MODULE}.make_tracked_session")
class TestFanOut:
    def test_list_users_carries_list_id_and_skips_blank_lines(self, mock_session) -> None:
        session = mock_session.return_value
        session.get.side_effect = [
            _response({"lists": [{"id": 11}, {"id": 12}]}),
            _text_response("a@example.com\n\nb@example.com\n"),
            _text_response("a@example.com\n"),
        ]

        rows = _rows(
            iterable_source("key", "us", "list_users", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )

        assert rows == [
            {"listId": 11, "email": "a@example.com"},
            {"listId": 11, "email": "b@example.com"},
            {"listId": 12, "email": "a@example.com"},
        ]
        assert [call.kwargs.get("params") for call in session.get.call_args_list[1:]] == [
            {"listId": 11},
            {"listId": 12},
        ]

    def test_campaign_metrics_batches_campaign_ids_and_parses_csv(self, mock_session) -> None:
        session = mock_session.return_value
        session.get.side_effect = [
            _response({"campaigns": [{"id": i} for i in range(1, 102)]}),
            _text_response("id,Total Email Sends,Unique Email Opens\n1,100,40\n2,50,\n"),
            _text_response("id,Total Email Sends,Unique Email Opens\n101,7,3\n"),
        ]

        rows = _rows(
            iterable_source(
                "key", "us", "campaign_metrics", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert rows == [
            {"id": 1, "Total Email Sends": "100", "Unique Email Opens": "40"},
            {"id": 2, "Total Email Sends": "50", "Unique Email Opens": None},
            {"id": 101, "Total Email Sends": "7", "Unique Email Opens": "3"},
        ]
        metrics_params = [call.kwargs["params"] for call in session.get.call_args_list[1:]]
        assert metrics_params == [
            [("campaignId", i) for i in range(1, 101)],
            [("campaignId", 101)],
        ]

    def test_campaign_metrics_with_no_campaigns_makes_no_metrics_request(self, mock_session) -> None:
        session = mock_session.return_value
        session.get.side_effect = [_response({"campaigns": []})]

        rows = _rows(
            iterable_source(
                "key", "us", "campaign_metrics", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert rows == []
        assert session.get.call_count == 1
