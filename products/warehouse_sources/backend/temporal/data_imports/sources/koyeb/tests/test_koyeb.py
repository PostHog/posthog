from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.koyeb import KoyebSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.koyeb import (
    KoyebResumeConfig,
    _format_time_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.settings import KOYEB_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.source import KoyebSource


def _driver() -> SourceDriver:
    return SourceDriver(KoyebSource(), KoyebSourceConfig(api_token="token"))


def _response(data_key: str, items: list[dict[str, Any]], *, has_next: bool | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {data_key: items}
    if has_next is not None:
        body["has_next"] = has_next
    return ScriptedResponse(json=body)


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
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool, expected_error: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            ok, error = validate_credentials("token")

        assert ok is expected_ok
        assert error == expected_error
        assert {request.path for request in network.requests_log} == {"/v1/account/profile"}
        assert all(request.headers["authorization"] == "Bearer token" for request in network.requests_log)

    def test_transport_error_is_invalid(self) -> None:
        # validate_via_probe swallows any transport failure and reports "not validated".
        with scripted_network(always(ConnectionError("boom"))) as network:
            ok, error = validate_credentials("token")

        assert ok is False
        assert error == "Could not reach the Koyeb API"
        assert {request.path for request in network.requests_log} == {"/v1/account/profile"}


class TestPagination:
    @parameterized.expand(
        [
            ("apps", "apps", True),
            # Catalog replies carry only `count`, no `has_next`, so the short page must end the walk.
            ("catalog_instances", "instances", None),
        ]
    )
    def test_follows_offset_pagination_and_progresses(
        self, endpoint: str, data_key: str, has_next: bool | None
    ) -> None:
        full_page = [{"id": str(i)} for i in range(100)]
        result = _driver().run(
            endpoint,
            [
                _response(data_key, full_page, has_next=has_next),
                _response(data_key, [{"id": "last"}], has_next=False if has_next else None),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 101
        assert len(result.requests) == 2
        assert result.params("offset") == ["0", "100"]
        assert result.params("limit") == ["100", "100"]
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        assert result.saved_states == [KoyebResumeConfig(offset=100)]

    def test_resumes_from_the_saved_offset(self) -> None:
        result = _driver().run(
            "apps", [_response("apps", [{"id": "a"}], has_next=False)], resume_state=KoyebResumeConfig(offset=200)
        )

        assert result.raised is None
        assert result.params("offset") == ["200"]
        assert result.rows == [{"id": "a"}]


class TestQueryParams:
    def test_incremental_instances_sends_starting_time(self) -> None:
        result = _driver().run(
            "instances",
            [_response("instances", [{"id": "i1"}], has_next=False)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("starting_time") == "2024-05-01T00:00:00Z"
        assert result.requests[0].param("order") == "asc"


class TestSecretScrubbing:
    def test_deployment_definition_secrets_are_redacted(self) -> None:
        # Deployment definitions embed plaintext env values and config-file content; leaving them
        # in place would expose credentials to anyone with warehouse-query access.
        result = _driver().run(
            "deployments",
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

        assert result.raised is None
        env = result.rows[0]["definition"]["env"]
        assert env[0] == {"key": "DB_PASSWORD", "value": "[redacted by PostHog]"}
        # A secret *reference* is just a name, not the value, so it survives untouched.
        assert env[1] == {"key": "API_KEY", "secret": "my-secret-ref"}
        assert result.rows[0]["definition"]["config_files"][0] == {
            "path": "/etc/app.conf",
            "content": "[redacted by PostHog]",
        }

    def test_capture_disabled_only_for_secret_scrubbed_endpoints(self) -> None:
        # HTTP sample capture stores the raw body before the definition scrub runs, so secret-scrubbed
        # endpoints must build a capture-off session; the rest let RESTClient build its own (capture on).
        deployments = _driver().run("deployments", [_response("deployments", [], has_next=False)])
        apps = _driver().run("apps", [_response("apps", [], has_next=False)])

        assert deployments.raised is None
        assert apps.raised is None
        assert len(deployments.session_options) == 1
        assert deployments.session_options[0]["capture"] is False
        assert len(apps.session_options) == 1
        assert "capture" not in apps.session_options[0]


class TestSourceResponse:
    @parameterized.expand([(name,) for name in KOYEB_ENDPOINTS])
    def test_source_response_per_endpoint(self, endpoint: str) -> None:
        config = KOYEB_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_response(config.response_data_key, [])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        assert result.response.sort_mode == "asc"
        if config.partition_key:
            assert result.response.partition_keys == [config.partition_key]
            assert result.response.partition_mode == "datetime"
        else:
            assert result.response.partition_keys is None

    def test_usage_details_composite_primary_key(self) -> None:
        # Usage rows have no id; dropping either half of the composite key would multi-match merges.
        assert KOYEB_ENDPOINTS["usage_details"].primary_keys == ["instance_id", "started_at"]
