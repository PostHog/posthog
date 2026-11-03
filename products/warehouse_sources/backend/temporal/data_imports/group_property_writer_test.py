import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import PropertyDefinition
from posthog.models.group.util import get_group_by_key
from posthog.test.persons import create_group

from products.warehouse_sources.backend.temporal.data_imports.group_property_writer import (
    GroupPropertyUpdate,
    GroupPropertyWriter,
    detect_property_type,
    parse_group_update,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.group_property_writer"
_NOW = 1_800_000_000.0

_VALID_PAYLOAD = {
    "kind": "group",
    "team_id": 1,
    "project_id": 2,
    "group_type_index": 0,
    "group_key": "acme",
    "properties": {"tier": "pro"},
}


class TestDetectPropertyType:
    @parameterized.expand(
        [
            ("bool", "is_active", True, "Boolean"),
            ("bool_with_date_keyword", "updated_at", False, "Boolean"),
            ("lowercase_boolean_string", "flag", "true", "Boolean"),
            ("padded_uppercase_boolean_string", "flag", " FALSE ", "Boolean"),
            ("mixed_case_boolean_string_is_text", "flag", "True", "String"),
            ("plain_string", "tier", "pro", "String"),
            ("date_string", "renewal", "2026-03-01", "DateTime"),
            ("date_time_string", "renewal", "2026-03-01 10:00:00", "DateTime"),
            ("rfc3339_string", "renewal", "2026-03-01T10:00:00.5Z", "DateTime"),
            ("rfc2822_string", "renewal", "Sun, 01 Mar 2026 10:00:00 +0000", "DateTime"),
            ("compact_digits_are_text", "code", "20260301", "String"),
            ("int", "seats", 12, "Numeric"),
            ("float", "mrr", 12.5, "Numeric"),
            ("recent_timestamp_with_date_keyword", "created_at", int(_NOW), "DateTime"),
            ("recent_timestamp_without_date_keyword", "seats", int(_NOW), "Numeric"),
            ("old_timestamp_with_date_keyword", "created_at", 1_000_000_000, "Numeric"),
            ("float_timestamp_with_date_keyword", "created_at", _NOW, "Numeric"),
            ("utm_number_is_text", "utm_campaign", 2026, "String"),
            ("null", "tier", None, None),
            ("list", "tags", ["a"], None),
            ("object", "meta", {"a": 1}, None),
        ]
    )
    def test_detects_the_type_ingestion_assigns(self, _name, key, value, expected):
        assert detect_property_type(key, value, now=lambda: _NOW) == expected


class TestParseGroupUpdate:
    def test_maps_a_complete_message(self):
        assert parse_group_update({**_VALID_PAYLOAD, "group_key": 42}) == GroupPropertyUpdate(
            team_id=1, project_id=2, group_type_index=0, group_key="42", properties={"tier": "pro"}
        )

    @parameterized.expand(
        [
            ("no_project_id", {"project_id": None}),
            ("no_team_id", {"team_id": None}),
            ("boolean_id", {"team_id": True}),
            ("no_group_type_index", {"group_type_index": None}),
            ("group_type_index_out_of_range", {"group_type_index": 5}),
            ("negative_group_type_index", {"group_type_index": -1}),
            ("empty_group_key", {"group_key": ""}),
            ("no_properties", {"properties": {}}),
            ("properties_not_an_object", {"properties": ["tier"]}),
        ]
    )
    def test_returns_none_for_a_message_it_cannot_write(self, _name, overrides):
        assert parse_group_update({**_VALID_PAYLOAD, **overrides}) is None


class TestGroupPropertyWriter(BaseTest):
    def setUp(self):
        super().setUp()
        ch_patches = [patch(f"{_MODULE}.raw_create_group_ch"), patch("posthog.models.group.util.raw_create_group_ch")]
        self.write_ch, self.create_ch = (p.start() for p in ch_patches)
        for p in ch_patches:
            self.addCleanup(p.stop)

    def _update(self, properties: dict, group_key: str = "acme") -> GroupPropertyUpdate:
        return GroupPropertyUpdate(
            team_id=self.team.pk,
            project_id=self.team.project_id,
            group_type_index=0,
            group_key=group_key,
            properties=properties,
        )

    def _definition_types(self) -> dict[str, tuple[str | None, bool]]:
        rows = PropertyDefinition.objects.filter(team=self.team, type=PropertyDefinition.Type.GROUP, group_type_index=0)
        return {row.name: (row.property_type, row.is_numerical) for row in rows}

    def test_merges_onto_an_existing_group_and_keeps_other_properties(self):
        created_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        create_group(
            team=self.team,
            group_type_index=0,
            group_key="acme",
            group_properties={"name": "Acme", "tier": "free"},
            created_at=created_at,
        )

        outcome = GroupPropertyWriter().write(self._update({"tier": "pro", "seats": 12}))

        merged = {"name": "Acme", "tier": "pro", "seats": 12}
        assert outcome == "updated"
        group = get_group_by_key(self.team.pk, 0, "acme")
        assert group is not None
        assert group.group_properties == merged
        self.write_ch.assert_called_once_with(self.team.pk, 0, "acme", merged, created_at)

    def test_skips_the_write_when_no_property_changes(self):
        create_group(team=self.team, group_type_index=0, group_key="acme", group_properties={"tier": "pro"})

        assert GroupPropertyWriter().write(self._update({"tier": "pro"})) == "unchanged"
        self.write_ch.assert_not_called()

    def test_creates_a_group_that_does_not_exist(self):
        assert GroupPropertyWriter().write(self._update({"tier": "pro"}, group_key="new-co")) == "created"

        group = get_group_by_key(self.team.pk, 0, "new-co")
        assert group is not None
        assert group.group_properties == {"tier": "pro"}
        assert self.create_ch.call_args.args[:4] == (self.team.pk, 0, "new-co", {"tier": "pro"})

    def test_sets_a_missing_definition_type_and_keeps_an_existing_one(self):
        create_group(team=self.team, group_type_index=0, group_key="acme", group_properties={})
        for name, property_type in (("untyped", None), ("typed", "String")):
            PropertyDefinition.objects.create(
                team=self.team,
                project_id=self.team.project_id,
                name=name,
                type=PropertyDefinition.Type.GROUP,
                group_type_index=0,
                property_type=property_type,
            )
        PropertyDefinition.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            name="untyped",
            type=PropertyDefinition.Type.GROUP,
            group_type_index=1,
        )

        GroupPropertyWriter().write(self._update({"untyped": 5, "typed": 7, "absent": True, "empty": None}))

        assert self._definition_types() == {
            "untyped": ("Numeric", True),
            "typed": ("String", False),
            "absent": ("Boolean", False),
        }
        other_group_type = PropertyDefinition.objects.get(team=self.team, name="untyped", group_type_index=1)
        assert other_group_type.property_type is None

    def test_a_repeated_property_issues_no_definition_query(self):
        create_group(team=self.team, group_type_index=0, group_key="acme", group_properties={})
        writer = GroupPropertyWriter()
        writer.write(self._update({"tier": "pro"}))

        with self.assertNumQueries(0):
            writer.write(self._update({"tier": "enterprise"}))
