from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import orjson

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yousign import (
    YouSignSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.settings import (
    SIGNATURE_REQUEST_SOURCES,
    WEBHOOK_EVENTS,
    YOUSIGN_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.source import YouSignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign import (
    YousignResumeConfig,
    _date_filter_value,
    create_webhook,
    delete_webhook,
    get_resource,
    make_webhook_table_transformer,
    update_webhook_events,
    validate_credentials,
    yousign_source,
)

TEAM_ID = 1
JOB_ID = "job-1"


def _make_manager(resume_state: YousignResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _driver() -> SourceDriver:
    return SourceDriver(YouSignSource(), YouSignSourceConfig(api_key="key", environment="production"))


class TestDateFilterValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            # Backs off one day so the date-granular filter can't drop rows from the watermark day.
            (datetime(2025, 3, 2, 15, 30, tzinfo=UTC), "2025-03-01"),
            (date(2025, 3, 2), "2025-03-01"),
            ("2025-03-02T15:30:00Z", "2025-03-01"),
            (1740924000, "2025-03-01"),  # 2025-03-02 UTC as epoch seconds
            (None, None),
            ("not-a-date", None),
        ],
    )
    def test_formats_watermark_as_previous_day(self, value: Any, expected: str | None) -> None:
        assert _date_filter_value(value) == expected


def _endpoint_params(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], resource["endpoint"]["params"])


