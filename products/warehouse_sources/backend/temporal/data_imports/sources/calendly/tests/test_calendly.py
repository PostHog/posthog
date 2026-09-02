import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly import (
    CALENDLY_BASE_URL,
    SUPPORTED_API_VERSIONS,
    CalendlyResumeConfig,
    _format_datetime,
    _webhook_table_transformer,
    calendly_source,
    create_webhook,
    delete_webhook,
    get_current_organization,
    get_external_webhook_info,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.settings import (
    CALENDLY_WEBHOOK_EVENTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# The /users/me bootstrap and validate_credentials build their own tracked session in the calendly module.
CALENDLY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly.make_tracked_session"
)

ORG_URI = "https://api.calendly.com/organizations/ABC123"


def _response(
    collection: Optional[list[dict[str, Any]]],
    next_page: Optional[str] = None,
    *,
    status: int = 200,
    drop_collection: bool = False,
) -> Response:
    body: dict[str, Any] = {"pagination": {"next_page": next_page}}
    if not drop_collection:
        body["collection"] = collection or []
    resp = Response()
    resp.status_code = status
    resp.url = f"{CALENDLY_BASE_URL}/event_types?count=100"
    resp._content = json.dumps(body).encode()
    return resp


def _users_me_response(status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = f"{CALENDLY_BASE_URL}/users/me"
    resp._content = json.dumps({"resource": {"current_organization": ORG_URI}}).encode()
    return resp


def _make_manager(resume_state: Optional[CalendlyResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's url/params AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "event_types", **kwargs):
    return calendly_source(
        token="token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000000Z"),
            ("string_passthrough", "2026-03-04T00:00:00.000000Z", "2026-03-04T00:00:00.000000Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_no_plus_zero_offset_in_output(self) -> None:
        assert "+00:00" not in _format_datetime(datetime(2026, 3, 4, tzinfo=UTC))


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_validate_credentials_status_mapping(
        self, _name: str, status_code: int, expected: bool, mock_session: mock.MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("token") is expected

    @mock.patch(CALENDLY_SESSION_PATCH, side_effect=Exception("network down"))
    def test_validate_credentials_swallows_exceptions(self, _mock_session: mock.MagicMock) -> None:
        assert validate_credentials("token") is False


class TestGetCurrentOrganization:
    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_parses_org_uri(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _users_me_response()
        assert get_current_organization("token") == ORG_URI


class TestPagination:
    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_across_pages_following_next_page(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        next_url = f"{CALENDLY_BASE_URL}/event_types?page=2"
        snapshots = _wire(
            MockClientSession.return_value,
            [_response([{"uri": "a"}, {"uri": "b"}], next_page=next_url), _response([{"uri": "c"}])],
        )
        manager = _make_manager()

        rows = _rows(_source(manager))

        assert [r["uri"] for r in rows] == ["a", "b", "c"]
        # First request is the org-scoped list; second follows the self-contained next_page URL.
        assert snapshots[0]["params"]["count"] == 100
        assert snapshots[0]["params"]["organization"] == ORG_URI
        assert snapshots[1]["url"] == next_url
        assert snapshots[1]["params"] == {}
        # State saved after the first page yielded, pointing at page 2; no save at the end.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == CalendlyResumeConfig(next_url=next_url)

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_collection_yields_nothing(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        _wire(MockClientSession.return_value, [_response([])])

        rows = _rows(_source(_make_manager()))

        assert rows == []

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_collection_key_treated_as_empty(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        _wire(MockClientSession.return_value, [_response(None, drop_collection=True)])

        rows = _rows(_source(_make_manager()))

        assert rows == []

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_mid_pagination_does_not_terminate_early(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        # An empty page that still advertises a next_page must not end the sync.
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        _wire(
            MockClientSession.return_value,
            [_response([], next_page=f"{CALENDLY_BASE_URL}/event_types?page=2"), _response([{"uri": "a"}])],
        )

        rows = _rows(_source(_make_manager()))

        assert [r["uri"] for r in rows] == ["a"]

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_users_me_and_starts_from_saved_url(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        resume_url = f"{CALENDLY_BASE_URL}/event_types?page=5"
        snapshots = _wire(MockClientSession.return_value, [_response([{"uri": "z"}])])
        manager = _make_manager(resume_state=CalendlyResumeConfig(next_url=resume_url))

        rows = _rows(_source(manager))

        assert [r["uri"] for r in rows] == ["z"]
        # No /users/me bootstrap call on resume; first request is the saved URL.
        mock_calendly_session.assert_not_called()
        assert snapshots[0]["url"] == resume_url
        assert snapshots[0]["params"] == {}

    @parameterized.expand([(version,) for version in SUPPORTED_API_VERSIONS])
    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_every_supported_version_targets_calendly_host(
        self, api_version: str, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        snapshots = _wire(MockClientSession.return_value, [_response([{"uri": "a"}])])

        _rows(_source(_make_manager(), api_version=api_version))

        # Both the /users/me bootstrap and the list request must stay on the Calendly host for
        # every pinned version — the version→base-url map must never retarget the bearer token.
        assert mock_calendly_session.return_value.get.call_args.args[0].startswith(CALENDLY_BASE_URL)
        assert all(snapshot["url"].startswith(CALENDLY_BASE_URL) for snapshot in snapshots)

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_request_scopes_to_organization(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        snapshots = _wire(MockClientSession.return_value, [_response([{"uri": "a"}])])

        _rows(_source(_make_manager()))

        # users/me bootstrap first, then the scoped list request carrying the org URI.
        users_me_call = mock_calendly_session.return_value.get.call_args
        assert users_me_call.args[0] == f"{CALENDLY_BASE_URL}/users/me"
        assert snapshots[0]["params"]["organization"] == ORG_URI

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_http_4xx_fails_loudly(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        _wire(MockClientSession.return_value, [_response([], status=401)])

        with pytest.raises(HTTPError, match="401 Client Error"):
            _rows(_source(_make_manager()))


class TestRequestParams:
    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_scheduled_events_adds_sort_and_no_filter_without_incremental(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        snapshots = _wire(MockClientSession.return_value, [_response([{"uri": "a"}])])

        _rows(_source(_make_manager(), endpoint="scheduled_events"))

        assert snapshots[0]["params"]["sort"] == "start_time:asc"
        assert "min_start_time" not in snapshots[0]["params"]

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_scheduled_events_adds_min_start_time_when_incremental(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        snapshots = _wire(MockClientSession.return_value, [_response([{"uri": "a"}])])

        _rows(
            _source(
                _make_manager(),
                endpoint="scheduled_events",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["min_start_time"] == "2026-01-01T00:00:00.000000Z"

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_incremental_endpoint_never_adds_filter(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        snapshots = _wire(MockClientSession.return_value, [_response([{"uri": "a"}])])

        _rows(
            _source(
                _make_manager(),
                endpoint="event_types",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert "min_start_time" not in snapshots[0]["params"]


class TestCalendlySource:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(_make_manager(), endpoint=endpoint)

        assert response.name == endpoint
        assert response.primary_keys == ["uri"]
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"


WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/hog-fn-1"


def _scheduled_event(uri: str = "https://api.calendly.com/scheduled_events/EVENT", **overrides: Any) -> dict[str, Any]:
    return {
        "uri": uri,
        "name": "30 Minute Meeting",
        "status": "active",
        "start_time": "2026-07-10T15:00:00.000000Z",
        "end_time": "2026-07-10T15:30:00.000000Z",
        "created_at": "2026-07-02T12:00:00.000000Z",
        "updated_at": "2026-07-02T12:00:00.000000Z",
        **overrides,
    }


def _delivery(scheduled_event: Optional[dict[str, Any]], created_at: str = "2026-07-02T12:00:00.000000Z") -> dict:
    payload: dict[str, Any] = {"uri": "https://api.calendly.com/scheduled_events/EVENT/invitees/INVITEE"}
    if scheduled_event is not None:
        payload["scheduled_event"] = scheduled_event
    return {"event": "invitee.created", "created_at": created_at, "payload": payload}


def _subscription(
    uuid: str = "sub-1",
    callback_url: str = WEBHOOK_URL,
    **overrides: Any,
) -> dict[str, Any]:
    return {
        "uri": f"https://api.calendly.com/webhook_subscriptions/{uuid}",
        "callback_url": callback_url,
        "events": list(CALENDLY_WEBHOOK_EVENTS),
        "state": "active",
        "scope": "organization",
        "created_at": "2026-07-01T00:00:00.000000Z",
        **overrides,
    }


def _subscriptions_response(items: list[dict[str, Any]], next_page: Optional[str] = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp.url = f"{CALENDLY_BASE_URL}/webhook_subscriptions"
    resp._content = json.dumps({"collection": items, "pagination": {"next_page": next_page}}).encode()
    return resp


def _wire_webhook_session(
    mock_session: mock.MagicMock,
    subscription_pages: Optional[list[Response]] = None,
) -> mock.MagicMock:
    """Serve `/users/me` and the subscription listing off the one patched session factory."""
    session = mock_session.return_value
    pages = list(subscription_pages if subscription_pages is not None else [_subscriptions_response([])])

    def _get(url: str, **_kwargs: Any) -> Response:
        if url.endswith("/users/me"):
            return _users_me_response()
        return pages.pop(0)

    session.get.side_effect = _get
    return session


class TestWebhookTableTransformer:
    def test_lifts_the_nested_scheduled_event_into_the_polled_row_shape(self) -> None:
        table = table_from_py_list([_delivery(_scheduled_event())])

        rows = _webhook_table_transformer(table).to_pylist()

        assert rows == [_scheduled_event()]

    def test_keeps_only_the_latest_delivery_per_scheduled_event(self) -> None:
        # A batch can carry invitee.created then invitee.canceled for one meeting. Delta merge only
        # dedupes across syncs, so the batch itself must collapse to the canceled row.
        table = table_from_py_list(
            [
                _delivery(_scheduled_event(status="active"), created_at="2026-07-02T12:00:00.000000Z"),
                _delivery(_scheduled_event(status="canceled"), created_at="2026-07-03T09:00:00.000000Z"),
            ]
        )

        rows = _webhook_table_transformer(table).to_pylist()

        assert len(rows) == 1
        assert rows[0]["status"] == "canceled"

    def test_out_of_order_deliveries_still_resolve_to_the_newest(self) -> None:
        table = table_from_py_list(
            [
                _delivery(_scheduled_event(status="canceled"), created_at="2026-07-03T09:00:00.000000Z"),
                _delivery(_scheduled_event(status="active"), created_at="2026-07-02T12:00:00.000000Z"),
            ]
        )

        rows = _webhook_table_transformer(table).to_pylist()

        assert [row["status"] for row in rows] == ["canceled"]

    def test_distinct_meetings_are_all_kept(self) -> None:
        table = table_from_py_list(
            [
                _delivery(_scheduled_event(uri="https://api.calendly.com/scheduled_events/A")),
                _delivery(_scheduled_event(uri="https://api.calendly.com/scheduled_events/B")),
            ]
        )

        rows = _webhook_table_transformer(table).to_pylist()

        assert {row["uri"] for row in rows} == {
            "https://api.calendly.com/scheduled_events/A",
            "https://api.calendly.com/scheduled_events/B",
        }

    @parameterized.expand(
        [
            ("no_scheduled_event", _delivery(None)),
            ("scheduled_event_without_uri", _delivery({"name": "30 Minute Meeting"})),
        ]
    )
    def test_deliveries_without_a_usable_scheduled_event_are_dropped(self, _name: str, delivery: dict) -> None:
        assert _webhook_table_transformer(table_from_py_list([delivery])).num_rows == 0

    def test_empty_batch_is_dropped_rather_than_passed_through(self) -> None:
        assert _webhook_table_transformer(table_from_py_list([])).num_rows == 0


class TestCreateWebhook:
    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_creates_an_organization_scoped_subscription_and_keeps_the_signing_key(
        self, mock_session: mock.MagicMock
    ) -> None:
        session = _wire_webhook_session(mock_session)
        created = Response()
        created.status_code = 201
        created._content = json.dumps({"resource": _subscription(signing_key="key-from-calendly")}).encode()
        session.post.return_value = created

        result = create_webhook("token", WEBHOOK_URL)

        assert result.success is True
        # Without the signing key on the hog function every delivery fails verification.
        assert result.extra_inputs["signing_secret"] == "key-from-calendly"
        body = session.post.call_args.kwargs["json"]
        assert body["url"] == WEBHOOK_URL
        assert body["scope"] == "organization"
        assert body["organization"] == ORG_URI
        assert body["events"] == list(CALENDLY_WEBHOOK_EVENTS)
        assert body["signing_key"]

    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_falls_back_to_the_generated_key_when_the_response_omits_it(self, mock_session: mock.MagicMock) -> None:
        session = _wire_webhook_session(mock_session)
        created = Response()
        created.status_code = 201
        created._content = json.dumps({"resource": _subscription()}).encode()
        session.post.return_value = created

        result = create_webhook("token", WEBHOOK_URL)

        assert result.success is True
        assert result.extra_inputs["signing_secret"] == session.post.call_args.kwargs["json"]["signing_key"]

    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_replaces_an_existing_subscription_on_the_same_url(self, mock_session: mock.MagicMock) -> None:
        # Calendly rejects a duplicate callback URL and never hands back an existing subscription's
        # signing key, so the stale one has to go before we can register a key we hold.
        session = _wire_webhook_session(mock_session, [_subscriptions_response([_subscription(uuid="old-sub")])])
        session.delete.return_value = mock.MagicMock(status_code=204)
        created = Response()
        created.status_code = 201
        created._content = json.dumps({"resource": _subscription()}).encode()
        session.post.return_value = created

        result = create_webhook("token", WEBHOOK_URL)

        assert result.success is True
        assert session.delete.call_args.args[0].endswith("/webhook_subscriptions/old-sub")

    @parameterized.expand([("payment_required", 402), ("forbidden", 403), ("conflict", 409)])
    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_rejection_surfaces_an_actionable_error(
        self, _name: str, status_code: int, mock_session: mock.MagicMock
    ) -> None:
        session = _wire_webhook_session(mock_session)
        session.post.return_value = mock.MagicMock(status_code=status_code)

        result = create_webhook("token", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None
        assert "Standard plan" in result.error

    @mock.patch(CALENDLY_SESSION_PATCH, side_effect=Exception("network down"))
    def test_network_failure_is_reported_rather_than_raised(self, _mock_session: mock.MagicMock) -> None:
        result = create_webhook("token", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "network down" in result.error


class TestDeleteWebhook:
    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_deletes_only_subscriptions_pointing_at_our_url(self, mock_session: mock.MagicMock) -> None:
        session = _wire_webhook_session(
            mock_session,
            [
                _subscriptions_response(
                    [
                        _subscription(uuid="ours"),
                        _subscription(uuid="theirs", callback_url="https://elsewhere.example.com/hook"),
                    ]
                )
            ],
        )
        session.delete.return_value = mock.MagicMock(status_code=204)

        result = delete_webhook("token", WEBHOOK_URL)

        assert result.success is True
        assert session.delete.call_count == 1
        assert session.delete.call_args.args[0].endswith("/webhook_subscriptions/ours")

    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_walks_every_page_of_subscriptions(self, mock_session: mock.MagicMock) -> None:
        next_page = f"{CALENDLY_BASE_URL}/webhook_subscriptions?page_token=abc"
        session = _wire_webhook_session(
            mock_session,
            [
                _subscriptions_response([_subscription(uuid="page-1", callback_url="https://other/hook")], next_page),
                _subscriptions_response([_subscription(uuid="page-2")]),
            ],
        )
        session.delete.return_value = mock.MagicMock(status_code=204)

        result = delete_webhook("token", WEBHOOK_URL)

        assert result.success is True
        assert session.delete.call_args.args[0].endswith("/webhook_subscriptions/page-2")

    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_failed_delete_is_reported(self, mock_session: mock.MagicMock) -> None:
        session = _wire_webhook_session(mock_session, [_subscriptions_response([_subscription(uuid="ours")])])
        session.delete.return_value = mock.MagicMock(status_code=500)

        result = delete_webhook("token", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "ours" in result.error

    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_off_origin_next_page_is_refused(self, mock_session: mock.MagicMock) -> None:
        # `pagination.next_page` is response-controlled and the session carries the access token.
        _wire_webhook_session(
            mock_session,
            [_subscriptions_response([], next_page="https://evil.example.com/webhook_subscriptions")],
        )

        result = delete_webhook("token", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "Refusing to follow" in result.error


class TestGetExternalWebhookInfo:
    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_reports_the_registered_subscription(self, mock_session: mock.MagicMock) -> None:
        _wire_webhook_session(mock_session, [_subscriptions_response([_subscription()])])

        info = get_external_webhook_info("token", WEBHOOK_URL)

        assert info.exists is True
        assert info.url == WEBHOOK_URL
        assert info.enabled_events == list(CALENDLY_WEBHOOK_EVENTS)
        assert info.status == "active"

    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_reports_absence_when_nothing_points_at_our_url(self, mock_session: mock.MagicMock) -> None:
        _wire_webhook_session(
            mock_session, [_subscriptions_response([_subscription(callback_url="https://elsewhere/hook")])]
        )

        info = get_external_webhook_info("token", WEBHOOK_URL)

        assert info.exists is False

    @mock.patch(CALENDLY_SESSION_PATCH, side_effect=Exception("network down"))
    def test_network_failure_is_reported_rather_than_raised(self, _mock_session: mock.MagicMock) -> None:
        info = get_external_webhook_info("token", WEBHOOK_URL)

        assert info.exists is False
        assert info.error == "network down"


class TestWebhookPipelineWiring:
    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_webhook_items_replace_the_poll_once_the_schema_is_webhook_backed(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        _wire(MockClientSession.return_value, [_response([{"uri": "polled"}])])
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)
        webhook_manager.get_items.return_value = "webhook-items"

        response = _source(_make_manager(), endpoint="scheduled_events", webhook_source_manager=webhook_manager)

        assert response.items() == "webhook-items"
        assert webhook_manager.get_items.call_args.kwargs["table_transformer"] is _webhook_table_transformer

    @parameterized.expand([("webhook_disabled", "scheduled_events", False), ("non_webhook_table", "groups", True)])
    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_poll_path_is_untouched(
        self,
        _name: str,
        endpoint: str,
        webhook_enabled: bool,
        MockClientSession: mock.MagicMock,
        mock_calendly_session: mock.MagicMock,
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        _wire(MockClientSession.return_value, [_response([{"uri": "polled"}])])
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=webhook_enabled)

        response = _source(_make_manager(), endpoint=endpoint, webhook_source_manager=webhook_manager)

        assert [row["uri"] for page in response.items() for row in page] == ["polled"]
        webhook_manager.get_items.assert_not_called()
