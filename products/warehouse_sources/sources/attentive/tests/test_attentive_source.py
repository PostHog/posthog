from datetime import UTC, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.attentive._config import AttentiveSourceConfig
from products.warehouse_sources.sources.attentive.api_client import (
    API_KEY_REJECTED_ERROR,
    SEGMENTS_PERMISSION_ERROR,
    AttentiveResumeConfig,
)
from products.warehouse_sources.sources.attentive.constants import RESOURCE_TO_ATTENTIVE_EVENT_TYPE
from products.warehouse_sources.sources.attentive.source import AttentiveSource, _webhook_table_transformer
from products.warehouse_sources.sources.sdk.internals import table_from_py_list
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver


class TestWebhookTableTransformer:
    def test_adds_stable_event_id_and_created_at(self):
        row = {"type": "sms.sent", "timestamp": 1632945178104, "subscriber": {"phone": "+15555555555"}}
        table = table_from_py_list([row])

        result = _webhook_table_transformer(table).to_pylist()

        assert len(result) == 1
        assert result[0]["created_at"] == 1632945178
        assert result[0]["event_id"]
        # Identical retried deliveries hash to the same event_id.
        rerun = _webhook_table_transformer(table_from_py_list([row])).to_pylist()
        assert rerun[0]["event_id"] == result[0]["event_id"]

    def test_different_payloads_get_different_event_ids(self):
        rows = [
            {"type": "sms.sent", "timestamp": 1632945178104},
            {"type": "sms.sent", "timestamp": 1632945178105},
        ]
        result = _webhook_table_transformer(table_from_py_list(rows)).to_pylist()
        assert result[0]["event_id"] != result[1]["event_id"]

    def test_missing_timestamp_omits_created_at(self):
        result = _webhook_table_transformer(table_from_py_list([{"type": "sms.sent"}])).to_pylist()
        assert result[0].get("created_at") is None


class TestAttentiveSource:
    def setup_method(self):
        self.source = AttentiveSource()
        self.team_id = 123
        self.config = AttentiveSourceConfig(api_key="key")

    def test_webhook_template_registered(self):
        template = self.source.webhook_template
        assert template is not None
        assert template.id == "template-warehouse-source-attentive"
        assert template.type == "warehouse_source_webhook"

    def test_webhook_resource_map(self):
        assert self.source.webhook_resource_map == RESOURCE_TO_ATTENTIVE_EVENT_TYPE

    def test_get_desired_webhook_events_maps_eligible_schemas(self):
        events = self.source.get_desired_webhook_events(self.config, ["sms_sent", "email_opened", "not_a_schema"])
        assert events == ["sms.sent", "email.opened"]

    @mock.patch("products.warehouse_sources.sources.attentive.source.api_client.create_webhook")
    def test_create_webhook_subscribes_all_event_types(self, mock_create):
        self.source.create_webhook(self.config, "https://ph.example/webhook", self.team_id)

        mock_create.assert_called_once_with(
            api_key="key",
            webhook_url="https://ph.example/webhook",
            resource_names=list(RESOURCE_TO_ATTENTIVE_EVENT_TYPE.keys()),
        )

    @mock.patch("products.warehouse_sources.sources.attentive.source.api_client.enable_webhook")
    def test_webhook_inputs_updated_enables_once_secret_provided(self, mock_enable):
        mock_enable.return_value = (True, None)

        ok, _ = self.source.webhook_inputs_updated(
            self.config, "https://ph.example/webhook", self.team_id, {"signing_secret": "sek"}
        )

        assert ok is True
        mock_enable.assert_called_once_with("key", "https://ph.example/webhook")

    @mock.patch("products.warehouse_sources.sources.attentive.source.api_client.enable_webhook")
    def test_webhook_inputs_updated_noop_without_secret(self, mock_enable):
        ok, _ = self.source.webhook_inputs_updated(self.config, "https://ph.example/webhook", self.team_id, {})

        assert ok is True
        mock_enable.assert_not_called()

    @mock.patch("products.warehouse_sources.sources.attentive.source.async_to_sync")
    def test_webhook_schema_without_live_webhook_yields_nothing(self, mock_async_to_sync):
        mock_async_to_sync.return_value = mock.MagicMock(return_value=False)

        result = SourceDriver(self.source, self.config).run("sms_sent", [])

        assert result.raised is None
        assert result.rows == []
        assert result.requests == []
        assert result.response is not None
        assert result.response.webhook_only is True
        assert result.response.supports_resume is False
        assert result.response.primary_keys == ["event_id"]

    @parameterized.expand([("segments", True), ("sms_sent", False), ("email_opened", False), (None, False)])
    def test_resume_budget_covers_only_the_segments_table(self, schema_name, expected):
        for incremental_or_append in (True, False):
            covered = self.source.resume_covers_run(
                incremental_or_append=incremental_or_append, schema_name=schema_name
            )
            assert covered is expected


