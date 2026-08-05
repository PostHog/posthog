"""Protobuf helpers for the tracked gRPC transport.

`message_byte_size` reports the serialized size of a protobuf message for
metrics (guarded — returns 0 for anything that isn't a message).

`message_to_scrubbed_dict` converts a message to a JSON-shaped dict for sample
capture. It walks the message via protobuf reflection so it can:

- replace `bytes` fields with a `<bytes:N>` placeholder rather than emitting
  them base64-encoded. A raw `bytes` field can carry bulk payloads — e.g.
  BigQuery Storage `ReadRowsResponse.arrow_record_batch.serialized_record_batch`
  holds the actual table rows — that scrubadub can't see inside, so we never
  serialize them into a sample;
- drop auth-bearing keys by name (`developer_token`, `refresh_token`, …);
- scrub string leaves via scrubadub.

Well-known `google.protobuf.*` types (Struct, Timestamp, wrappers, …) are
delegated to `MessageToDict`, which renders them canonically and carries no
bytes-of-concern.
"""

from __future__ import annotations

import logging
from typing import Any

from google.protobuf.descriptor import FieldDescriptor

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sample_scrub import (
    REDACT_FIELD_NAMES,
    scrub_value,
)

logger = logging.getLogger(__name__)

_REDACTED_KEY_VALUE = "REDACTED"


def message_byte_size(message: Any) -> int:
    """Return `message.ByteSize()` if `message` is a protobuf message, else 0.

    By the time a request reaches a client interceptor, gapic has already
    coerced any dict argument into a serialized protobuf message — but we guard
    anyway so a non-message value (or a mock in tests) never raises.
    """
    byte_size = getattr(message, "ByteSize", None)
    if byte_size is None:
        return 0
    try:
        return int(byte_size())
    except Exception:
        return 0


def _bytes_placeholder(value: bytes) -> str:
    try:
        return f"<bytes:{len(value)}>"
    except Exception:
        return "<bytes>"


def _convert_scalar_or_message(field: FieldDescriptor, value: Any) -> Any:
    if field.type == FieldDescriptor.TYPE_BYTES:
        return _bytes_placeholder(value)
    if field.type == FieldDescriptor.TYPE_MESSAGE:
        return _proto_to_safe_dict(value)
    if field.type == FieldDescriptor.TYPE_ENUM:
        enum_value = field.enum_type.values_by_number.get(value)
        return enum_value.name if enum_value is not None else value
    return value


def _convert_field(field: FieldDescriptor, value: Any) -> Any:
    if field.label == FieldDescriptor.LABEL_REPEATED:
        message_type = field.message_type
        if message_type is not None and message_type.GetOptions().map_entry:
            value_field = message_type.fields_by_name["value"]
            return {str(k): _convert_scalar_or_message(value_field, v) for k, v in value.items()}
        return [_convert_scalar_or_message(field, item) for item in value]
    return _convert_scalar_or_message(field, value)


def _proto_to_safe_dict(message: Any) -> Any:
    """Recursively convert a protobuf message to a dict, redacting bytes fields.

    Well-known `google.protobuf.*` types are delegated to `MessageToDict` — they
    render canonically and don't carry bulk-bytes fields we need to guard.
    """
    descriptor = getattr(message, "DESCRIPTOR", None)
    if descriptor is None:
        return message

    if descriptor.full_name.startswith("google.protobuf."):
        from google.protobuf.json_format import MessageToDict

        return MessageToDict(message, preserving_proto_field_name=True)

    result: dict[str, Any] = {}
    for field, value in message.ListFields():
        result[field.name] = _convert_field(field, value)
    return result


def _redact_keys(value: Any) -> Any:
    """Drop auth-bearing dict keys by name (developer_token, refresh_token, …)."""
    if isinstance(value, dict):
        return {
            k: (_REDACTED_KEY_VALUE if str(k).lower() in REDACT_FIELD_NAMES else _redact_keys(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_keys(item) for item in value]
    return value


def message_to_scrubbed_dict(message: Any) -> Any:
    """Convert a protobuf message to a scrubbed JSON-shaped dict.

    Falls back to scrubbing the raw value if `message` isn't a protobuf message
    (e.g. a dict request that gapic hadn't coerced yet). Bytes fields become a
    size placeholder, auth keys are dropped by name, and scrubadub runs over the
    remaining string leaves.
    """
    if hasattr(message, "DESCRIPTOR"):
        try:
            as_dict = _proto_to_safe_dict(message)
        except Exception:
            logger.debug("Failed to convert protobuf message to dict", exc_info=True)
            return "<proto_conversion_failed>"
    else:
        as_dict = message

    return scrub_value(_redact_keys(as_dict))
