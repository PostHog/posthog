from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import orjson
from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.settings import (
    SIGNATURE_REQUEST_SOURCES,
    WEBHOOK_EVENTS,
    YOUSIGN_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign import (
    YousignResumeConfig,
    _cursor_paginator,
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


def _resp(payload: Any, status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.json.return_value = payload
    resp.content = b"x"
    return resp


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

    def test_incremental_defaults_to_created_at(self) -> None:
        resource = get_resource(YOUSIGN_ENDPOINTS["signature_requests"], True, None)
        assert "created_at[after]" in _endpoint_params(resource)

    @pytest.mark.parametrize("endpoint, field", [("signature_requests", "updated_at"), ("contacts", "created_at")])
    def test_incremental_rejects_unsupported_fields(self, endpoint: str, field: str) -> None:
        with pytest.raises(ValueError, match="does not support incremental field"):
            get_resource(YOUSIGN_ENDPOINTS[endpoint], True, field)


class TestCursorPaginator:
    def test_follows_meta_next_cursor_until_null(self) -> None:
        paginator = _cursor_paginator()

        paginator.update_state(_resp({"data": [{"id": "a"}], "meta": {"next_cursor": "tok1"}}))
        assert paginator.has_next_page
        request = Request(method="GET", url="https://api.yousign.app/v3/signature_requests", params={})
        paginator.update_request(request)
        assert request.params["after"] == "tok1"

        paginator.update_state(_resp({"data": [{"id": "b"}], "meta": {"next_cursor": None}}))
        assert not paginator.has_next_page

    def test_resume_state_roundtrip(self) -> None:
        paginator = _cursor_paginator()
        paginator.update_state(_resp({"data": [], "meta": {"next_cursor": "tok2"}}))
        state = paginator.get_resume_state()
        assert state == {"cursor": "tok2"}

        resumed = _cursor_paginator()
        resumed.set_resume_state(state)
        request = Request(method="GET", url="https://api.yousign.app/v3/contacts", params={})
        resumed.init_request(request)
        assert request.params["after"] == "tok2"


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
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.make_tracked_session")
    def test_status_mapping(
        self, mock_session: mock.MagicMock, status: int, schema_name: str | None, expected_valid: bool
    ) -> None:
        mock_session.return_value.get.return_value = _resp({}, status=status)
        valid, _ = validate_credentials("key", "production", schema_name)
        assert valid is expected_valid

    @pytest.mark.parametrize(
        "environment, expected_host",
        [("production", "https://api.yousign.app/v3"), ("sandbox", "https://api-sandbox.yousign.app/v3")],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.make_tracked_session")
    def test_probes_the_environment_host(
        self, mock_session: mock.MagicMock, environment: str, expected_host: str
    ) -> None:
        mock_session.return_value.get.return_value = _resp({}, status=200)
        validate_credentials("key", environment)
        assert mock_session.return_value.get.call_args.args[0] == f"{expected_host}/users"


class TestYousignSourceResponse:
    @pytest.mark.parametrize("endpoint", list(YOUSIGN_ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        response = yousign_source(
            api_key="key",
            environment="production",
            endpoint=endpoint,
            team_id=TEAM_ID,
            job_id=JOB_ID,
            resumable_source_manager=_make_manager(),
        )
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

    @pytest.mark.parametrize("endpoint", ["signers", "documents"])
    def test_fanout_children_key_on_parent_id(self, endpoint: str) -> None:
        # Fan-out children aggregate rows across every signature request; without the parent id
        # in the key, duplicate ids would multi-match on every merge.
        response = yousign_source(
            api_key="key",
            environment="production",
            endpoint=endpoint,
            team_id=TEAM_ID,
            job_id=JOB_ID,
            resumable_source_manager=_make_manager(),
        )
        assert response.primary_keys == ["signature_request_id", "id"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.rest_api_resource")
    def test_resumes_from_saved_cursor(self, mock_rest_api_resource: mock.MagicMock) -> None:
        manager = _make_manager(YousignResumeConfig(cursor="tok"))
        yousign_source(
            api_key="key",
            environment="production",
            endpoint="signature_requests",
            team_id=TEAM_ID,
            job_id=JOB_ID,
            resumable_source_manager=manager,
        )
        kwargs = mock_rest_api_resource.call_args.kwargs
        assert kwargs["initial_paginator_state"] == {"cursor": "tok"}

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.rest_api_resource")
    def test_checkpoint_saves_only_when_a_next_page_exists(self, mock_rest_api_resource: mock.MagicMock) -> None:
        manager = _make_manager()
        yousign_source(
            api_key="key",
            environment="production",
            endpoint="signature_requests",
            team_id=TEAM_ID,
            job_id=JOB_ID,
            resumable_source_manager=manager,
        )
        save_checkpoint = mock_rest_api_resource.call_args.kwargs["resume_hook"]

        save_checkpoint({"cursor": "tok3"})
        manager.save_state.assert_called_once_with(YousignResumeConfig(cursor="tok3"))

        manager.save_state.reset_mock()
        save_checkpoint(None)
        save_checkpoint({"cursor": None})
        manager.save_state.assert_not_called()

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

    def test_webhook_manager_not_consulted_for_non_webhook_schema(self) -> None:
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=True)

        yousign_source(
            api_key="key",
            environment="production",
            endpoint="contacts",
            team_id=TEAM_ID,
            job_id=JOB_ID,
            resumable_source_manager=_make_manager(),
            webhook_source_manager=webhook_manager,
        )

        webhook_manager.webhook_enabled.assert_not_called()


class TestWebhookTableTransformer:
    def _envelope(self, request_id: str, status: str, event_time: str) -> dict[str, Any]:
        return {
            "event_id": f"evt-{request_id}-{event_time}",
            "event_name": "signature_request.activated",
            "event_time": event_time,
            "sandbox": False,
            "data": {"signature_request": {"id": request_id, "status": status, "name": "Contract"}},
        }

    def test_reshapes_envelopes_and_keeps_latest_event_per_id(self) -> None:
        table = table_from_py_list(
            [
                self._envelope("sr-1", "ongoing", "100"),
                self._envelope("sr-1", "done", "200"),
                self._envelope("sr-2", "ongoing", "150"),
            ]
        )
        rows = make_webhook_table_transformer()(table).to_pylist()
        by_id = {row["id"]: row for row in rows}
        assert set(by_id) == {"sr-1", "sr-2"}
        assert by_id["sr-1"]["status"] == "done"
        # Envelope keys must not leak into the table — the rows merge with pulled API rows.
        assert "event_name" not in by_id["sr-1"]

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


def _static_resource(rows: list[dict[str, Any]]) -> Resource:
    return Resource(lambda: iter([rows]), name="r", hints={})


def _flatten(response: Any) -> list[dict[str, Any]]:
    return [row for page in cast(Iterable[Any], response.items()) for row in page]


class TestSignerCapabilityStripping:
    """`signature_link` (and other capability fields) must never reach the warehouse on any path."""

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.build_dependent_resource"
    )
    def test_signers_fanout_strips_signature_link(self, mock_build: mock.MagicMock) -> None:
        mock_build.return_value = _static_resource(
            [{"signature_request_id": "sr-1", "id": "s-1", "status": "signed", "signature_link": "https://sign/abc"}]
        )
        response = yousign_source(
            api_key="key",
            environment="production",
            endpoint="signers",
            team_id=TEAM_ID,
            job_id=JOB_ID,
            resumable_source_manager=_make_manager(),
        )
        rows = _flatten(response)
        assert rows[0].get("signature_link") is None
        assert rows[0]["id"] == "s-1"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.rest_api_resource")
    def test_signature_requests_strips_embedded_signer_links(self, mock_rest: mock.MagicMock) -> None:
        mock_rest.return_value = _static_resource(
            [{"id": "sr-1", "signers": [{"id": "s-1", "signature_link": "https://sign/abc"}]}]
        )
        response = yousign_source(
            api_key="key",
            environment="production",
            endpoint="signature_requests",
            team_id=TEAM_ID,
            job_id=JOB_ID,
            resumable_source_manager=_make_manager(),
        )
        rows = _flatten(response)
        assert rows[0]["signers"][0].get("signature_link") is None
        assert rows[0]["signers"][0]["id"] == "s-1"


class TestWebhookManagement:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.make_tracked_session")
    def test_create_webhook_returns_signing_secret_as_extra_input(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _resp({"id": "wh-1", "secret_key": "s" * 32}, status=201)
        result = create_webhook("key", "sandbox", "https://ph/webhook", mock.MagicMock())

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "s" * 32}
        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert body["endpoint"] == "https://ph/webhook"
        assert body["sandbox"] is True
        assert body["subscribed_events"] == WEBHOOK_EVENTS

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.make_tracked_session")
    def test_create_webhook_without_secret_marks_signing_secret_pending(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _resp({"id": "wh-1"}, status=201)
        result = create_webhook("key", "production", "https://ph/webhook", mock.MagicMock())

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]

    @pytest.mark.parametrize("status", [401, 403])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.make_tracked_session")
    def test_create_webhook_permission_error_is_actionable(self, mock_session: mock.MagicMock, status: int) -> None:
        mock_session.return_value.post.return_value = _resp({}, status=status)
        result = create_webhook("key", "production", "https://ph/webhook", mock.MagicMock())

        assert result.success is False
        assert result.error is not None and "full-access" in result.error

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.make_tracked_session")
    def test_delete_webhook_is_a_noop_success_when_absent(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _resp([{"id": "wh-1", "endpoint": "https://other/webhook"}])
        result = delete_webhook("key", "production", "https://ph/webhook", mock.MagicMock())

        assert result.success is True
        mock_session.return_value.delete.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.make_tracked_session")
    def test_delete_webhook_deletes_the_matching_subscription(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _resp([{"id": "wh-1", "endpoint": "https://ph/webhook"}])
        mock_session.return_value.delete.return_value = _resp({}, status=204)
        result = delete_webhook("key", "production", "https://ph/webhook", mock.MagicMock())

        assert result.success is True
        assert mock_session.return_value.delete.call_args.args[0].endswith("/webhooks/wh-1")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.make_tracked_session")
    def test_update_webhook_events_skips_patch_when_already_in_sync(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _resp(
            [{"id": "wh-1", "endpoint": "https://ph/webhook", "subscribed_events": sorted(WEBHOOK_EVENTS)}]
        )
        result = update_webhook_events("key", "production", "https://ph/webhook", WEBHOOK_EVENTS, mock.MagicMock())

        assert result.success is True
        mock_session.return_value.patch.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign.make_tracked_session")
    def test_update_webhook_events_patches_drifted_subscription(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _resp(
            [{"id": "wh-1", "endpoint": "https://ph/webhook", "subscribed_events": ["signature_request.done"]}]
        )
        mock_session.return_value.patch.return_value = _resp({}, status=200)
        result = update_webhook_events("key", "production", "https://ph/webhook", WEBHOOK_EVENTS, mock.MagicMock())

        assert result.success is True
        patch_kwargs = mock_session.return_value.patch.call_args.kwargs
        assert patch_kwargs["json"] == {"subscribed_events": WEBHOOK_EVENTS}
