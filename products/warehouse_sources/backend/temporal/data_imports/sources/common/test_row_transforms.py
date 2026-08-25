from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.row_transforms import coerce_fields_to_str


class TestCoerceFieldsToStr:
    @pytest.mark.parametrize(
        "item,fields,expected",
        [
            # int -> str: the type flip that breaks Arrow batch merging.
            ({"owner_id": 42}, ["owner_id"], {"owner_id": "42"}),
            # An already-string value is unchanged.
            ({"owner_id": "42"}, ["owner_id"], {"owner_id": "42"}),
            # None is preserved so the column stays nullable.
            ({"owner_id": None}, ["owner_id"], {"owner_id": None}),
            # A missing field is a no-op.
            ({"name": "x"}, ["owner_id"], {"name": "x"}),
            # Only named fields are touched.
            ({"owner_id": 1, "count": 2}, ["owner_id"], {"owner_id": "1", "count": 2}),
        ],
    )
    def test_coerce_fields_to_str(self, item: dict[str, Any], fields: list[str], expected: dict[str, Any]):
        assert coerce_fields_to_str(item, fields) == expected
