from uuid import uuid4

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import exceptions

from products.workflows.backend.services.account_audience import is_account_audience, parse_account_audience_filters


class TestParseAccountAudienceFilters(SimpleTestCase):
    def test_valid_filters_round_trip(self):
        definition_id = uuid4()
        parsed = parse_account_audience_filters(
            {
                "audience_type": "accounts",
                "properties": [
                    {"key": str(definition_id), "type": "account_custom_property", "operator": "exact", "value": ["x"]}
                ],
                "tag_names": ["vip"],
                "assigned_to_user_ids": [7],
                "all_roles_unassigned": True,
            }
        )

        assert parsed.tag_names == ("vip",)
        assert parsed.assigned_to_user_ids == (7,)
        assert parsed.all_roles_unassigned is True
        assert parsed.custom_properties[0].definition_id == definition_id
        assert parsed.custom_properties[0].operator == "exact"
        assert parsed.custom_properties[0].value == ["x"]

    @parameterized.expand(
        [
            ("person_property_entry", {"properties": [{"key": "email", "type": "person", "operator": "exact"}]}),
            ("cohort_entry", {"properties": [{"key": "id", "type": "cohort", "value": 1, "operator": "in"}]}),
            ("non_uuid_key", {"properties": [{"key": "tier", "type": "account_custom_property", "operator": "exact"}]}),
            ("non_list_properties", {"properties": "nope"}),
            (
                "unknown_operator",
                {
                    "properties": [
                        {
                            "key": "7b0d4a12-8f0e-4c39-9a5f-52dd8f2f7a11",
                            "type": "account_custom_property",
                            "operator": "equals",
                            "value": ["x"],
                        }
                    ]
                },
            ),
            (
                "missing_value",
                {
                    "properties": [
                        {
                            "key": "7b0d4a12-8f0e-4c39-9a5f-52dd8f2f7a11",
                            "type": "account_custom_property",
                            "operator": "exact",
                            "value": [],
                        }
                    ]
                },
            ),
            ("non_list_tag_names", {"tag_names": "vip"}),
            ("non_str_tag_entries", {"tag_names": [1]}),
            ("non_int_user_ids", {"assigned_to_user_ids": ["7"]}),
        ]
    )
    def test_malformed_filters_raise(self, _name, overrides):
        with self.assertRaises(exceptions.ValidationError):
            parse_account_audience_filters({"audience_type": "accounts", **overrides})

    @parameterized.expand(
        [
            ("accounts", {"audience_type": "accounts"}, True),
            ("persons_explicit", {"audience_type": "persons"}, False),
            ("absent", {}, False),
            ("none", None, False),
        ]
    )
    def test_is_account_audience(self, _name, filters, expected):
        assert is_account_audience(filters) is expected
