import pickle
from typing import Any

import pytest

import pyarrow as pa

from products.warehouse_destinations.backend.core.json_type import JsonType


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
