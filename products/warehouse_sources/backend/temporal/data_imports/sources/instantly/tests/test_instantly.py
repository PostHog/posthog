from collections.abc import Iterable
from datetime import UTC, datetime

import pytest
from unittest import mock

from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.instantly.instantly import (
    WEBHOOK_PLAN_ERROR,
    WEBHOOK_SECRET_HEADER,
    InstantlyCursorPaginator,
    InstantlyResumeConfig,
    InstantlyThrottledCursorPaginator,
    _format_incremental_timestamp,
    _webhook_events_table_transformer,
    create_webhook,
    delete_webhook,
    get_endpoint_permissions,
    get_resource,
    instantly_source,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.instantly.instantly"


def _response(body=None, status_code=200):
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = body
    return response


def _endpoint_config(resource) -> dict:
    endpoint = resource["endpoint"]
    assert isinstance(endpoint, dict)
    return endpoint


class TestInstantly:
    def test_paginator_follows_next_starting_after_in_query(self):
        paginator = InstantlyCursorPaginator()
        request = Request(method="GET", url="https://api.instantly.ai/api/v2/campaigns", params={"limit": 100})
        items = [{"id": "a"}]

        paginator.update_state(_response({"items": items, "next_starting_after": "cur-1"}), items)
        paginator.update_request(request)

        assert paginator.has_next_page
        assert request.params["starting_after"] == "cur-1"

    def test_paginator_follows_cursor_in_json_body_for_post_endpoints(self):
        paginator = InstantlyCursorPaginator(use_json_body=True)
        request = Request(method="POST", url="https://api.instantly.ai/api/v2/leads/list", json={"limit": 100})
        items = [{"id": "a"}]

        paginator.update_state(_response({"items": items, "next_starting_after": "cur-1"}), items)
        paginator.update_request(request)

        assert request.json["starting_after"] == "cur-1"
        assert "starting_after" not in (request.params or {})

    @pytest.mark.parametrize(
        "body,data",
        [
            # Empty page, even with a cursor still present.
            ({"items": [], "next_starting_after": "cur-1"}, []),
            # No cursor in the body.
            ({"items": [{"id": "a"}]}, [{"id": "a"}]),
        ],
    )
    def test_paginator_stops(self, body, data):
        paginator = InstantlyCursorPaginator()

        paginator.update_state(_response(body), data)

        assert not paginator.has_next_page

    def test_paginator_stops_on_non_advancing_cursor(self):
        # If the API echoed the same cursor forever we'd otherwise refetch the same page endlessly.
        paginator = InstantlyCursorPaginator()
        items = [{"id": "a"}]

        paginator.update_state(_response({"items": items, "next_starting_after": "cur-1"}), items)
        assert paginator.has_next_page
        paginator.update_state(_response({"items": items, "next_starting_after": "cur-1"}), items)

        assert not paginator.has_next_page

    def test_paginator_resume_state_roundtrip(self):
        paginator = InstantlyCursorPaginator()
        items = [{"id": "a"}]
        paginator.update_state(_response({"items": items, "next_starting_after": "cur-9"}), items)

        state = paginator.get_resume_state()
        assert state == {"cursor": "cur-9"}

        resumed = InstantlyCursorPaginator()
        resumed.set_resume_state(state)
        request = Request(method="GET", url="https://api.instantly.ai/api/v2/campaigns", params={})
        resumed.init_request(request)

        assert request.params["starting_after"] == "cur-9"

    @mock.patch(f"{MODULE}.time.sleep")
    def test_throttled_paginator_waits_only_between_pages(self, mock_sleep):
        paginator = InstantlyThrottledCursorPaginator(3.0)
        request = Request(method="GET", url="https://api.instantly.ai/api/v2/emails", params={})
        items = [{"id": "a"}]

        paginator.update_state(_response({"items": items, "next_starting_after": "cur-1"}), items)
        paginator.update_request(request)
        assert mock_sleep.call_count == 1

        paginator.update_state(_response({"items": items}), items)
        paginator.update_request(request)
        assert mock_sleep.call_count == 1

    def test_emails_resource_sends_incremental_filter_only_when_enabled(self):
        incremental = get_resource("emails", True)
        full_refresh = get_resource("emails", False)

        incremental_params = _endpoint_config(incremental)["params"]
        assert incremental_params["min_timestamp_created"]["type"] == "incremental"
        assert incremental_params["min_timestamp_created"]["cursor_path"] == "timestamp_created"
        # sort_order=asc keeps arrival order matching sort_mode="asc" for watermark checkpointing.
        assert incremental_params["sort_order"] == "asc"
        assert incremental["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

        assert "min_timestamp_created" not in _endpoint_config(full_refresh)["params"]
        assert full_refresh["write_disposition"] == "replace"

    def test_leads_resource_is_post_with_json_body(self):
        endpoint = _endpoint_config(get_resource("leads", False))

        assert endpoint["method"] == "POST"
        assert endpoint["json"] == {"limit": 100}
        assert "params" not in endpoint

    def test_analytics_resources_are_single_page_bare_arrays(self):
        endpoint = _endpoint_config(get_resource("campaign_analytics", False))

        assert endpoint["paginator"] == "single_page"
        assert "data_selector" not in endpoint

    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05+00:00"),
            ("2026-01-02T03:04:05.000Z", "2026-01-02T03:04:05.000Z"),
        ],
    )
    def test_format_incremental_timestamp(self, value, expected):
        assert _format_incremental_timestamp(value) == expected

    @pytest.mark.parametrize(
        "endpoint,expected_primary_keys,expected_partition_mode",
        [
            ("campaigns", ["id"], "datetime"),
            ("accounts", ["email"], "datetime"),
            ("campaign_analytics", ["campaign_id"], None),
        ],
    )
    @mock.patch(f"{MODULE}.rest_api_resource")
    def test_source_response_per_endpoint(
        self, mock_resource, endpoint, expected_primary_keys, expected_partition_mode
    ):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        response = instantly_source(
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
        )

        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.partition_mode == expected_partition_mode

    @mock.patch(f"{MODULE}.rest_api_resource")
    def test_resume_state_seeds_paginator_and_saves_after_batches(self, mock_resource):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = InstantlyResumeConfig(cursor="saved-cursor")

        instantly_source(
            api_key="key",
            endpoint="campaigns",
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
        )

        kwargs = mock_resource.call_args.kwargs
        assert kwargs["initial_paginator_state"] == {"cursor": "saved-cursor"}

        save_checkpoint = kwargs["resume_hook"]
        save_checkpoint({"cursor": "next-cursor"})
        manager.save_state.assert_called_once_with(InstantlyResumeConfig(cursor="next-cursor"))

        # A None/exhausted state must not clobber the checkpoint.
        save_checkpoint(None)
        assert manager.save_state.call_count == 1

    def test_webhook_events_source_is_webhook_only_and_empty_without_webhook(self):
        webhook_manager = mock.MagicMock()
        webhook_manager.webhook_enabled = mock.AsyncMock(return_value=False)

        response = instantly_source(
            api_key="key",
            endpoint="webhook_events",
            team_id=1,
            job_id="job",
            resumable_source_manager=mock.MagicMock(),
            webhook_source_manager=webhook_manager,
        )

        assert response.webhook_only is True
        assert response.primary_keys == ["event_id"]
        items = response.items()
        assert isinstance(items, Iterable)
        assert list(items) == []

    def test_webhook_events_transformer_stamps_event_id_and_dedupes(self):
        payload = {"event_type": "email_sent", "lead_email": "a@b.com", "timestamp": "2026-01-01T00:00:00Z"}
        other = {"event_type": "reply_received", "lead_email": "a@b.com", "timestamp": "2026-01-02T00:00:00Z"}
        table = table_from_py_list([dict(payload), dict(payload), dict(other)])

        result = _webhook_events_table_transformer(table)
        rows = result.to_pylist()

        assert len(rows) == 2
        assert all(row["event_id"] for row in rows)
        # Redelivered payloads hash to the same id so delta merge collapses them across syncs too.
        rerun = _webhook_events_table_transformer(table_from_py_list([dict(payload)])).to_pylist()
        assert rerun[0]["event_id"] == rows[0]["event_id"]

    @pytest.mark.parametrize(
        "status_code,schema_name,expected_valid",
        [
            (200, None, True),
            (401, None, False),
            (402, None, False),
            # A 403 at source-create means a valid but scoped key — must not block the source.
            (403, None, True),
            (403, "emails", False),
            (200, "emails", True),
        ],
    )
    @mock.patch(f"{MODULE}._probe_endpoint")
    @mock.patch(f"{MODULE}._make_session")
    def test_validate_credentials_status_mapping(
        self, mock_session, mock_probe, status_code, schema_name, expected_valid
    ):
        mock_probe.return_value = _response({"message": "Forbidden"}, status_code=status_code)

        valid, error = validate_credentials("key", schema_name)

        assert valid is expected_valid
        assert (error is None) is expected_valid

    @mock.patch(f"{MODULE}._probe_endpoint")
    @mock.patch(f"{MODULE}._make_session")
    def test_get_endpoint_permissions_flags_only_real_denials(self, mock_session, mock_probe):
        def probe(session, endpoint):
            if endpoint == "emails":
                return _response({"message": "Missing scope: emails:read"}, status_code=403)
            if endpoint == "leads":
                raise ConnectionError("boom")
            return _response({"items": []}, status_code=200)

        mock_probe.side_effect = probe

        permissions = get_endpoint_permissions("key", ["campaigns", "emails", "leads"])

        assert permissions["campaigns"] is None
        assert permissions["emails"] == "Missing scope: emails:read"
        # A network blip is not a permission denial.
        assert permissions["leads"] is None

    @mock.patch(f"{MODULE}._find_webhook_by_url", return_value=None)
    @mock.patch(f"{MODULE}._make_session")
    def test_create_webhook_subscribes_all_events_with_secret_header(self, mock_session, mock_find):
        session = mock_session.return_value
        session.post.return_value = _response({"id": "wh-1"}, status_code=200)

        result = create_webhook("key", "https://ph/webhook", mock.MagicMock())

        assert result.success is True
        body = session.post.call_args.kwargs["json"]
        assert body["target_hook_url"] == "https://ph/webhook"
        assert body["event_type"] == "all_events"
        secret = body["headers"][WEBHOOK_SECRET_HEADER]
        assert result.extra_inputs == {"signing_secret": secret}

    @mock.patch(f"{MODULE}._find_webhook_by_url", return_value={"id": "wh-1", "target_hook_url": "https://ph/webhook"})
    @mock.patch(f"{MODULE}._make_session")
    def test_create_webhook_reconciles_existing_webhook_instead_of_duplicating(self, mock_session, mock_find):
        session = mock_session.return_value
        session.patch.return_value = _response({"id": "wh-1"}, status_code=200)

        result = create_webhook("key", "https://ph/webhook", mock.MagicMock())

        assert result.success is True
        session.post.assert_not_called()
        assert "/webhooks/wh-1" in session.patch.call_args.args[0]

    @mock.patch(f"{MODULE}._find_webhook_by_url", return_value=None)
    @mock.patch(f"{MODULE}._make_session")
    def test_create_webhook_surfaces_plan_gating(self, mock_session, mock_find):
        session = mock_session.return_value
        session.post.return_value = _response({"message": "Workspace does not have an active paid plan"}, 402)

        result = create_webhook("key", "https://ph/webhook", mock.MagicMock())

        assert result.success is False
        assert result.error == WEBHOOK_PLAN_ERROR

    @mock.patch(f"{MODULE}._find_webhook_by_url")
    @mock.patch(f"{MODULE}._make_session")
    def test_delete_webhook_is_idempotent(self, mock_session, mock_find):
        session = mock_session.return_value
        mock_find.return_value = None

        assert delete_webhook("key", "https://ph/webhook", mock.MagicMock()).success is True
        session.delete.assert_not_called()

        mock_find.return_value = {"id": "wh-1"}
        session.delete.return_value = _response(None, status_code=200)
        assert delete_webhook("key", "https://ph/webhook", mock.MagicMock()).success is True
        assert "/webhooks/wh-1" in session.delete.call_args.args[0]
