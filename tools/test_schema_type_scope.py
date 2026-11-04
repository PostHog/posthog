from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

import unittest

import schema_type_scope as scope
from parameterized import parameterized

ENUMS = textwrap.dedent(
    """
    from enum import StrEnum


    class Interval(StrEnum):
        DAY = "day"
        WEEK = "week"


    class Unit(StrEnum):
        SECONDS = "seconds"
    """
)

SCHEMA = textwrap.dedent(
    """
    from __future__ import annotations

    from pydantic import BaseModel

    from posthog.schema_enums import (
        Interval as Interval,
        Unit as Unit,
    )


    class DateRange(BaseModel):
        date_from: str | None = None


    class TrendsQuery(BaseModel):
        dateRange: DateRange | None = None
        interval: Interval | None = None


    class Unrelated(BaseModel):
        name: str


    QuerySchemaRoot = TrendsQuery | Unrelated

    TrendsQuery.model_rebuild()
    """
)


def _edit(source: str, old: str, new: str) -> str:
    assert old in source
    return source.replace(old, new)


def _diff(schema: str = SCHEMA, enums: str = ENUMS) -> tuple[set[str], set[str]]:
    return scope.changed_schema_types(
        {"posthog/schema.py": SCHEMA, "posthog/schema_enums.py": ENUMS},
        {"posthog/schema.py": schema, "posthog/schema_enums.py": enums},
    )


class TestChangedSchemaTypes(unittest.TestCase):
    # A type that contains a changed one validates and serializes differently too, so a
    # caller naming only the container must be reached.
    @parameterized.expand(
        [
            (
                "field_added_to_a_nested_type",
                _edit(
                    SCHEMA,
                    "date_from: str | None = None",
                    "date_from: str | None = None\n    date_to: str | None = None",
                ),
                ENUMS,
                {"DateRange"},
                {"DateRange", "TrendsQuery", "QuerySchemaRoot"},
            ),
            (
                "enum_member_added",
                SCHEMA,
                _edit(ENUMS, 'WEEK = "week"', 'WEEK = "week"\n    MONTH = "month"'),
                {"Interval"},
                {"Interval", "TrendsQuery", "QuerySchemaRoot"},
            ),
            (
                "rebuild_call_dropped",
                _edit(SCHEMA, "TrendsQuery.model_rebuild()", ""),
                ENUMS,
                {"TrendsQuery"},
                {"TrendsQuery", "QuerySchemaRoot"},
            ),
            ("new_type_only", SCHEMA + "\n\nclass Fresh(BaseModel):\n    x: int\n", ENUMS, set(), set()),
        ]
    )
    def test_attributes_type_changes(self, _name, schema, enums, changed, affected) -> None:
        self.assertEqual(_diff(schema, enums), (changed, affected))

    @parameterized.expand(
        [
            (
                "type_removed",
                _edit(SCHEMA, "class Unrelated(BaseModel):\n    name: str\n", ""),
                ENUMS,
                "removed or renamed",
            ),
            (
                "module_level_import",
                _edit(SCHEMA, "from pydantic import BaseModel", "from pydantic import BaseModel, Field"),
                ENUMS,
                "outside its type definitions",
            ),
            ("enum_reexport_dropped", _edit(SCHEMA, "    Unit as Unit,\n", ""), ENUMS, "stopped re-exporting"),
            ("does_not_parse", SCHEMA + "\nclass Broken(:\n", ENUMS, "does not parse"),
            ("enum_module_statement", SCHEMA, "import os\n" + ENUMS, "outside its type definitions"),
        ]
    )
    def test_falls_back_on_changes_it_cannot_attribute(self, _name, schema, enums, reason) -> None:
        with self.assertRaisesRegex(scope._Unattributable, reason):
            _diff(schema, enums)


class TestFilesReferencing(unittest.TestCase):
    @parameterized.expand(
        [
            ("names_a_changed_type", "from posthog.schema import TrendsQuery\n", "referencing"),
            ("aliased_module", "import posthog.schema as ps\nq = ps.TrendsQuery()\n", "referencing"),
            ("names_another_type", "from posthog.schema import Unrelated\n", None),
            ("patches_by_string", 'from unittest import mock\nmock.patch("posthog.schema.Unrelated")\n', "wildcard"),
            ("imports_by_string", 'import importlib\nimportlib.import_module("posthog.schema")\n', "wildcard"),
            ("passes_the_module_around", "import posthog.schema\nregister(posthog.schema)\n", "wildcard"),
            ("does_not_parse", "from posthog.schema import TrendsQuery\ndef broken(:\n", "wildcard"),
        ]
    )
    def test_classifies_a_module(self, _name: str, source: str, expected: str | None) -> None:
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "module.py").write_text(source)
            referencing, wildcard = scope.files_referencing(
                Path(root), ["module.py"], {"TrendsQuery"}, scope.load_scanner()
            )
        self.assertEqual(
            (referencing, wildcard),
            (["module.py"] if expected == "referencing" else [], ["module.py"] if expected == "wildcard" else []),
        )