class TestGetResource:
    def test_signature_requests_override_the_source_filter(self) -> None:
        # Without the override Yousign only returns API-created requests (source[eq]=public_api),
        # silently dropping everything created from the app.
        resource = get_resource(YOUSIGN_ENDPOINTS["signature_requests"], False, None)
        params = _endpoint_params(resource)
        assert params["source[in]"] == SIGNATURE_REQUEST_SOURCES
        assert params["limit"] == 100
        assert resource["write_disposition"] == "replace"
        assert not any("[after]" in key for key in params)

    @pytest.mark.parametrize("field", ["created_at", "activated_at", "completed_at"])
    def test_incremental_adds_server_side_date_filter(self, field: str) -> None:
        resource = get_resource(YOUSIGN_ENDPOINTS["signature_requests"], True, field)
        incremental_param = _endpoint_params(resource)[f"{field}[after]"]
        assert incremental_param["type"] == "incremental"
        assert incremental_param["cursor_path"] == field
        assert incremental_param["convert"] is _date_filter_value
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    @pytest.mark.parametrize("endpoint, field", [("signature_requests", "updated_at"), ("contacts", "created_at")])
    def test_incremental_rejects_unsupported_fields(self, endpoint: str, field: str) -> None:
        with pytest.raises(ValueError, match="does not support incremental field"):
            get_resource(YOUSIGN_ENDPOINTS[endpoint], True, field)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (401, None, False),
            # A workspace-scoped key may legitimately lack some permissions — don't block
            # source-create on a 403, but do fail the per-schema probe.
            (403, None, True),
            (403, "users", False),
            (500, None, False),
        ],
    )
    def test_status_mapping(self, status: int, schema_name: str | None, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            valid, _ = validate_credentials("key", "production", schema_name)
        assert valid is expected_valid


class TestYousignSourceResponse:
    @staticmethod
    def _assert_metadata(endpoint: str, response: Any) -> None:
        config = YOUSIGN_ENDPOINTS[endpoint]
        expected_keys = config.primary_key if isinstance(config.primary_key, list) else [config.primary_key]
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        # Yousign has no sort param and pages arrive newest-first; declaring "asc" would corrupt
        # the incremental watermark after the first batch.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"

    @pytest.mark.parametrize("endpoint", list(YOUSIGN_ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        response = _driver().run(endpoint, []).response
        assert response is not None
        self._assert_metadata(endpoint, response)

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "signature_requests",
            [ScriptedResponse(json={"data": [{"id": "sr-1"}], "meta": {"next_cursor": None}})],
            resume_state=YousignResumeConfig(cursor="tok"),
        )

        assert result.requests[0].param("after") == "tok"

    def test_checkpoint_saves_only_when_a_next_page_exists(self) -> None:
        result = _driver().run(
            "signature_requests",
            [
                ScriptedResponse(json={"data": [{"id": "sr-1"}], "meta": {"next_cursor": "tok3"}}),
                ScriptedResponse(json={"data": [{"id": "sr-2"}], "meta": {"next_cursor": None}}),
            ],
        )

        assert result.saved_states == [YousignResumeConfig(cursor="tok3")]

    # Patch out the real async_to_sync: running its event loop closes the thread-local Django
    # connection, which poisons DB-backed tests (e.g. migration tests) later in the same worker.
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.async_to_sync",
        lambda fn: fn,
    )
    def test_webhook_enabled_schema_reads_from_webhook_manager(self) -> None:
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.MagicMock(return_value=True)
        webhook_manager.get_items.return_value = iter([])

        response = yousign_source(
            api_key="key",
            environment="production",
            endpoint="signature_requests",
            team_id=TEAM_ID,
            job_id=JOB_ID,
            resumable_source_manager=_make_manager(),
            webhook_source_manager=webhook_manager,
        )
        list(cast(Iterable[Any], response.items()))

        webhook_manager.get_items.assert_called_once()


class TestWebhookTableTransformer:
    def test_strips_signer_signature_link_from_webhook_rows(self) -> None:
        # `signature_link` is a `no_otp`-usable signing URL — it must never reach the warehouse.
        envelope = {
            "event_name": "signature_request.activated",
            "event_time": "100",
            "data": {
                "signature_request": {
                    "id": "sr-1",
                    "status": "ongoing",
                    "signers": [{"id": "s-1", "signature_link": "https://yousign.app/sign/abc"}],
                }
            },
        }
        rows = make_webhook_table_transformer()(table_from_py_list([envelope])).to_pylist()
        # Nested fields round-trip through parquet as JSON strings.
        signers = orjson.loads(rows[0]["signers"]) if isinstance(rows[0]["signers"], str) else rows[0]["signers"]
        assert signers[0].get("signature_link") is None
        assert signers[0]["id"] == "s-1"

    def test_parses_json_string_data_and_drops_malformed_rows(self) -> None:
        table = table_from_py_list(
            [
                {
                    "event_name": "signature_request.done",
                    "event_time": "100",
                    "data": '{"signature_request": {"id": "sr-3", "status": "done"}}',
                },
                {"event_name": "signature_request.done", "event_time": "101", "data": None},
                {"event_name": "signature_request.done", "event_time": "102", "data": '{"signature_request": {}}'},
            ]
        )
        rows = make_webhook_table_transformer()(table).to_pylist()
        assert [row["id"] for row in rows] == ["sr-3"]


class TestCapabilityLinkStripping:
    """Signing and approval links (capability fields) must never reach the warehouse on any path."""

    @pytest.mark.parametrize(
        "endpoint, link_field",
        [("signers", "signature_link"), ("approvers", "approval_link")],
    )
    def test_fanout_strips_capability_link(self, endpoint: str, link_field: str) -> None:
        result = _driver().run(
            endpoint,
            route(
                {
                    "/signature_requests": [
                        ScriptedResponse(json={"data": [{"id": "sr-1"}], "meta": {"next_cursor": None}})
                    ],
                    f"/signature_requests/sr-1/{endpoint}": [
                        ScriptedResponse(json=[{"id": "r-1", "status": "notified", link_field: "https://link/abc"}])
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.rows[0].get(link_field) is None
        assert result.rows[0]["id"] == "r-1"
        assert result.rows[0]["signature_request_id"] == "sr-1"

    def test_signature_requests_strips_embedded_links(self) -> None:
        result = _driver().run(
            "signature_requests",
            [
                ScriptedResponse(
                    json={
                        "data": [
                            {
                                "id": "sr-1",
                                "signers": [{"id": "s-1", "signature_link": "https://sign/abc"}],
                                "approvers": [{"id": "a-1", "approval_link": "https://approve/abc"}],
                            }
                        ],
                        "meta": {"next_cursor": None},
                    }
                )
            ],
        )

        assert result.raised is None
        assert result.rows[0]["signers"][0].get("signature_link") is None
        assert result.rows[0]["signers"][0]["id"] == "s-1"
        assert result.rows[0]["approvers"][0].get("approval_link") is None
        assert result.rows[0]["approvers"][0]["id"] == "a-1"


def _hook(endpoint: str = "https://ph/webhook", **extra: Any) -> dict[str, Any]:
    return {"id": "wh-1", "endpoint": endpoint, **extra}


class TestWebhookManagement:
    def test_create_webhook_returns_signing_secret_as_extra_input(self) -> None:
        with scripted_network([ScriptedResponse(status=201, json={"id": "wh-1", "secret_key": "s" * 32})]) as network:
            result = create_webhook("key", "sandbox", "https://ph/webhook", mock.MagicMock())

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "s" * 32}
        body = network.requests_log[0].json()
        assert body["endpoint"] == "https://ph/webhook"
        assert body["sandbox"] is True
        assert body["subscribed_events"] == WEBHOOK_EVENTS

    def test_create_webhook_without_secret_marks_signing_secret_pending(self) -> None:
        with scripted_network([ScriptedResponse(status=201, json={"id": "wh-1"})]):
            result = create_webhook("key", "production", "https://ph/webhook", mock.MagicMock())

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]

    @pytest.mark.parametrize("status", [401, 403])
    def test_create_webhook_permission_error_is_actionable(self, status: int) -> None:
        with scripted_network([ScriptedResponse(status=status, json={})]):
            result = create_webhook("key", "production", "https://ph/webhook", mock.MagicMock())

        assert result.success is False
        assert result.error is not None and "full-access" in result.error

    def test_delete_webhook_is_a_noop_success_when_absent(self) -> None:
        with scripted_network([ScriptedResponse(json=[_hook("https://other/webhook")])]) as network:
            result = delete_webhook("key", "production", "https://ph/webhook", mock.MagicMock())

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET"]

    def test_delete_webhook_deletes_the_matching_subscription(self) -> None:
        with scripted_network([ScriptedResponse(json=[_hook()]), ScriptedResponse(status=204)]) as network:
            result = delete_webhook("key", "production", "https://ph/webhook", mock.MagicMock())

        assert result.success is True
        assert network.requests_log[1].method == "DELETE"
        assert network.requests_log[1].path.endswith("/webhooks/wh-1")

    def test_update_webhook_events_skips_patch_when_already_in_sync(self) -> None:
        with scripted_network([ScriptedResponse(json=[_hook(subscribed_events=sorted(WEBHOOK_EVENTS))])]) as network:
            result = update_webhook_events("key", "production", "https://ph/webhook", WEBHOOK_EVENTS, mock.MagicMock())

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET"]

    def test_update_webhook_events_patches_drifted_subscription(self) -> None:
        script = [
            ScriptedResponse(json=[_hook(subscribed_events=["signature_request.done"])]),
            ScriptedResponse(json={}),
        ]
        with scripted_network(script) as network:
            result = update_webhook_events("key", "production", "https://ph/webhook", WEBHOOK_EVENTS, mock.MagicMock())

        assert result.success is True
        assert network.requests_log[1].method == "PATCH"
        assert network.requests_log[1].json() == {"subscribed_events": WEBHOOK_EVENTS}
