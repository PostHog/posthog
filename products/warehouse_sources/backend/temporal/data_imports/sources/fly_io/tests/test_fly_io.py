import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.fly_io import (
    _sanitize_machine,
    fly_io_source,
    validate_credentials,
)

# RESTClient builds its own tracked session here when no custom session is passed (apps, volumes).
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# The machines stream builds a capture-disabled session in the fly_io module; validate_credentials
# builds its probe session here too.
FLY_IO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.fly_io.make_tracked_session"
)


def _response(body: dict[str, Any], status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

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


class TestPaginationAndUrls:
    @parameterized.expand(
        [
            # Org-scoped endpoints carry the org in the path; the apps endpoint takes it as a query param.
            ("machines", "https://api.machines.dev/v1/orgs/acme/machines", {"limit": 1000}),
            ("volumes", "https://api.machines.dev/v1/orgs/acme/volumes", {"limit": 1000}),
        ]
    )
    @mock.patch(FLY_IO_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_org_scoped_endpoint_puts_org_in_path(
        self, endpoint: str, expected_url: str, expected_params: dict, MockClientSession, MockFlyIoSession
    ) -> None:
        session = MockClientSession.return_value
        MockFlyIoSession.return_value = session
        snaps = _wire(session, [_response({endpoint: [{"id": "x"}], "next_cursor": None})])

        _rows(fly_io_source("tok", endpoint, "acme", team_id=1, job_id="j"))

        assert snaps[0]["url"] == expected_url
        assert snaps[0]["params"] == expected_params

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_apps_endpoint_puts_org_in_query(self, MockClientSession) -> None:
        session = MockClientSession.return_value
        snaps = _wire(session, [_response({"apps": [{"id": "a"}]})])

        _rows(fly_io_source("tok", "apps", "acme", team_id=1, job_id="j"))

        assert snaps[0]["url"] == "https://api.machines.dev/v1/apps"
        assert snaps[0]["params"] == {"org_slug": "acme"}

    @parameterized.expand([("machines",), ("volumes",)])
    @mock.patch(FLY_IO_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reserved_char_in_slug_is_encoded_in_path(self, endpoint: str, MockClientSession, MockFlyIoSession) -> None:
        # A slug carrying a path-reserved char must be percent-encoded, otherwise it could retarget
        # the request to a different API path than the one credential validation checked.
        session = MockClientSession.return_value
        MockFlyIoSession.return_value = session
        snaps = _wire(session, [_response({endpoint: [], "next_cursor": None})])

        _rows(fly_io_source("tok", endpoint, "ac/me", team_id=1, job_id="j"))

        assert snaps[0]["url"] == f"https://api.machines.dev/v1/orgs/ac%2Fme/{endpoint}"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_apps_is_single_request_and_ignores_cursor(self, MockClientSession) -> None:
        # The apps endpoint isn't paginated; a stray next_cursor must not trigger a second request
        # against a cursor the endpoint doesn't accept.
        session = MockClientSession.return_value
        _wire(session, [_response({"apps": [{"id": "app1"}, {"id": "app2"}], "next_cursor": "should-be-ignored"})])

        rows = _rows(fly_io_source("tok", "apps", "acme", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["app1", "app2"]
        assert session.send.call_count == 1

    @mock.patch(FLY_IO_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_machines_follows_cursor_until_exhausted(self, MockClientSession, MockFlyIoSession) -> None:
        # Not advancing the cursor loops forever; not following it silently drops later pages.
        session = MockClientSession.return_value
        MockFlyIoSession.return_value = session
        snaps = _wire(
            session,
            [
                _response({"machines": [{"id": "m1", "app_name": "app1"}], "next_cursor": "c2"}),
                _response({"machines": [{"id": "m2", "app_name": "app2"}], "next_cursor": ""}),
            ],
        )

        rows = _rows(fly_io_source("tok", "machines", "acme", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["m1", "m2"]
        # The second request carries the cursor returned by the first page.
        assert "cursor" not in snaps[0]["params"]
        assert snaps[1]["params"]["cursor"] == "c2"

    @mock.patch(FLY_IO_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_no_rows(self, MockClientSession, MockFlyIoSession) -> None:
        session = MockClientSession.return_value
        MockFlyIoSession.return_value = session
        _wire(session, [_response({"volumes": [], "next_cursor": None})])

        assert _rows(fly_io_source("tok", "volumes", "acme", team_id=1, job_id="j")) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_response_shape_raises(self, MockClientSession) -> None:
        # A bare list where an object wrapper is expected must fail loudly, not silently sync zero rows.
        session = MockClientSession.return_value
        _wire(session, [_response([{"id": "x"}])])  # type: ignore[arg-type]

        with pytest.raises(ValueError):
            _rows(fly_io_source("tok", "apps", "acme", team_id=1, job_id="j"))


class TestSampleCaptureAndRedaction:
    @mock.patch(FLY_IO_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_machines_stream_sanitizes_rows_and_disables_sample_capture(
        self, MockClientSession, MockFlyIoSession
    ) -> None:
        # End-to-end wiring: the machines stream must both redact secrets from every yielded row and
        # opt out of HTTP sample capture, so secrets reach neither the warehouse nor the sample pipeline.
        session = MockClientSession.return_value
        MockFlyIoSession.return_value = session
        _wire(
            session,
            [
                _response(
                    {
                        "machines": [{"id": "m1", "config": {"image": "app", "env": {"SECRET": "x"}}}],
                        "next_cursor": None,
                    }
                )
            ],
        )

        rows = _rows(fly_io_source("tok", "machines", "acme", team_id=1, job_id="j"))

        assert rows == [{"id": "m1", "config": {"image": "app"}}]
        # The machines session is built with sample capture disabled and the token masked.
        MockFlyIoSession.assert_called_once_with(capture=False, redact_values=("tok",))

    @mock.patch(FLY_IO_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_secret_stream_keeps_sample_capture_and_rows_verbatim(
        self, MockClientSession, MockFlyIoSession
    ) -> None:
        # Volumes carry no secrets, so no capture-disabled session is built and rows pass through unchanged.
        session = MockClientSession.return_value
        MockFlyIoSession.return_value = session
        _wire(session, [_response({"volumes": [{"id": "v1", "encrypted": True}], "next_cursor": None})])

        rows = _rows(fly_io_source("tok", "volumes", "acme", team_id=1, job_id="j"))

        assert rows == [{"id": "v1", "encrypted": True}]
        # No custom session is built for a non-secret stream; RESTClient builds the (capturing) one.
        MockFlyIoSession.assert_not_called()


class TestMachineSecretRedaction:
    def test_sanitize_strips_secret_bearing_config_fields(self) -> None:
        # env, files (inline file contents), and secrets would land deployment credentials in the
        # warehouse where any project member with query access could read them — they must be dropped.
        row = {
            "id": "m1",
            "config": {
                "image": "flyio/app:latest",
                "guest": {"cpus": 1, "memory_mb": 256},
                "env": {"DATABASE_URL": "postgres://user:pass@host/db"},
                "secrets": [{"name": "STRIPE_KEY"}],
                "files": [{"guest_path": "/etc/cert.pem", "raw_value": "c3VwZXItc2VjcmV0"}],
                "processes": [
                    {"cmd": ["run"], "env": {"TOKEN": "shhh"}, "secrets": [{"name": "X"}]},
                ],
            },
        }
        sanitized = _sanitize_machine(row)
        config = sanitized["config"]
        assert config["image"] == "flyio/app:latest"
        assert config["guest"] == {"cpus": 1, "memory_mb": 256}
        assert "env" not in config
        assert "secrets" not in config
        assert "files" not in config
        # Processes stay (cmd is operational) but their nested secret vectors are stripped.
        assert config["processes"] == [{"cmd": ["run"]}]
        # The original row is not mutated in place.
        assert "env" in row["config"]

    def test_sanitize_keeps_only_platform_metadata_keys(self) -> None:
        # Fly metadata is a free-form user map, so a user-set secret must not survive; only Fly's
        # own platform keys are known-safe and kept.
        row = {
            "id": "m1",
            "config": {
                "image": "app",
                "metadata": {
                    "fly_process_group": "web",
                    "fly_release_id": "rel_123",
                    "api_token": "FlyV1 super-secret",
                    "DATABASE_PASSWORD": "hunter2",
                },
            },
        }
        metadata = _sanitize_machine(row)["config"]["metadata"]
        assert metadata == {"fly_process_group": "web", "fly_release_id": "rel_123"}

    def test_sanitize_strips_request_headers_from_services_and_checks(self) -> None:
        # Service/check request headers can carry an Authorization credential, so every nested
        # `headers` map must be dropped while the rest of the networking config is kept.
        row = {
            "id": "m1",
            "config": {
                "image": "app",
                "services": [
                    {
                        "internal_port": 8080,
                        "checks": [
                            {
                                "type": "http",
                                "path": "/health",
                                "headers": [{"name": "Authorization", "value": "Bearer secret"}],
                            }
                        ],
                    }
                ],
                "checks": {"web": {"type": "http", "path": "/", "headers": [{"name": "X-Token", "value": "shhh"}]}},
            },
        }
        config = _sanitize_machine(row)["config"]
        assert config["services"] == [{"internal_port": 8080, "checks": [{"type": "http", "path": "/health"}]}]
        assert config["checks"] == {"web": {"type": "http", "path": "/"}}

    def test_sanitize_leaves_row_without_config_untouched(self) -> None:
        row = {"id": "m1", "state": "started"}
        assert _sanitize_machine(row) == row


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
            (401, False),
            (403, False),
            (404, False),
            (500, False),
        ]
    )
    @mock.patch(FLY_IO_SESSION_PATCH)
    def test_status_maps_to_validity(self, status_code: int, expected_valid: bool, MockFlyIoSession) -> None:
        MockFlyIoSession.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        valid, error = validate_credentials("tok", "acme")
        assert valid is expected_valid
        assert (error is None) is expected_valid

    @mock.patch(FLY_IO_SESSION_PATCH)
    def test_network_error_is_not_valid(self, MockFlyIoSession) -> None:
        MockFlyIoSession.return_value.get.side_effect = Exception("no route")
        valid, error = validate_credentials("tok", "acme")
        assert valid is False
        assert error is not None


class TestFlyIoSourceResponse:
    @parameterized.expand(
        [
            ("machines", "created_at"),
            ("volumes", "created_at"),
        ]
    )
    @mock.patch(FLY_IO_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_timestamped_endpoints_partition_on_created_at(
        self, endpoint: str, partition_key: str, MockClientSession, MockFlyIoSession
    ) -> None:
        MockFlyIoSession.return_value = MockClientSession.return_value
        response = fly_io_source("tok", endpoint, "acme", team_id=1, job_id="j")
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        assert response.primary_keys == ["id"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_apps_has_no_partitioning(self, MockClientSession) -> None:
        # App objects carry no timestamp, so partitioning on a nonexistent column would break the sync.
        response = fly_io_source("tok", "apps", "acme", team_id=1, job_id="j")
        assert response.partition_mode is None
        assert response.partition_keys is None
        assert response.primary_keys == ["id"]
