"""Arrow extension type for JSON strings, and how to recognize any JSON extension type."""

import re
import typing

import orjson
import pyarrow as pa

from products.warehouse_destinations.backend.core.loggers import get_write_only_logger

# Callers build batches with their own extension class, so a JSON column is recognized by the
# extension name, never by class. "arrow.json" is the Arrow canonical JSON extension.
JSON_EXTENSION_NAMES = frozenset({"json", "arrow.json"})


def is_json_type(arrow_type: pa.DataType) -> bool:
    """Whether `arrow_type` is a JSON extension type, from any class."""
    return isinstance(arrow_type, pa.BaseExtensionType) and arrow_type.extension_name in JSON_EXTENSION_NAMES


def load_json(value: str | None) -> typing.Any:
    """Decode a JSON string, after repairing the faults we see in practice.

    The repairs cover:
    * Unescaped whitespace characters (e.g. \n).
    * Unescaped surrogates without a pair.
    * Escaped surrogates without a pair.
    * Not a JSON document (we assume it's a string and quote it).

    An empty or missing value is None. A value that no repair makes valid raises
    `orjson.JSONDecodeError`.
    """
    if not value:
        return None

    if re.search("([\t\n\r\f\v])", value):
        value = value.encode("unicode-escape").decode("utf-8")

    json_bytes = value.encode("utf-8", "replace")

    try:
        return orjson.loads(json_bytes)
    except orjson.JSONDecodeError:
        pass

    json_bytes = json_bytes.decode("raw-unicode-escape").encode("utf-8", "replace")

    try:
        return orjson.loads(json_bytes)
    except orjson.JSONDecodeError:
        pass

    if not value.startswith("{") and not value.endswith("}"):
        # Handles non-valid JSON strings like `'"$set": "Something"'` by quoting them.
        value = f'"{value}"'

    json_bytes = value.encode("utf-8", "replace").decode("raw-unicode-escape").encode("utf-8", "replace")
    try:
        return orjson.loads(json_bytes)
    except orjson.JSONDecodeError as err:
        # The value can hold customer data, so the log names only the error.
        get_write_only_logger(__name__).warning("Failed to decode a JSON value", error_type=type(err).__name__)
        raise


class JsonScalar(pa.ExtensionScalar):
    """Represents a JSON binary string."""

    def as_py(self, *, maps_as_pydicts: typing.Literal["lossy", "strict"] | None = None) -> typing.Any:
        """Decode the value as JSON with `load_json`."""
        if not self.value:
            return None
        return load_json(self.value.as_py())


class JsonType(pa.ExtensionType):
    """Type for JSON binary strings."""

    def __init__(self) -> None:
        super().__init__(pa.string(), "json")

    def __arrow_ext_serialize__(self) -> bytes:
        return b""

    def __hash__(self) -> int:
        return pa.DataType.__hash__(self)

    @classmethod
    def __arrow_ext_deserialize__(cls, storage_type: pa.DataType, serialized: bytes) -> "JsonType":
        return JsonType()

    def __arrow_ext_scalar_class__(self) -> type["JsonScalar"]:
        return JsonScalar