def _segment(external_id: str) -> dict[str, Any]:
    return {
        "externalId": external_id,
        "name": f"Segment {external_id}",
        "description": "Invented test segment",
        "created": "2026-01-05T10:00:00Z",
        "updated": "2026-02-05T10:00:00Z",
    }


def _page(external_ids: list[str], cursor: str | None, has_more: bool | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"segments": [_segment(i) for i in external_ids], "cursor": cursor}
    body["hasMore"] = cursor is not None if has_more is None else has_more
    return ScriptedResponse(json=body)


class TestAttentiveSegments:
    def setup_method(self):
        self.driver = SourceDriver(AttentiveSource(), AttentiveSourceConfig(api_key="key"))

    @parameterized.expand(
        [
            ("full_refresh", {}, None),
            (
                "incremental",
                {
                    "incremental_field": "updated",
                    "db_incremental_field_last_value": datetime(2026, 3, 1, 12, 30, tzinfo=UTC),
                },
                "2026-03-01T12:30:00Z",
            ),
            (
                "incremental_first_run",
                {"incremental_field": "updated", "db_incremental_field_last_value": None},
                None,
            ),
        ]
    )
    def test_walks_every_page_with_the_cursor(self, _name, inputs, expected_updated_since):
        result = self.driver.run(
            "segments",
            [_page(["seg_1", "seg_2"], "c2"), _page(["seg_3"], "c3"), _page(["seg_4"], None)],
            **inputs,
        )

        assert result.raised is None
        assert [row["externalId"] for row in result.rows] == ["seg_1", "seg_2", "seg_3", "seg_4"]
        assert result.paths == ["/v2/segments"] * 3
        assert result.params("cursor") == [None, "c2", "c3"]
        assert result.params("limit") == ["1000"] * 3
        assert result.params("updatedSince") == [expected_updated_since] * 3
        assert result.requests[0].headers["authorization"] == "Bearer key"
        assert result.response is not None
        assert result.response.primary_keys == ["externalId"]
        assert result.response.webhook_only is False

    @parameterized.expand(
        [
            ("full_refresh_walk", None, {}),
            (
                "incremental_walk_with_advanced_watermark",
                "2026-01-01T00:00:00Z",
                {
                    "incremental_field": "updated",
                    "db_incremental_field_last_value": datetime(2026, 3, 1, 12, 30, tzinfo=UTC),
                },
            ),
        ]
    )
    def test_resumes_with_the_cursor_and_filter_of_the_interrupted_walk(self, _name, saved_updated_since, inputs):
        result = self.driver.run(
            "segments",
            [_page(["seg_3"], None)],
            resume_state=AttentiveResumeConfig(cursor="c3", updated_since=saved_updated_since),
            **inputs,
        )

        assert result.raised is None
        assert result.params("cursor") == ["c3"]
        assert result.params("updatedSince") == [saved_updated_since]
        assert [row["externalId"] for row in result.rows] == ["seg_3"]

    def test_cursor_of_a_written_page_survives_a_failed_next_page(self):
        result = self.driver.run(
            "segments",
            [_page(["seg_1"], "c2"), ScriptedResponse(status=400)],
            incremental_field="updated",
            db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
        )

        assert result.raised is not None
        assert [row["externalId"] for row in result.rows] == ["seg_1"]
        assert result.committed_states == [AttentiveResumeConfig(cursor="c2", updated_since="2026-03-01T00:00:00Z")]

    @parameterized.expand(
        [
            ("has_more_false_with_cursor", _page(["seg_1"], "stale", has_more=False)),
            ("empty_last_page", _page([], None)),
            ("missing_segments_key", ScriptedResponse(json={"hasMore": False})),
        ]
    )
    def test_stops_on_the_terminal_page(self, _name, terminal):
        result = self.driver.run("segments", [terminal])

        assert result.raised is None
        assert len(result.requests) == 1

    def test_empty_page_with_more_results_keeps_paging(self):
        result = self.driver.run("segments", [_page([], "c2"), _page(["seg_2"], None)])

        assert result.raised is None
        assert result.params("cursor") == [None, "c2"]
        assert [row["externalId"] for row in result.rows] == ["seg_2"]

    @parameterized.expand(
        [
            (403, SEGMENTS_PERMISSION_ERROR, None),
            (401, "401 Client Error: Unauthorized", API_KEY_REJECTED_ERROR),
        ]
    )
    def test_maps_auth_errors_to_non_retryable_messages(self, status, error_fragment, friendly):
        result = self.driver.run("segments", [ScriptedResponse(status=status)])

        assert result.raised is not None
        assert error_fragment in str(result.raised)
        non_retryable = AttentiveSource().get_non_retryable_errors()
        matched = [message for pattern, message in non_retryable.items() if pattern in str(result.raised)]
        assert matched == [friendly]
