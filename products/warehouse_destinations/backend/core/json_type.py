"""Arrow extension type for JSON strings."""

import re
import typing

import orjson
import pyarrow as pa

from posthog.temporal.common.logger import get_write_only_logger

LOGGER = get_write_only_logger(__name__)


class JsonScalar(pa.ExtensionScalar):
    """Represents a JSON binary string."""

    def as_py(self, *, maps_as_pydicts: typing.Literal["lossy", "strict"] | None = None) -> dict | None:
        """Try to convert value to Python representation.

        We attempt to decode the value returned by `as_py` as JSON. However, to do so safely we must
        ensure the value is a valid UTF-8 string. We try to take care of the following scenarios:
        * Unescaped whitespace characters (e.g. \n).
        * Unescaped surrogates without a pair.
        * Escaped surrogates without a pair.
        * Not a JSON document (we assume it's a string and quote it).

        If all else fails, we will log the offending value and re-raise the decoding error.
        """
        if self.value:
            value = self.value.as_py()

            if re.search("([\t\n\r\f\v])", value):
                value = value.encode("unicode-escape").decode("utf-8")

            if not value:
                return None

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

            if isinstance(value, str) and len(value) > 0 and not value.startswith("{") and not value.endswith("}"):
                # Handles non-valid JSON strings like `'"$set": "Something"'` by quoting them.
                value = f'"{value}"'

            json_bytes = value.encode("utf-8", "replace").decode("raw-unicode-escape").encode("utf-8", "replace")
            try:
                return orjson.loads(json_bytes)
            except orjson.JSONDecodeError:
                LOGGER.exception("Failed to decode with orjson: %s", value)
                raise

        else:
            return None


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
