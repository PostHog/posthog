from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import build_default_schemas
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sendgrid import (
    SendGridSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid import SendGridResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.settings import SENDGRID_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.source import SendGridSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.source"
_TRANSPORT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid"

ALL_ENDPOINTS = {
    "bounces",
    "blocks",
    "invalid_emails",
    "spam_reports",
    "global_unsubscribes",
    "stats",
    "unsubscribe_groups",
    "marketing_lists",
    "templates",
    "message_activity",
}
# Endpoints that sync incrementally, mapped to the cursor field they expose. Everything else is
# full refresh.
INCREMENTAL_FIELD_BY_ENDPOINT = {
    "bounces": "created",
    "blocks": "created",
    "invalid_emails": "created",
    "spam_reports": "created",
    "global_unsubscribes": "created",
    "stats": "date",
    "message_activity": "last_event_time",
}


def _config() -> SendGridSourceConfig:
    return SendGridSourceConfig(api_key="SG.test-key")


def _source_inputs(schema_name: str = "bounces", **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestSendGridSource:
    def test_source_type(self) -> None:
        assert SendGridSource().source_type == ExternalDataSourceType.SENDGRID

    def test_source_config_basics(self) -> None:
        config = SendGridSource().get_source_config
        assert config.label == "SendGrid"
        assert config.releaseStatus == "alpha"
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/sendgrid.png"

    def test_source_config_has_api_key_password_field(self) -> None:
        fields = SendGridSource().get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = SendGridSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == ALL_ENDPOINTS

    def test_incremental_endpoints_expose_their_cursor_field(self) -> None:
        schemas = {s.name: s for s in SendGridSource().get_schemas(_config(), team_id=1)}
        for name in ALL_ENDPOINTS:
            expected_field = INCREMENTAL_FIELD_BY_ENDPOINT.get(name)
            if expected_field is None:
                assert schemas[name].supports_incremental is False
                assert schemas[name].incremental_fields == []
            else:
                assert schemas[name].supports_incremental is True
                assert {f["field"] for f in schemas[name].incremental_fields} == {expected_field}
        # message_activity rows mutate in place as events land, so it syncs incrementally on
        # last_event_time but must never be offered as append (stale copies would pile up).
        assert schemas["message_activity"].supports_append is False
        for name in INCREMENTAL_FIELD_BY_ENDPOINT.keys() - {"message_activity"}:
            assert schemas[name].supports_append is True

    def test_message_activity_is_opt_in(self) -> None:
        # The add-on gate means most accounts 403 on this table: force-enabling it would fail
        # their first sync, so both the schema picker default and one-shot source creation must
        # leave it unselected.
        schemas = SendGridSource().get_schemas(_config(), team_id=1)
        defaults = {s.name: s.should_sync_default for s in schemas}
        assert defaults.pop("message_activity") is False
        assert all(defaults.values())

        by_name = {schema["name"]: schema for schema in build_default_schemas(schemas)}
        assert by_name["message_activity"] == {"name": "message_activity", "should_sync": False}
        assert by_name["bounces"]["should_sync"] is True

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = SendGridSource().get_schemas(_config(), team_id=1, names=["bounces", "templates"])
        assert {s.name for s in schemas} == {"bounces", "templates"}

    @pytest.mark.parametrize(
        ("status", "schema_name", "expected_ok", "expected_has_msg"),
        [
            (200, None, True, False),
            (200, "bounces", True, False),
            (401, None, False, True),
            (401, "bounces", False, True),
            # 403 = valid token, missing scope: accepted at source-create, rejected per-schema.
            (403, None, True, False),
            (403, "bounces", False, True),
            (None, None, False, True),
        ],
    )
    def test_validate_credentials(
        self, status: int | None, schema_name: str | None, expected_ok: bool, expected_has_msg: bool
    ) -> None:
        # A named schema probes its own endpoint; source-create probes `/scopes`.
        with (
            patch(f"{_SOURCE_MODULE}.get_status_code", return_value=status),
            patch(f"{_SOURCE_MODULE}.get_endpoint_status_code", return_value=status),
        ):
            ok, msg = SendGridSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        assert (msg is not None) is expected_has_msg

    @pytest.mark.parametrize(
        ("schema_name", "fragments"),
        [
            ("marketing_lists", ["marketing.read"]),
            ("message_activity", ["email_activity.read", "additional email activity history"]),
        ],
    )
    def test_per_schema_403_names_the_missing_scope(self, schema_name: str, fragments: list[str]) -> None:
        with patch(f"{_SOURCE_MODULE}.get_endpoint_status_code", return_value=403):
            _ok, msg = SendGridSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert msg is not None
        for fragment in fragments:
            assert fragment in msg

    @pytest.mark.parametrize(
        ("gated_endpoint", "scope"),
        [
            ("marketing_lists", "marketing.read"),
            # The add-on gate must stay per-table: a 403 on message_activity cannot make the
            # picker (or a sync) treat any other table as unreachable.
            ("message_activity", "email_activity.read"),
        ],
    )
    def test_get_endpoint_permissions_flags_only_the_unreadable_table(self, gated_endpoint: str, scope: str) -> None:
        # The bug this guards: with no per-table probe every table looked reachable, so a key without
        # the scope still got the gated table enabled, and the first sync hard-failed.
        def status_for(_api_key: str, config: Any) -> int:
            return 403 if config.name == gated_endpoint else 200

        with patch(f"{_TRANSPORT_MODULE}.get_endpoint_status_code", side_effect=status_for):
            permissions = SendGridSource().get_endpoint_permissions(_config(), team_id=1, endpoints=list(ALL_ENDPOINTS))

        gated_reason = permissions[gated_endpoint]
        assert gated_reason is not None
        assert scope in gated_reason
        assert {name: reason for name, reason in permissions.items() if reason is not None} == {
            gated_endpoint: gated_reason
        }

    @pytest.mark.parametrize("name", sorted(ALL_ENDPOINTS))
    def test_every_endpoint_declares_a_scope_to_name(self, name: str) -> None:
        # An endpoint added without one would render "missing the `` scope" at users.
        assert SENDGRID_ENDPOINTS[name].required_scope

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = SendGridSource().get_resumable_source_manager(_source_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SendGridResumeConfig

    def test_get_non_retryable_errors_covers_auth(self) -> None:
        errors = SendGridSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    @pytest.mark.parametrize(
        ("error_url", "expected_fragment"),
        [
            # A /v3/messages 403 also matches the bare-host key, so the add-on entry must come
            # first in insertion order or users get the generic scope advice for a paid add-on gap.
            ("https://api.sendgrid.com/v3/messages?limit=1000", "additional email activity history"),
            ("https://api.sendgrid.com/v3/suppression/bounces?limit=500", "cannot read this table"),
        ],
    )
    def test_403_friendly_message_matches_the_failing_endpoint(self, error_url: str, expected_fragment: str) -> None:
        # Mirrors the job finalizer: the first matching key in insertion order supplies the message.
        error = f"403 Client Error: Forbidden for url: {error_url}"
        errors = SendGridSource().get_non_retryable_errors()
        matches = [message for key, message in errors.items() if key.lower() in error.lower()]
        assert matches and matches[0] is not None
        assert expected_fragment in matches[0]

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _source_inputs(
            schema_name="bounces",
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
            incremental_field="created",
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.source.sendgrid_source"
        ) as mock_source:
            mock_source.return_value = MagicMock(spec=SourceResponse)
            SendGridSource().source_for_pipeline(_config(), manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "SG.test-key"
        assert kwargs["endpoint"] == "bounces"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000
        assert kwargs["incremental_field"] == "created"

    def test_source_for_pipeline_drops_cursor_when_not_incremental(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _source_inputs(
            schema_name="bounces",
            should_use_incremental_field=False,
            db_incremental_field_last_value=1700000000,
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.source.sendgrid_source"
        ) as mock_source:
            mock_source.return_value = MagicMock(spec=SourceResponse)
            SendGridSource().source_for_pipeline(_config(), manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
