import json
from datetime import UTC, date, datetime
from typing import Any, Optional

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
    get_external_webhook_info,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.settings import (
    CALENDLY_WEBHOOK_EVENTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source import CalendlySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calendly import (
    CalendlySourceConfig,
)

# The two webhook-manager integration tests still need direct session patches.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
CALENDLY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly.make_tracked_session"
)

ORG_URI = "https://api.calendly.com/organizations/ABC123"

# Endpoints whose rows lack a `uri` or a `created_at`, as (primary keys, partition key).
ENDPOINT_KEYS: dict[str, tuple[list[str], Optional[str]]] = {
    "activity_log_entries": (["uri"], "occurred_at"),
    "outgoing_communications": (["type", "to", "event_uri", "created_at"], "created_at"),
    "meeting_recap_transcripts": (["uri"], None),
}

# Parent row each fan-out child is bound to, keyed by the child endpoint.
PARENT_URIS = {
    "invitees": "https://api.calendly.com/scheduled_events/EV1",
    "routing_form_submissions": "https://api.calendly.com/routing_forms/RF1",
    "event_type_memberships": "https://api.calendly.com/event_types/ET1",
}


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


def _page(collection: list[dict[str, Any]], next_page: str | None = None, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json={"collection": collection, "pagination": {"next_page": next_page}})


def _me_page(status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json={"resource": {"current_organization": ORG_URI}})


def _driver() -> SourceDriver:
    return SourceDriver(CalendlySource(), CalendlySourceConfig(personal_access_token="token"))


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


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_validate_credentials_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([_me_page(status_code)]) as network:
            assert validate_credentials("token") == (expected, status_code)
        assert network.requests_log[0].path == "/users/me"
        assert network.requests_log[0].headers["authorization"] == "Bearer token"


class TestPagination:
    def test_empty_page_mid_pagination_does_not_terminate_early(self) -> None:
        # An empty page that still advertises a next_page must not end the sync.
        result = _driver().run(
            "event_types",
            [_me_page(), _page([], next_page=f"{CALENDLY_BASE_URL}/event_types?page=2"), _page([{"uri": "a"}])],
        )

        assert result.raised is None
        assert [row["uri"] for row in result.rows] == ["a"]
        assert result.paths == ["/users/me", "/event_types", "/event_types"]
        assert result.params("page") == [None, None, "2"]

    def test_resume_skips_users_me_and_starts_from_saved_url(self) -> None:
        resume_url = f"{CALENDLY_BASE_URL}/event_types?page=5"
        result = _driver().run(
            "event_types", [_page([{"uri": "z"}])], resume_state=CalendlyResumeConfig(next_url=resume_url)
        )

        assert result.raised is None
        assert [row["uri"] for row in result.rows] == ["z"]
        # No /users/me bootstrap call on resume; first request is the saved URL.
        assert result.urls == [resume_url]
        assert result.queries == [{"page": ("5",)}]

    @parameterized.expand([(version,) for version in SUPPORTED_API_VERSIONS])
    def test_every_supported_version_targets_calendly_host(self, api_version: str) -> None:
        result = _driver().run("event_types", [_me_page(), _page([{"uri": "a"}])], api_version=api_version)

        # Both the /users/me bootstrap and the list request must stay on the Calendly host for
        # every pinned version — the version→base-url map must never retarget the bearer token.
        assert result.raised is None
        assert result.paths == ["/users/me", "/event_types"]
        assert all(url.startswith(CALENDLY_BASE_URL) for url in result.urls)

    def test_http_4xx_fails_loudly(self) -> None:
        result = _driver().run("event_types", [_me_page(), _page([], status=401)])

        assert isinstance(result.raised, HTTPError)
        assert "401 Client Error" in str(result.raised)


