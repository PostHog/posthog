from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.fly_io import (
    _sanitize_config_field,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.source import FlyIoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flyio import FlyIoSourceConfig


def _driver(org_slug: str = "acme") -> SourceDriver:
    return SourceDriver(FlyIoSource(), FlyIoSourceConfig(api_token="tok", organization_slug=org_slug))


class TestPaginationAndUrls:
    @parameterized.expand(
        [
            # Org-scoped endpoints carry the org in the path; the apps endpoint takes it as a query param.
            ("machines", "https://api.machines.dev/v1/orgs/acme/machines", {"limit": 1000}),
            ("volumes", "https://api.machines.dev/v1/orgs/acme/volumes", {"limit": 1000}),
        ]
    )
    def test_org_scoped_endpoint_puts_org_in_path(
        self, endpoint: str, expected_url: str, expected_params: dict[str, int]
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={endpoint: [{"id": "x"}], "next_cursor": None})])

        assert result.raised is None
        assert [url.split("?", 1)[0] for url in result.urls] == [expected_url]
        assert result.queries == [{key: (str(value),) for key, value in expected_params.items()}]

    @parameterized.expand([("machines",), ("volumes",)])
    def test_reserved_char_in_slug_is_encoded_in_path(self, endpoint: str) -> None:
        # A slug carrying a path-reserved char must be percent-encoded, otherwise it could retarget
        # the request to a different API path than the one credential validation checked.
        result = _driver("ac/me").run(endpoint, [ScriptedResponse(json={endpoint: [], "next_cursor": None})])

        assert result.raised is None
        assert result.paths == [f"/v1/orgs/ac%2Fme/{endpoint}"]

    def test_unexpected_response_shape_raises(self) -> None:
        # A bare list where an object wrapper is expected must fail loudly, not silently sync zero rows.
        result = _driver().run("apps", [ScriptedResponse(json=[{"id": "x"}])])

        assert isinstance(result.raised, ValueError)


