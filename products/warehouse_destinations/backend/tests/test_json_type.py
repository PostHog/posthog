import pickle
from typing import Any

import pytest

import pyarrow as pa

from products.warehouse_destinations.backend.core.json_type import JsonType, is_json_type


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("", None),
        ("null", None),
        ('{"a": 1}', {"a": 1}),
        ("[1, 2]", [1, 2]),
        ('{"a": "x\ny"}', {"a": "x\ny"}),
        ('{"a": "tab\there"}', {"a": "tab\there"}),
        ("hello", "hello"),
        ('{"a": "\\ud83d"}', {"a": "?"}),
        ('{"a": "\\ud83d\\ude00"}', {"a": "\N{GRINNING FACE}"}),
    ],
)
def test_json_type_decodes_values(value: str | None, expected: Any) -> None:
    array: Any = pa.array([value], type=pa.string()).cast(JsonType())

    assert array.to_pylist() == [expected]


def test_json_type_survives_pickle_round_trip() -> None:
    batch = pa.RecordBatch.from_arrays(
        [pa.array(['{"a": 1}', None], type=pa.string()).cast(JsonType())], names=["properties"]
    )

    restored = pickle.loads(pickle.dumps(batch))

    assert restored.schema.field("properties").type == JsonType()
    assert restored.column(0).to_pylist() == [{"a": 1}, None]


def test_json_type_instances_are_equal_and_hash_equal() -> None:
    assert JsonType() == JsonType()
    assert len({JsonType(), JsonType()}) == 1


class _OtherJsonType(pa.ExtensionType):
    def __init__(self) -> None:
        super().__init__(pa.string(), "json")

    def __arrow_ext_serialize__(self) -> bytes:
        return b""

    @classmethod
    def __arrow_ext_deserialize__(cls, storage_type: pa.DataType, serialized: bytes) -> "_OtherJsonType":
        return cls()


class _NotJsonType(pa.ExtensionType):
    def __init__(self) -> None:
        super().__init__(pa.string(), "geojson")

    def __arrow_ext_serialize__(self) -> bytes:
        return b""

    @classmethod
    def __arrow_ext_deserialize__(cls, storage_type: pa.DataType, serialized: bytes) -> "_NotJsonType":
        return cls()


@pytest.mark.parametrize(
    "arrow_type, expected",
    [
        (JsonType(), True),
        (_OtherJsonType(), True),
        (pa.json_(), True),
        (_NotJsonType(), False),
        (pa.string(), False),
        (pa.struct([("a", pa.int64())]), False),
    ],
)
def test_is_json_type_matches_by_extension_name(arrow_type: pa.DataType, expected: bool) -> None:
    assert is_json_type(arrow_type) is expected
