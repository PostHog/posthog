from unittest.mock import Mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.errors import auth_non_retryable_errors
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
    incremental_field,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.types import IncrementalFieldType

ENDPOINTS = ("charges", "invoices", "events")
INCREMENTAL_FIELDS = {
    "charges": [incremental_field("updated_at")],
    "invoices": [incremental_field("created", IncrementalFieldType.Date)],
    # "events" intentionally has no incremental fields (full-refresh only)
}


class TestIncrementalField:
    def test_defaults_type_and_label_from_field(self) -> None:
        assert incremental_field("updated_at") == {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }

    def test_type_and_field_type_stay_in_sync(self) -> None:
        # The whole point of the helper: type == field_type, so they can't drift apart.
        f = incremental_field("created", IncrementalFieldType.Date, label="Created")
        assert f["label"] == "Created"
        assert f["type"] == f["field_type"] == IncrementalFieldType.Date


class TestBuildEndpointSchemas:
    def test_matches_the_hand_written_loop(self) -> None:
        # Equivalent to the loop copy-pasted across ~421 sources — output must be identical.
        expected = [
            SourceSchema(
                name=e,
                supports_incremental=INCREMENTAL_FIELDS.get(e) is not None,
                supports_append=INCREMENTAL_FIELDS.get(e) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(e, []),
            )
            for e in ENDPOINTS
        ]
        assert build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS) == expected

    def test_endpoint_without_incremental_fields_is_full_refresh(self) -> None:
        events = next(s for s in build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS) if s.name == "events")
        assert events.supports_incremental is False
        assert events.supports_append is False
        assert events.incremental_fields == []

    def test_names_filter_keeps_only_requested(self) -> None:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names=["invoices"])
        assert [s.name for s in schemas] == ["invoices"]

    def test_names_none_returns_all(self) -> None:
        assert len(build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names=None)) == len(ENDPOINTS)

    def test_append_only_disables_incremental_but_keeps_append(self) -> None:
        charges = next(
            s
            for s in build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, append_only={"charges"})
            if s.name == "charges"
        )
        assert charges.supports_incremental is False
        assert charges.supports_append is True

    def test_merge_only_disables_append_but_keeps_incremental(self) -> None:
        charges = next(
            s
            for s in build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, merge_only={"charges"})
            if s.name == "charges"
        )
        assert charges.supports_incremental is True
        assert charges.supports_append is False

    def test_per_endpoint_metadata_overrides(self) -> None:
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            descriptions={"charges": "A charge"},
            should_sync_default={"events": False},
            supports_webhooks={"invoices"},
        )
        by_name = {s.name: s for s in schemas}
        assert by_name["charges"].description == "A charge"
        assert by_name["events"].should_sync_default is False
        assert by_name["invoices"].supports_webhooks is True
        # unspecified endpoints keep the defaults
        assert by_name["charges"].should_sync_default is True
        assert by_name["charges"].supports_webhooks is False


class TestAuthNonRetryableErrors:
    def test_host_scoped_keys_match_requests_error_text(self) -> None:
        # Keys must be substrings of the real `raise_for_status()` message, or non-retryable
        # matching silently fails and bad-credential jobs retry forever.
        host = "https://api.example.com"
        errors = auth_non_retryable_errors(host, service="Example")
        assert f"401 Client Error: Unauthorized for url: {host}" in errors
        assert f"403 Client Error: Forbidden for url: {host}" in errors
        assert "Example" in errors[f"401 Client Error: Unauthorized for url: {host}"]

    def test_host_agnostic_default(self) -> None:
        errors = auth_non_retryable_errors()
        assert set(errors) == {"401 Client Error", "403 Client Error"}


class TestValidateViaProbe:
    @parameterized.expand([(200, True), (204, False), (401, False), (403, False), (500, False)])
    def test_status_mapping(self, status: int, expected_valid: bool) -> None:
        response = Mock(status_code=status)
        session = Mock()
        session.get.return_value = response
        valid, code = validate_via_probe(lambda: session, "https://api.example.com/ping")
        assert (valid, code) == (expected_valid, status)

    def test_custom_ok_statuses(self) -> None:
        session = Mock()
        session.get.return_value = Mock(status_code=204)
        valid, code = validate_via_probe(lambda: session, "https://x", ok_statuses=(200, 204))
        assert (valid, code) == (True, 204)

    def test_transport_error_maps_to_false_none(self) -> None:
        session = Mock()
        session.get.side_effect = requests.ConnectionError("boom")
        assert validate_via_probe(lambda: session, "https://x") == (False, None)

    def test_any_exception_maps_to_false_none(self) -> None:
        # A credential probe must never raise out of validate_credentials — matches the broad
        # `except Exception` the hand-rolled source probes use, so the helper is a drop-in.
        def boom() -> Mock:
            raise ValueError("session build failed")

        assert validate_via_probe(boom, "https://x") == (False, None)