class TestFanout:
    @parameterized.expand(
        [
            (
                "machine_events",
                "machines",
                {"id": "m1", "app_name": "app1"},
                [{"id": "e1", "type": "start"}],
                "https://api.machines.dev/v1/apps/app1/machines/m1/events",
                {"machine_id": "m1", "app_name": "app1"},
            ),
            (
                "machine_versions",
                "machines",
                {"id": "m1", "app_name": "app1"},
                [{"version": "v1", "user_config": {"image": "app"}}],
                "https://api.machines.dev/v1/apps/app1/machines/m1/versions",
                {"machine_id": "m1", "app_name": "app1"},
            ),
            (
                "volume_snapshots",
                "volumes",
                {"id": "vol1", "app_name": "app1"},
                [{"id": "s1", "created_at": "2026-01-01T00:00:00Z"}],
                "https://api.machines.dev/v1/apps/app1/volumes/vol1/snapshots",
                {"volume_id": "vol1", "app_name": "app1"},
            ),
        ]
    )
    def test_child_path_binds_to_its_parent_row_and_carries_its_columns(
        self,
        endpoint: str,
        parent: str,
        parent_row: dict[str, Any],
        child_rows: list[dict[str, Any]],
        expected_child_url: str,
        expected_parent_columns: dict[str, str],
    ) -> None:
        # The child path needs BOTH the app name and the resource id from the same parent row, and
        # each row has to carry them as flat columns — the composite primary key is built from them.
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={parent: [parent_row], "next_cursor": None}), ScriptedResponse(json=child_rows)],
        )

        assert result.raised is None
        assert result.urls[1].split("?", 1)[0] == expected_child_url
        assert result.requests[1].param("limit") == ("50" if endpoint == "machine_events" else None)
        assert len(result.rows) == len(child_rows)
        for row in result.rows:
            for column, value in expected_parent_columns.items():
                assert row[column] == value
            # The raw `_<parent>_<field>` keys the fan-out injects must not survive into the table.
            assert not any(key.startswith(f"_{parent}_") for key in row)

    def test_machine_versions_sanitizes_its_user_config(self) -> None:
        # A version row carries the whole machine config under `user_config`, so it needs the same
        # redaction as the machines stream — otherwise deploy secrets land in the warehouse.
        result = _driver().run(
            "machine_versions",
            [
                ScriptedResponse(json={"machines": [{"id": "m1", "app_name": "app1"}], "next_cursor": None}),
                ScriptedResponse(json=[{"version": "v1", "user_config": {"image": "app", "env": {"SECRET": "x"}}}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"version": "v1", "user_config": {"image": "app"}, "machine_id": "m1", "app_name": "app1"}
        ]

    @parameterized.expand([("machine_events",), ("machine_versions",)])
    def test_machine_parented_streams_disable_sample_capture(self, endpoint: str) -> None:
        # The machines listing that drives these fan-outs returns machine configs, so their traffic
        # can carry secrets even where the child rows cannot.
        result = _driver().run(endpoint, [ScriptedResponse(json={"machines": [], "next_cursor": None})])

        assert result.raised is None
        assert result.session_options == [{"capture": False, "redact_values": ("tok",)}]


class TestSampleCaptureAndRedaction:
    def test_machines_stream_sanitizes_rows_and_disables_sample_capture(self) -> None:
        # End-to-end wiring: the machines stream must both redact secrets from every yielded row and
        # opt out of HTTP sample capture, so secrets reach neither the warehouse nor the sample pipeline.
        result = _driver().run(
            "machines",
            [
                ScriptedResponse(
                    json={
                        "machines": [{"id": "m1", "config": {"image": "app", "env": {"SECRET": "x"}}}],
                        "next_cursor": None,
                    },
                )
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "m1", "config": {"image": "app"}}]
        # The machines session is built with sample capture disabled and the token masked.
        assert result.session_options == [{"capture": False, "redact_values": ("tok",)}]

    def test_non_secret_stream_keeps_sample_capture_and_rows_verbatim(self) -> None:
        # Volumes carry no secrets, so no capture-disabled session is built and rows pass through unchanged.
        result = _driver().run(
            "volumes", [ScriptedResponse(json={"volumes": [{"id": "v1", "encrypted": True}], "next_cursor": None})]
        )

        assert result.raised is None
        assert result.rows == [{"id": "v1", "encrypted": True}]
        # No custom session is built for a non-secret stream; RESTClient builds the (capturing) one.
        assert result.session_options == [{"redact_values": ("tok",)}]


_sanitize_machine = _sanitize_config_field("config")


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
            (404, False),
        ]
    )
    def test_status_maps_to_validity(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, error = validate_credentials("tok", "acme")

        assert valid is expected_valid
        assert (error is None) is expected_valid
        assert network.requests_log[0].path == "/v1/apps"
        assert network.requests_log[0].param("org_slug") == "acme"
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"

    def test_network_error_is_not_valid(self) -> None:
        with scripted_network(always(ConnectionError("no route"))) as network:
            valid, error = validate_credentials("tok", "acme")

        assert valid is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/v1/apps"}


class TestFlyIoSourceResponse:
    @parameterized.expand(
        [
            ("machines", "created_at"),
            ("volumes", "created_at"),
            ("volume_snapshots", "created_at"),
        ]
    )
    def test_timestamped_endpoints_partition_on_created_at(self, endpoint: str, partition_key: str) -> None:
        parent = "volumes" if endpoint == "volume_snapshots" else endpoint
        result = _driver().run(endpoint, [ScriptedResponse(json={parent: [], "next_cursor": None})])

        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == [partition_key]

    @parameterized.expand([("apps",), ("regions",), ("machine_events",), ("machine_versions",)])
    def test_timestampless_endpoints_have_no_partitioning(self, endpoint: str) -> None:
        # These rows carry no RFC 3339 timestamp (machine events only carry epoch milliseconds), so
        # partitioning on one would break the sync.
        parent = "machines" if endpoint in ("machine_events", "machine_versions") else endpoint
        wrapper = "Regions" if endpoint == "regions" else parent
        result = _driver().run(endpoint, [ScriptedResponse(json={wrapper: [], "next_cursor": None})])

        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
