import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.koyeb import (
    USAGE_WINDOW_START,
    KoyebResumeConfig,
    _format_time_value,
    koyeb_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.settings import KOYEB_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# Secret-scrubbed endpoints (and validate_credentials) build their session in the koyeb module.
KOYEB_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.koyeb.make_tracked_session"
)


def _response(data_key: str, items: list[dict[str, Any]] | None, *, has_next: bool | None = None) -> Response:
    body: dict[str, Any] = {data_key: items if items is not None else []}
    if has_next is not None:
        body["has_next"] = has_next
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: KoyebResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session, returning a list that snapshots each request's url/params AT SEND TIME.

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


def _run(endpoint: str, **kwargs: Any):
    return koyeb_source(
        api_token="t",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=kwargs.pop("manager", _make_manager()),
        **kwargs,
    )


class TestFormatTimeValue:
    @parameterized.expand(
        [
            ("naive_datetime", datetime(2024, 5, 1, 12, 30, 45), "2024-05-01T12:30:45Z"),
            ("aware_utc", datetime(2024, 5, 1, 12, 30, 45, tzinfo=UTC), "2024-05-01T12:30:45Z"),
            # Non-UTC offsets must be converted, not just re-labelled.
            (
                "aware_offset",
                datetime(2024, 5, 1, 14, 30, 45, tzinfo=timezone(timedelta(hours=2))),
                "2024-05-01T12:30:45Z",
            ),
            ("date", date(2024, 5, 1), "2024-05-01T00:00:00Z"),
            ("string_passthrough", "2024-05-01T00:00:00Z", "2024-05-01T00:00:00Z"),
        ]
    )
    def test_formats_rfc3339_utc(self, _name: str, value: Any, expected: str) -> None:
        assert _format_time_value(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid or unauthorized Koyeb API token"),
            ("forbidden", 403, False, "Invalid or unauthorized Koyeb API token"),
            ("server_error", 500, False, "Koyeb API error: 500"),
        ]
    )
    @mock.patch(KOYEB_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status: int, expected_ok: bool, expected_error: str | None, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        ok, error = validate_credentials("token")
        assert ok is expected_ok
        assert error == expected_error

    @mock.patch(KOYEB_SESSION_PATCH)
    def test_transport_error_is_invalid(self, mock_session) -> None:
        # validate_via_probe swallows any transport failure and reports "not validated".
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, error = validate_credentials("token")
        assert ok is False
        assert error is not None


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_offset_pagination_and_progresses(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(100)]
        snaps = _wire(
            session, [_response("apps", full_page, has_next=True), _response("apps", [{"id": "last"}], has_next=False)]
        )

        manager = _make_manager()
        rows = _rows(_run("apps", manager=manager))

        assert len(rows) == 101
        assert session.send.call_count == 2
        assert snaps[0]["params"]["offset"] == 0
        assert snaps[0]["params"]["limit"] == 100
        assert snaps[1]["params"]["offset"] == 100
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == KoyebResumeConfig(offset=100)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_terminates_without_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("secrets", [{"id": "s1"}, {"id": "s2"}])])

        manager = _make_manager()
        rows = _rows(_run("secrets", manager=manager))

        assert [r["id"] for r in rows] == ["s1", "s2"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_without_has_next_fetches_until_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(100)]
        _wire(session, [_response("secrets", full_page), _response("secrets", [])])

        rows = _rows(_run("secrets"))

        assert len(rows) == 100
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response("apps", [{"id": "1"}], has_next=False)])

        rows = _rows(_run("apps", manager=_make_manager(KoyebResumeConfig(offset=300))))

        assert [r["id"] for r in rows] == ["1"]
        assert snaps[0]["params"]["offset"] == 300

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_response_data_key_and_path_per_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        # Event streams return rows under "events", not the endpoint name.
        snaps = _wire(session, [_response("events", [{"id": "e1"}], has_next=False)])

        rows = _rows(_run("deployment_events"))

        assert [r["id"] for r in rows] == ["e1"]
        assert snaps[0]["url"].endswith("/v1/deployment_events")


class TestQueryParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_order_param_present_for_ordered_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response("events", [{"id": "e1"}], has_next=False)])
        _rows(_run("app_events"))
        assert snaps[0]["params"]["order"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_order_param_for_plain_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response("apps", [{"id": "a"}], has_next=False)])
        _rows(_run("apps"))
        assert "order" not in snaps[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_instances_sends_starting_time(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response("instances", [{"id": "i1"}], has_next=False)])
        _rows(
            _run(
                "instances",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
            )
        )
        assert snaps[0]["params"]["starting_time"] == "2024-05-01T00:00:00Z"
        assert snaps[0]["params"]["order"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_instances_omits_starting_time(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response("instances", [{"id": "i1"}], has_next=False)])
        _rows(
            _run(
                "instances",
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
            )
        )
        assert "starting_time" not in snaps[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoint_without_time_filter_drops_cutoff(self, MockSession) -> None:
        # apps has no server-side time filter, so a watermark must not become a query param.
        session = MockSession.return_value
        snaps = _wire(session, [_response("apps", [{"id": "a"}], has_next=False)])
        _rows(
            _run(
                "apps",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
            )
        )
        assert "starting_time" not in snaps[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_usage_details_always_sends_required_window(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response("usage_details", [{"instance_id": "x", "started_at": "t"}], has_next=False)])
        _rows(_run("usage_details"))
        assert snaps[0]["params"]["starting_time"] == USAGE_WINDOW_START
        assert "ending_time" in snaps[0]["params"]
        assert snaps[0]["params"]["order"] == "asc"


class TestSecretScrubbing:
    @mock.patch(KOYEB_SESSION_PATCH)
    def test_deployment_definition_secrets_are_redacted(self, mock_session) -> None:
        # Deployment definitions embed plaintext env values and config-file content; leaving them
        # in place would expose credentials to anyone with warehouse-query access.
        session = mock_session.return_value
        _wire(
            session,
            [
                _response(
                    "deployments",
                    [
                        {
                            "id": "d1",
                            "definition": {
                                "env": [
                                    {"key": "DB_PASSWORD", "value": "hunter2"},
                                    {"key": "API_KEY", "secret": "my-secret-ref"},
                                ],
                                "config_files": [{"path": "/etc/app.conf", "content": "token=abc123"}],
                            },
                        }
                    ],
                    has_next=False,
                )
            ],
        )

        rows = _rows(_run("deployments"))

        env = rows[0]["definition"]["env"]
        assert env[0] == {"key": "DB_PASSWORD", "value": "[redacted by PostHog]"}
        # A secret *reference* is just a name, not the value, so it survives untouched.
        assert env[1] == {"key": "API_KEY", "secret": "my-secret-ref"}
        assert rows[0]["definition"]["config_files"][0] == {
            "path": "/etc/app.conf",
            "content": "[redacted by PostHog]",
        }

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_deployment_rows_pass_through_untouched(self, MockSession) -> None:
        # Only definition-bearing endpoints are scrubbed; a stray `value` elsewhere stays.
        session = MockSession.return_value
        _wire(session, [_response("secrets", [{"id": "s1", "value": "keep-me"}], has_next=False)])
        rows = _rows(_run("secrets"))
        assert rows[0] == {"id": "s1", "value": "keep-me"}

    @mock.patch(CLIENT_SESSION_PATCH)
    @mock.patch(KOYEB_SESSION_PATCH)
    def test_capture_disabled_only_for_secret_scrubbed_endpoints(self, mock_koyeb_session, mock_client_session) -> None:
        # HTTP sample capture stores the raw body before the definition scrub runs, so secret-scrubbed
        # endpoints must build a capture-off session; the rest let RESTClient build its own (capture on).
        _wire(mock_koyeb_session.return_value, [_response("deployments", [], has_next=False)])
        _rows(_run("deployments"))
        assert mock_koyeb_session.call_args.kwargs["capture"] is False

        mock_koyeb_session.reset_mock()
        _wire(mock_client_session.return_value, [_response("apps", [], has_next=False)])
        _rows(_run("apps"))
        mock_koyeb_session.assert_not_called()


class TestSourceResponse:
    @parameterized.expand([(name,) for name in KOYEB_ENDPOINTS])
    def test_source_response_per_endpoint(self, endpoint: str) -> None:
        config = KOYEB_ENDPOINTS[endpoint]
        response = koyeb_source(
            api_token="t",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None

    def test_usage_details_composite_primary_key(self) -> None:
        # Usage rows have no id; dropping either half of the composite key would multi-match merges.
        assert KOYEB_ENDPOINTS["usage_details"].primary_keys == ["instance_id", "started_at"]