class TestRequestParams:
    @parameterized.expand(
        [
            ("scheduled_events", "min_start_time", "start_time:asc"),
            ("activity_log_entries", "min_occurred_at", "occurred_at:asc"),
        ]
    )
    def test_incremental_endpoint_sends_its_time_filter(self, endpoint: str, filter_param: str, sort: str) -> None:
        result = _driver().run(
            endpoint,
            [_me_page(), _page([{"uri": "a"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[1].param(filter_param) == "2026-01-01T00:00:00.000000Z"
        # The filter only bounds the walk when rows arrive oldest first.
        assert result.requests[1].param("sort") == sort
        assert result.requests[1].param("organization") == ORG_URI

    @parameterized.expand(
        [
            ("group_relationships", ["/users/me", "/group_relationships"], ORG_URI),
            ("outgoing_communications", ["/users/me", "/outgoing_communications"], ORG_URI),
            # Recaps are listed for the token's user, so the organization lookup is skipped.
            ("meeting_recaps", ["/meeting_recaps"], None),
        ]
    )
    def test_top_level_endpoint_scoping(
        self, endpoint: str, expected_paths: list[str], organization: str | None
    ) -> None:
        result = _driver().run(endpoint, [*([_me_page()] if organization else []), _page([{"uri": "a"}])])

        assert result.raised is None
        assert result.paths == expected_paths
        assert result.requests[-1].param("organization") == organization
        assert result.requests[-1].param("sort") is None
        assert len(result.rows) == 1

    def test_non_incremental_endpoint_never_adds_filter(self) -> None:
        result = _driver().run(
            "event_types",
            [_me_page(), _page([{"uri": "a"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[1].param("min_start_time") is None


class TestFanoutEndpoints:
    """The three child endpoints scoped to a parent resource, fanned out one request per parent."""

    @parameterized.expand(
        [
            (
                "invitees",
                "scheduled_events",
                f"{CALENDLY_BASE_URL}/scheduled_events/EV1/invitees",
                "created_at:asc",
            ),
            (
                "routing_form_submissions",
                "routing_forms",
                f"{CALENDLY_BASE_URL}/routing_form_submissions?form=https%3A%2F%2Fapi.calendly.com%2Frouting_forms%2FRF1",
                "created_at:asc",
            ),
            (
                "event_type_memberships",
                "event_types",
                f"{CALENDLY_BASE_URL}/event_type_memberships?event_type=https%3A%2F%2Fapi.calendly.com%2Fevent_types%2FET1",
                # The only list endpoint that accepts no sort param.
                None,
            ),
        ]
    )
    def test_child_request_is_bound_to_its_parent(
        self,
        endpoint: str,
        parent: str,
        expected_child_url: str,
        expected_sort: Optional[str],
    ) -> None:
        result = _driver().run(
            endpoint,
            [_me_page(), _page([{"uri": PARENT_URIS[endpoint]}]), _page([{"uri": "child-1"}])],
        )

        # The parent walk stays org-scoped; the child carries the parent identity in its path,
        # percent-encoded where it rides in a query param.
        assert result.raised is None
        assert result.requests[1].path == f"/{parent}"
        assert result.requests[1].param("organization") == ORG_URI
        assert result.requests[2].url.startswith(expected_child_url)
        assert result.requests[2].param("sort") == expected_sort
        assert result.requests[2].param("count") == "100"
        assert [row["uri"] for row in result.rows] == ["child-1"]

    def test_transcripts_fan_out_over_recaps_and_skip_missing_ones(self) -> None:
        recaps = [
            {"uri": "https://api.calendly.com/meeting_recaps/R1"},
            {"uri": "https://api.calendly.com/meeting_recaps/R2"},
        ]
        transcript = {"uri": "https://api.calendly.com/meeting_recaps/R1/transcript", "text": "Host: Hello"}

        result = _driver().run(
            "meeting_recap_transcripts",
            [_page(recaps), ScriptedResponse(json={"resource": transcript}), ScriptedResponse(status=404)],
        )

        assert result.raised is None
        assert result.paths == ["/meeting_recaps", "/meeting_recaps/R1/transcript", "/meeting_recaps/R2/transcript"]
        # The transcript endpoint returns one object and takes no paging params.
        assert result.requests[1].query == {}
        assert result.rows == [{**transcript, "meeting_recap": "https://api.calendly.com/meeting_recaps/R1"}]


class TestCalendlySource:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        primary_keys, partition_key = ENDPOINT_KEYS.get(endpoint, (["uri"], "created_at"))

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.partition_mode == ("datetime" if partition_key else None)


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


def _subscriptions_response(items: list[dict[str, Any]], next_page: Optional[str] = None) -> ScriptedResponse:
    return ScriptedResponse(json={"collection": items, "pagination": {"next_page": next_page}})


class TestWebhookTableTransformer:
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
    def test_creates_an_organization_scoped_subscription_and_keeps_the_signing_key(self) -> None:
        with scripted_network(
            [
                _me_page(),
                _subscriptions_response([]),
                ScriptedResponse(status=201, json={"resource": _subscription(signing_key="key-from-calendly")}),
            ]
        ) as network:
            result = create_webhook("token", WEBHOOK_URL)

        assert result.success is True
        # Without the signing key on the hog function every delivery fails verification.
        assert result.extra_inputs["signing_secret"] == "key-from-calendly"
        assert [request.method for request in network.requests_log] == ["GET", "GET", "POST"]
        body = network.requests_log[2].json()
        assert body["url"] == WEBHOOK_URL
        assert body["scope"] == "organization"
        assert body["organization"] == ORG_URI
        assert body["events"] == list(CALENDLY_WEBHOOK_EVENTS)
        assert body["signing_key"]

    @parameterized.expand([("payment_required", 402), ("forbidden", 403), ("conflict", 409)])
    def test_rejection_surfaces_an_actionable_error(self, _name: str, status_code: int) -> None:
        with scripted_network(
            [_me_page(), _subscriptions_response([]), ScriptedResponse(status=status_code)]
        ) as network:
            result = create_webhook("token", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None
        assert "Standard plan" in result.error
        assert network.requests_log[2].path == "/webhook_subscriptions"

    def test_network_failure_is_reported_rather_than_raised(self) -> None:
        with scripted_network(always(ConnectionResetError("network down"))) as network:
            result = create_webhook("token", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "network down" in result.error
        assert {request.path for request in network.requests_log} == {"/users/me"}


class TestDeleteWebhook:
    def test_deletes_only_subscriptions_pointing_at_our_url(self) -> None:
        with scripted_network(
            [
                _me_page(),
                _subscriptions_response(
                    [
                        _subscription(uuid="ours"),
                        _subscription(uuid="theirs", callback_url="https://elsewhere.example.com/hook"),
                    ]
                ),
                ScriptedResponse(status=204),
            ]
        ) as network:
            result = delete_webhook("token", WEBHOOK_URL)

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET", "GET", "DELETE"]
        assert network.requests_log[2].path == "/webhook_subscriptions/ours"

    def test_failed_delete_is_reported(self) -> None:
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/users/me":
                return _me_page()
            if request.method == "GET":
                return _subscriptions_response([_subscription(uuid="ours")])
            return ScriptedResponse(status=500)

        with scripted_network(answer) as network:
            result = delete_webhook("token", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "ours" in result.error
        assert {request.path for request in network.requests_log[2:]} == {"/webhook_subscriptions/ours"}

    def test_off_origin_next_page_is_refused(self) -> None:
        # `pagination.next_page` is response-controlled and the session carries the access token.
        with scripted_network(
            [_me_page(), _subscriptions_response([], next_page="https://evil.example.com/webhook_subscriptions")]
        ) as network:
            result = delete_webhook("token", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "Refusing to follow" in result.error
        assert [request.path for request in network.requests_log] == ["/users/me", "/webhook_subscriptions"]


class TestGetExternalWebhookInfo:
    def test_reports_the_registered_subscription(self) -> None:
        with scripted_network([_me_page(), _subscriptions_response([_subscription()])]) as network:
            info = get_external_webhook_info("token", WEBHOOK_URL)

        assert info.exists is True
        assert info.url == WEBHOOK_URL
        assert info.enabled_events == list(CALENDLY_WEBHOOK_EVENTS)
        assert info.status == "active"
        assert network.requests_log[1].param("organization") == ORG_URI

    def test_reports_absence_when_nothing_points_at_our_url(self) -> None:
        with scripted_network(
            [_me_page(), _subscriptions_response([_subscription(callback_url="https://elsewhere/hook")])]
        ):
            info = get_external_webhook_info("token", WEBHOOK_URL)

        assert info.exists is False

    def test_network_failure_is_reported_rather_than_raised(self) -> None:
        with scripted_network(always(ConnectionResetError("network down"))) as network:
            info = get_external_webhook_info("token", WEBHOOK_URL)

        assert info.exists is False
        assert info.error is not None and "network down" in info.error
        assert {request.path for request in network.requests_log} == {"/users/me"}


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
